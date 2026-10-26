"""The Digital Twin in the cloud: one always-on Modal container (docs/CLOUD.md).

    modal deploy deploy/modal_app.py      start it, or update it after a change (from the project root)
    modal app stop digital-twin           switch it off; the data stays in the volume

The container runs what deploy/supervisor.py runs on the laptop, except Caddy: PostgreSQL, the
network emulator, the Digital Twin Engine and the Django API on Waitress. Modal terminates HTTPS,
and the dashboard on Vercel forwards /api, /admin and /static here.

The database lives on the container's own disk. It is dumped to the volume every 10 minutes and
at shutdown, and a new container restores the latest dump, so the history survives restarts,
redeploys and being switched off. While switched off the network has no history; on the next
start the gap is filled from the emulator, as on the very first start, when 14 days of history
are generated and the models trained (deploy/setup.ps1 does the same on the laptop). The API
answers meanwhile; the engine starts when the history is complete.

There is never more than one container (max_containers=1): a second one would run a second
database.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path("/app")
BACKEND = APP_DIR / "backend"
VAR = APP_DIR / "var"                     # the Modal volume: models, emulator clock, database dumps
DUMP = VAR / "backup" / "twin.dump"
PGDATA = Path("/pgdata")                  # the container's own disk
DATABASE_URL = "postgresql://postgres@127.0.0.1:5432/twin?sslmode=disable"
EMULATOR = "http://127.0.0.1:9161"
PORT = 8000
BACKUP_SECONDS = 600
HISTORY_DAYS = 14
GAP_TO_BACKFILL = timedelta(minutes=15)   # a shorter gap is treated like a brief outage
WAT = timezone(timedelta(hours=1))        # D18: West Africa Time

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("postgresql", "tzdata")
    .uv_sync(str(ROOT / "backend"))       # the backend's locked dependencies (uv.lock)
    .env({"PYTHONUTF8": "1", "DJANGO_SETTINGS_MODULE": "config.settings.cloud", "DATABASE_URL": DATABASE_URL,
          "DJANGO_STATIC_ROOT": "/app/static", "EMULATOR_URL": EMULATOR})
    .add_local_dir(ROOT / "backend", str(BACKEND),
                   ignore=[".venv", "**/__pycache__", "**/.pytest_cache", "**/.ruff_cache", ".env",
                           "tests", "evaluation/results"])
    .add_local_dir(ROOT / "data", str(APP_DIR / "data"))
)
volume = modal.Volume.from_name("digital-twin-var", create_if_missing=True)
secret = modal.Secret.from_name("digital-twin", required_keys=[
    "DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS",
    "DT_SENIOR_PASSWORD", "DT_JUNIOR_PASSWORD"])
app = modal.App("digital-twin", image=image)


def log(message: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} cloud: {message}", flush=True)


def run(*command: str, cwd: Path = BACKEND, capture: bool = False) -> str:
    done = subprocess.run(list(command), cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)
    return (done.stdout or "").strip()


def manage(*args: str, capture: bool = False) -> str:
    return run(sys.executable, "manage.py", *args, capture=capture)


def django_says(code: str) -> str:
    """Run a line of Python in Django's shell and return the last line it printed."""
    return manage("shell", "-c", code, capture=True).splitlines()[-1]


def get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # local addresses only
            return json.loads(response.read())
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------- the database
PG_BIN = None


def pg(tool: str) -> str:
    global PG_BIN
    PG_BIN = PG_BIN or sorted(Path("/usr/lib/postgresql").glob("*/bin"))[-1]
    return str(PG_BIN / tool)


def start_database() -> None:
    if not (PGDATA / "PG_VERSION").exists():
        PGDATA.mkdir(parents=True, exist_ok=True)
        shutil.chown(PGDATA, "postgres", "postgres")
        # trust: the server listens on 127.0.0.1 inside this container only
        run("runuser", "-u", "postgres", "--", pg("initdb"), "-D", str(PGDATA), "-U", "postgres",
            "--auth=trust", "-E", "UTF8", "--locale=C.UTF-8", cwd=Path("/"))
    run("runuser", "-u", "postgres", "--", pg("pg_ctl"), "-D", str(PGDATA), "-l", "/tmp/postgres.log", "-w",
        "-o", "-c listen_addresses=127.0.0.1 -c port=5432 -c unix_socket_directories=/tmp", "start", cwd=Path("/"))
    client = ("-h", "127.0.0.1", "-U", "postgres")
    exists = run(pg("psql"), *client, "-tAc", "SELECT 1 FROM pg_database WHERE datname = 'twin'",
                 "postgres", capture=True, cwd=Path("/"))
    if exists != "1":
        run(pg("createdb"), *client, "twin", cwd=Path("/"))
        if DUMP.exists():
            log(f"restoring the database from {DUMP.name} ({DUMP.stat().st_size / 1e6:.1f} MB)")
            run(pg("pg_restore"), *client, "-d", "twin", "--no-owner", str(DUMP), cwd=Path("/"))


def dump_database() -> None:
    DUMP.parent.mkdir(parents=True, exist_ok=True)
    tmp = DUMP.with_suffix(".tmp")
    run(pg("pg_dump"), "-h", "127.0.0.1", "-U", "postgres", "-Fc", "-f", str(tmp), "twin", cwd=Path("/"))
    os.replace(tmp, DUMP)
    volume.commit()


# ------------------------------------------------------------------------- the services
class Service:
    """A long-running process, started again if it stops (as deploy/supervisor.py does)."""

    def __init__(self, name: str, command: list[str]):
        self.name, self.command = name, command
        self.process: subprocess.Popen | None = None
        self.exits: list[float] = []

    def start(self) -> None:
        log(f"starting {self.name}")
        self.process = subprocess.Popen(self.command, cwd=BACKEND, stdin=subprocess.DEVNULL)

    def keep_running(self) -> None:
        if self.process is None or self.process.poll() is None:
            return
        now = time.time()
        self.exits = [t for t in self.exits if now - t < 300] + [now]
        log(f"{self.name} exited with code {self.process.returncode}; starting it again")
        time.sleep(min(60.0, 2.0 ** len(self.exits)))
        self.start()

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def emulator(mode: str, start: str) -> Service:
    return Service("emulator", [sys.executable, "-m", "netemu", "serve", "--mode", mode,
                                "--speed", os.environ.get("DT_SPEED", "1"), "--start", start])


@app.cls(volumes={str(VAR): volume}, secrets=[secret], cpu=(0.25, 1.0), memory=(1024, 3072),
         min_containers=1, max_containers=1, startup_timeout=900)
@modal.concurrent(max_inputs=100)
class Twin:
    @modal.enter()
    def boot(self) -> None:
        self.services: list[Service] = []
        self.stopping = threading.Event()
        start_database()
        manage("migrate", "--noinput")
        manage("createcachetable")
        manage("setup_roles")
        for username, role, key in (("senior1", "senior", "DT_SENIOR_PASSWORD"),
                                    ("junior1", "junior", "DT_JUNIOR_PASSWORD")):
            if django_says(f"from django.contrib.auth.models import User; "
                           f"print(User.objects.filter(username='{username}').exists())") != "True":
                manage("setup_roles", "--create-user", username, "--role", role, "--password", os.environ[key])
        if django_says("from apps.twin.models import NetworkDevice; print(NetworkDevice.objects.exists())") != "True":
            manage("import_topology", str(APP_DIR / "data" / "topologies" / "campus.yaml"))
        manage("collectstatic", "--noinput", "--verbosity", "0")
        api = Service("api", [sys.executable, "-m", "waitress", f"--listen=0.0.0.0:{PORT}", "--threads=8",
                              "config.wsgi:application"])
        api.start()
        self.services.append(api)
        threading.Thread(target=self.twin, name="twin", daemon=True).start()

    @modal.web_server(PORT, startup_timeout=120, label="digital-twin")
    def web(self) -> None:
        """The API, started in boot(); Modal routes HTTPS to its port."""

    def twin(self) -> None:
        """Bring the history up to date, then keep the emulator and the engine running."""
        try:
            has_history = django_says(
                "from apps.twin.models import MonitoringRecord; print(MonitoringRecord.objects.exists())") == "True"
            if has_history:
                net = emulator("live", "resume")
            else:
                first_day = datetime.now(WAT).replace(hour=0, minute=0, second=0, microsecond=0)
                net = emulator("stepped", (first_day - timedelta(days=HISTORY_DAYS)).isoformat())
            net.start()
            self.services.append(net)
            info = None
            while info is None:
                if self.stopping.wait(2):
                    return
                info = get_json(f"{EMULATOR}/v1/info")
            behind = datetime.now(UTC) - datetime.fromisoformat(info["time"])
            if behind > GAP_TO_BACKFILL:
                days = behind.total_seconds() / 86400
                log(f"the network clock is {days:.2f} days behind: generating that history first")
                manage("backfill_history", "--days", f"{days:.4f}", "--then-live",
                       "--speed", os.environ.get("DT_SPEED", "1"))
            if not has_history or not any((VAR / "models").glob("*")):
                manage("train_models", "--days", str(HISTORY_DAYS))
            engine = Service("engine", [sys.executable, "manage.py", "run_twin"])
            engine.start()
            self.services.append(engine)
        except Exception as error:  # noqa: BLE001 - the API stays up; the System page shows the engine missing
            log(f"could not bring the twin up: {error!r}")
        last_backup = time.time()
        while not self.stopping.is_set():
            for service in self.services:
                service.keep_running()
            if time.time() - last_backup > BACKUP_SECONDS:
                try:
                    dump_database()
                except (OSError, subprocess.CalledProcessError) as error:
                    log(f"backup failed: {error!r}")
                last_backup = time.time()
            self.stopping.wait(5)

    @modal.exit()
    def shutdown(self) -> None:
        self.stopping.set()
        for service in reversed(self.services):
            service.stop()
        dump_database()
        log("stopped; database saved to the volume")
