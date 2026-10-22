"""Supervisor: starts the whole system, restarts anything that stops, stops it all again (NFR2).

    backend\\.venv\\Scripts\\python.exe deploy\\supervisor.py run [--speed 20] [--local-db] [--no-emulator]
    backend\\.venv\\Scripts\\python.exe deploy\\supervisor.py status
    backend\\.venv\\Scripts\\python.exe deploy\\supervisor.py stop

Started by deploy\\start.ps1 and stopped by deploy\\stop.ps1. Processes, in start order:

    emulator   the stand-in real network and its read-only telemetry feed   127.0.0.1:9161
    api        Django REST API on Waitress, behind Caddy                    127.0.0.1:8000
    engine     the Digital Twin Engine (monitoring cycle)
    caddy      HTTPS front door: dashboard + API on https://localhost

Each one logs to var\\log\\<name>.log. If a process exits it is started again after a short,
growing pause; after 5 failures in 5 minutes it is left stopped and reported as failed,
while the others keep running. With --local-db a local PostgreSQL (deploy\\localpg.py) is
used instead of Neon, for demos without internet (plan section 12.2, offline fallback).

Only the Python standard library is used, so this runs from the backend's virtual environment.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
RUN = ROOT / "var" / "run"
LOGS = ROOT / "var" / "log"
STATE = RUN / "supervisor.json"
STOP_REQUEST = RUN / "stop.request"
LOCALPG_PYTHON = ROOT / "var" / "localpg" / "pgenv" / "Scripts" / "python.exe"

CREATE_NO_WINDOW = 0x08000000          # no console window for the services
MAX_FAILURES, FAILURE_WINDOW = 5, 300  # give up after 5 exits within 5 minutes
LOG_ROLL_BYTES = 5_000_000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # local addresses only
            return 200 <= response.status < 500
    except OSError:
        return False


def _kill_tree(pid: int) -> None:
    # The virtual environment's python.exe is a launcher that runs the real interpreter as a
    # child, so the whole process tree must be stopped, not just the launcher.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def _alive(pid: int) -> bool:
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
    return str(pid) in result.stdout


@dataclass
class Service:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str]
    ready_url: str | None = None
    process: subprocess.Popen | None = None
    started_at: float = 0.0
    restarts: int = 0
    exits: list[float] = field(default_factory=list)
    failed: bool = False
    next_start: float = 0.0

    def start(self) -> None:
        log = LOGS / f"{self.name}.log"
        if log.exists() and log.stat().st_size > LOG_ROLL_BYTES:
            log.replace(log.with_suffix(".log.1"))
        with open(log, "a", encoding="utf-8", buffering=1) as handle:  # the child keeps its own copy
            handle.write(f"\n===== {_now()} supervisor: starting {self.name}: {' '.join(self.command)}\n")
            self.process = subprocess.Popen(self.command, cwd=self.cwd, env=self.env, stdout=handle,
                                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            creationflags=CREATE_NO_WINDOW)
        self.started_at = time.time()

    def wait_ready(self, seconds: float) -> bool:
        if self.ready_url is None:
            return True
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False
            if _get(self.ready_url):
                return True
            time.sleep(1.0)
        return False

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            _kill_tree(self.process.pid)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self.process = None

    def describe(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        return {"state": "failed" if self.failed else "running" if running else "starting",
                "pid": self.process.pid if self.process is not None else None,
                "restarts": self.restarts,
                "up_seconds": round(time.time() - self.started_at) if running else 0}


def find_caddy() -> str | None:
    """caddy on the PATH, or where winget installs it (a shell opened before the install has the old PATH)."""
    found = shutil.which("caddy")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    matches = sorted(packages.glob("CaddyServer.Caddy_*/caddy.exe")) if packages.exists() else []
    return str(matches[-1]) if matches else None


def build_services(args: argparse.Namespace, database_url: str | None) -> list[Service]:
    base = {**os.environ, "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"}
    django = {**base, "DJANGO_SETTINGS_MODULE": "config.settings.prod"}
    if database_url:
        django["DATABASE_URL"] = database_url
    services = []
    if not args.no_emulator:
        services.append(Service(
            "emulator",
            [str(PYTHON), "-m", "netemu", "serve", "--mode", "live", "--speed", str(args.speed), "--start", "resume"],
            BACKEND, base, ready_url="http://127.0.0.1:9161/v1/info"))
    services.append(Service(
        "api",
        [str(PYTHON), "-m", "waitress", "--listen=127.0.0.1:8000", "--threads=8",
         "--trusted-proxy=127.0.0.1", "--trusted-proxy-headers=x-forwarded-for x-forwarded-proto x-forwarded-host",
         "--clear-untrusted-proxy-headers", "config.wsgi:application"],
        BACKEND, django, ready_url="http://127.0.0.1:8000/api/v1/auth/csrf"))
    services.append(Service("engine", [str(PYTHON), "manage.py", "run_twin"], BACKEND, django))
    caddy = find_caddy()
    if caddy is None:
        raise SystemExit("Caddy was not found. Install it with: winget install CaddyServer.Caddy")
    services.append(Service(
        "caddy", [caddy, "run", "--config", str(ROOT / "deploy" / "Caddyfile"), "--adapter", "caddyfile"],
        ROOT, base, ready_url="http://127.0.0.1:2019/config/"))
    return services


def write_state(services: list[Service], extra: dict) -> None:
    """Publish what is running. Windows refuses the replace while someone is reading the file
    (deploy\\start.ps1, `supervisor.py status`), so retry briefly, then skip: it is rewritten every
    2 seconds, and a status file must never take the services down."""
    payload = {"supervisor_pid": os.getpid(), "updated": _now(), **extra,
               "services": {s.name: s.describe() for s in services}}
    tmp = STATE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for attempt in range(8):
            try:
                os.replace(tmp, STATE)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
    except OSError as error:
        print(f"{_now()} could not update {STATE.name}: {error}", file=sys.stderr)


def read_state() -> dict | None:
    """The supervisor's published state, or None if the system is not running."""
    for attempt in range(8):
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):          # being replaced at this moment: try again
            time.sleep(0.05 * (attempt + 1))
    return None


def describe_database(local_url: str | None) -> str:
    """Where the data lives, for the status line (never the password)."""
    from urllib.parse import urlparse

    url = local_url or os.environ.get("DATABASE_URL", "")
    if not url:
        return "as set in backend/.env"
    host = urlparse(url).hostname or "?"
    return f"local PostgreSQL ({host})" if host in ("127.0.0.1", "localhost") else f"{host}"


def start_local_database() -> str:
    if not LOCALPG_PYTHON.exists():
        raise SystemExit("The local database is not installed (var/localpg/pgenv). See docs/INSTALL.md, offline fallback.")
    result = subprocess.run([str(LOCALPG_PYTHON), str(ROOT / "deploy" / "localpg.py"), "start"],
                            capture_output=True, text=True, check=True, creationflags=CREATE_NO_WINDOW)
    uri = result.stdout.strip().splitlines()[-1]
    # pgserver listens on 127.0.0.1 without TLS
    return uri + ("&" if "?" in uri else "?") + "sslmode=disable" if "sslmode" not in uri else uri


def run(args: argparse.Namespace) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        previous = (read_state() or {}).get("supervisor_pid")
        if previous and previous != os.getpid() and _alive(previous):
            raise SystemExit(f"The system is already running (supervisor process {previous}). Stop it first.")
    STOP_REQUEST.unlink(missing_ok=True)
    database_url = start_local_database() if args.local_db else None
    services = build_services(args, database_url)
    extra = {"speed": args.speed, "database": describe_database(database_url), "started": _now()}

    try:
        for service in services:                                   # start in order, each once ready
            service.start()
            if not service.wait_ready(90):
                print(f"{service.name} did not become ready; see var/log/{service.name}.log", file=sys.stderr)
            write_state(services, extra)
        while not STOP_REQUEST.exists():
            now = time.time()
            for service in services:
                if service.failed or service.process is None or service.process.poll() is None:
                    if service.process is None and not service.failed and now >= service.next_start:
                        service.start()
                    continue
                code = service.process.returncode
                service.process = None
                service.exits = [t for t in service.exits if now - t < FAILURE_WINDOW] + [now]
                if len(service.exits) >= MAX_FAILURES:
                    service.failed = True
                    print(f"{_now()} {service.name} stopped {MAX_FAILURES} times in 5 minutes; leaving it stopped",
                          file=sys.stderr)
                    continue
                service.restarts += 1
                pause = min(60.0, 2.0 ** len(service.exits))
                service.next_start = now + pause
                with open(LOGS / f"{service.name}.log", "a", encoding="utf-8") as log:
                    log.write(f"===== {_now()} supervisor: {service.name} exited with code {code}; "
                              f"restarting in {pause:.0f} s\n")
            write_state(services, extra)
            time.sleep(2.0)
    except KeyboardInterrupt:
        pass
    finally:
        for service in reversed(services):
            service.stop()
        if args.local_db:
            subprocess.run([str(LOCALPG_PYTHON), str(ROOT / "deploy" / "localpg.py"), "stop"],
                           capture_output=True, check=False, creationflags=CREATE_NO_WINDOW)
        STOP_REQUEST.unlink(missing_ok=True)
        STATE.unlink(missing_ok=True)


def status(_: argparse.Namespace) -> None:
    state = read_state()
    if state is None:
        print("The system is not running.")
        return
    print(f"Supervisor process {state['supervisor_pid']}, started {state.get('started')}, "
          f"database: {state.get('database')}, emulator speed {state.get('speed')}x")
    for name, info in state["services"].items():
        print(f"  {name:<9} {info['state']:<9} pid {info['pid']}  restarts {info['restarts']}  up {info['up_seconds']} s")


def stop(_: argparse.Namespace) -> None:
    state = read_state()
    if state is None:
        print("The system is not running.")
        return
    STOP_REQUEST.touch()
    deadline = time.time() + 40
    while STATE.exists() and time.time() < deadline:
        time.sleep(1.0)
    if STATE.exists():                       # the supervisor did not finish: stop everything directly
        for info in state["services"].values():
            if info.get("pid"):
                _kill_tree(info["pid"])
        if state.get("supervisor_pid"):
            _kill_tree(state["supervisor_pid"])
        STATE.unlink(missing_ok=True)
        STOP_REQUEST.unlink(missing_ok=True)
    print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("run", help="start everything and keep it running")
    start.add_argument("--speed", type=float, default=1.0, help="emulator speed (network seconds per second)")
    start.add_argument("--local-db", action="store_true", help="use the local PostgreSQL instead of Neon")
    start.add_argument("--no-emulator", action="store_true", help="do not start the emulator (another source is used)")
    sub.add_parser("status", help="show what is running")
    sub.add_parser("stop", help="stop everything")
    args = parser.parse_args()
    {"run": run, "status": status, "stop": stop}[args.command](args)


if __name__ == "__main__":
    main()
