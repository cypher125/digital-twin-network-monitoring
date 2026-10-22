"""Helpers for experiments on the running system (E5-E7): a signed-in API client, the
supervisor's process list, per-process resource readings and the emulator's lab interface.

Standard library plus psutil only, so it runs against the deployed system started with
deploy/start.ps1 (Caddy on https://localhost, the supervisor writing var/run/supervisor.json).
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from .common import ROOT

STATE = ROOT / "var" / "run" / "supervisor.json"
LAB_TOKEN = ROOT / "var" / "netemu" / "lab_token"
SERVICES = ("emulator", "api", "engine", "caddy")


class Dashboard:
    """A signed-in client of the REST API, as the dashboard uses it (polls send X-Poll: 1)."""

    def __init__(self, base: str = "https://localhost", username: str | None = None, password: str | None = None,
                 timeout: float = 15.0):
        if username is None:
            username, _, password = os.environ.get("DT_SENIOR", "").partition(":")
        if not username:
            raise SystemExit("Set DT_SENIOR=username:password")
        self.base = base.rstrip("/") + "/api/v1/"
        self.username, self.password, self.timeout = username, password or "", timeout
        context = ssl.create_default_context()
        context.check_hostname = False          # Caddy's local certificate may not be trusted here
        context.verify_mode = ssl.CERT_NONE
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                                  urllib.request.HTTPSHandler(context=context))

    def _token(self) -> str:
        return next((c.value or "" for c in self.jar if c.name == "csrftoken"), "")

    def request(self, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method="POST" if body is not None else "GET",
            headers={"Content-Type": "application/json", "X-Poll": "1", "X-CSRFToken": self._token(),
                     "Referer": self.base})
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def sign_in(self) -> None:
        self.request("auth/csrf")
        self.request("auth/login", {"username": self.username, "password": self.password})

    def get(self, path: str) -> dict | None:
        """GET, signing in again once if the session has gone (for example after an API restart)."""
        try:
            return self.request(path)
        except urllib.error.HTTPError as error:
            if error.code == 403:
                try:
                    self.sign_in()
                    return self.request(path)
                except (OSError, urllib.error.URLError):
                    return None
            return None
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def timed_get(self, path: str) -> tuple[float, bool]:
        """(seconds, ok) for one request."""
        began = time.perf_counter()
        try:
            self.request(path)
            return time.perf_counter() - began, True
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return time.perf_counter() - began, False


def supervisor_state() -> dict | None:
    for attempt in range(8):                    # the supervisor replaces the file every 2 seconds
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            time.sleep(0.05 * (attempt + 1))
    return None


def service_pids() -> dict[str, int]:
    state = supervisor_state() or {}
    return {name: info["pid"] for name, info in state.get("services", {}).items() if info.get("pid")}


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


class ResourceSampler:
    """CPU (% of one core) and resident memory per service, counting each service's whole process
    tree (the virtual environment's python.exe is a launcher whose child is the real interpreter).

    psutil measures CPU since the previous reading of the same process object, so the objects are
    kept between samples; a service restarted by the supervisor is picked up by its new PID."""

    def __init__(self):
        self._procs: dict[int, object] = {}

    def _proc(self, pid: int):
        import psutil

        if pid not in self._procs:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)        # first reading is always 0: prime it
            self._procs[pid] = proc
        return self._procs[pid]

    def sample(self) -> dict[str, dict]:
        import psutil

        out: dict[str, dict] = {}
        for name, pid in service_pids().items():
            try:
                root = self._proc(pid)
                tree = [root, *[self._proc(c.pid) for c in root.children(recursive=True)]]
            except psutil.Error:
                continue
            rss, cpu = 0, 0.0
            for proc in tree:
                try:
                    rss += proc.memory_info().rss
                    cpu += proc.cpu_percent(interval=None)
                except psutil.Error:
                    continue
            out[name] = {"pid": pid, "rss_mb": round(rss / 1e6, 1), "cpu_pct": round(cpu, 1), "processes": len(tree)}
        return out


def lab(path: str, body: dict, url: str = "http://127.0.0.1:9161") -> dict:
    """POST to the emulator's lab interface (test harness only, never used by the twin)."""
    token = LAB_TOKEN.read_text(encoding="utf-8").strip()
    request = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Lab-Token": token})
    with urllib.request.urlopen(request, timeout=60) as response:  # local address only
        return json.loads(response.read())
