"""Recovery check (NFR2, plan section 9): stop each service abruptly and time how long the
system takes to recover on its own, with no manual step.

    set DT_SENIOR=senior1:password
    backend\\.venv\\Scripts\\python.exe deploy\\recovery_check.py [--url https://localhost]

Needs the system started with deploy\\start.ps1 (the supervisor). For each of the engine,
the emulator and the API, in turn: the service's process tree is killed, then the check
waits until the twin stores a new cycle again. Results go to docs/evidence/P6_recovery.json.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "var" / "run" / "supervisor.json"


class Dashboard:
    """A signed-in API client using only the standard library."""

    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/") + "/api/v1/"
        context = ssl.create_default_context()
        context.check_hostname = False          # Caddy's local certificate may not be trusted here
        context.verify_mode = ssl.CERT_NONE
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                                  urllib.request.HTTPSHandler(context=context))
        self.username, self.password = username, password

    def _token(self) -> str:
        return next((c.value or "" for c in self.jar if c.name == "csrftoken"), "")

    def request(self, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method="POST" if body is not None else "GET",
                                         headers={"Content-Type": "application/json", "X-Poll": "1",
                                                  "X-CSRFToken": self._token(), "Referer": self.base})
        with self.opener.open(request, timeout=10) as response:
            return json.loads(response.read())

    def sign_in(self) -> None:
        self.request("auth/csrf")
        self.request("auth/login", {"username": self.username, "password": self.password})

    def live(self) -> dict | None:
        try:
            return self.request("live")
        except urllib.error.HTTPError as error:
            if error.code == 403:                # the API restarted with a new process: sign in again
                try:
                    self.sign_in()
                    return self.request("live")
                except (OSError, urllib.error.URLError):
                    return None
            return None
        except (OSError, urllib.error.URLError):
            return None


def services() -> dict:
    for attempt in range(8):                    # the supervisor replaces the file every 2 seconds
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))["services"]
        except (OSError, json.JSONDecodeError):
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError(f"cannot read {STATE}")


def kill(name: str) -> int:
    pid = services()[name]["pid"]
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    return pid


def wait_for_new_cycle(dashboard: Dashboard, after: str | None, limit: float) -> tuple[float | None, dict | None]:
    began = time.monotonic()
    while time.monotonic() - began < limit:
        live = dashboard.live()
        if live and live.get("engine_state") == "running" and live.get("last_cycle") and live["last_cycle"] != after:
            return time.monotonic() - began, live
        time.sleep(1.0)
    return None, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Kill each service in turn and time the recovery (NFR2).")
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--limit", type=float, default=240.0, help="seconds to wait for each recovery")
    args = parser.parse_args()
    user, _, password = os.environ.get("DT_SENIOR", "").partition(":")
    if not STATE.exists() or not user:
        sys.exit("Start the system with deploy\\start.ps1 and set DT_SENIOR=username:password")
    dashboard = Dashboard(args.url, user, password)
    dashboard.sign_in()

    results = []
    for name in ("engine", "emulator", "api"):
        before = dashboard.live()
        if before is None or before.get("engine_state") != "running":
            _ready, before = wait_for_new_cycle(dashboard, None, args.limit)
        restarts_before = services()[name]["restarts"]
        killed_at = datetime.now().isoformat(timespec="seconds")
        pid = kill(name)
        seconds, after = wait_for_new_cycle(dashboard, (before or {}).get("last_cycle"), args.limit)
        restarted = services()[name]["restarts"] > restarts_before
        results.append({"service": name, "killed_pid": pid, "killed_at": killed_at, "restarted": restarted,
                        "seconds_to_new_cycle": None if seconds is None else round(seconds, 1),
                        "last_cycle_before": (before or {}).get("last_cycle"),
                        "last_cycle_after": (after or {}).get("last_cycle"), "recovered": seconds is not None})
        print(f"{name:<9} killed (pid {pid}); supervisor restarted it: {restarted}; "
              f"new cycle stored after {'-' if seconds is None else f'{seconds:.1f} s'}")
        time.sleep(5)

    out = ROOT / "docs" / "evidence" / "P6_recovery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"when": datetime.now().isoformat(timespec="seconds"), "url": args.url,
                               "results": results}, indent=2), encoding="utf-8")
    print(f"written to {out}")
    sys.exit(0 if all(r["recovered"] for r in results) else 1)


if __name__ == "__main__":
    main()
