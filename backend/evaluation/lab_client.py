"""Client for the emulator's token-protected lab interface (test harness and demo only).

The twin never uses this module (an import-linter contract forbids it).
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

DEFAULT_URL = os.environ.get("NETEMU_URL", "http://127.0.0.1:9161")
TOKEN_FILE = Path(__file__).resolve().parents[2] / "var" / "netemu" / "lab_token"


def lab_token(explicit: str | None = None) -> str:
    """Given explicitly, from NETEMU_LAB_TOKEN, or from the file the emulator creates on first start."""
    if explicit:
        return explicit
    if os.environ.get("NETEMU_LAB_TOKEN"):
        return os.environ["NETEMU_LAB_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise RuntimeError(f"no lab token: start the emulator once (it creates {TOKEN_FILE}) or set NETEMU_LAB_TOKEN")


class LabClient:
    def __init__(self, url: str = DEFAULT_URL, token: str | None = None, timeout: float = 120.0):
        self.client = httpx.Client(base_url=url.rstrip("/"), timeout=timeout,
                                   headers={"X-Lab-Token": lab_token(token)})

    def close(self) -> None:
        self.client.close()

    def _post(self, path: str, body: dict | None = None) -> dict:
        response = self.client.post(path, json=body or {})
        if response.status_code >= 400:
            raise RuntimeError(f"lab {path} failed ({response.status_code}): {response.text}")
        return response.json()

    def info(self) -> dict:
        response = self.client.get("/v1/info")
        response.raise_for_status()
        return response.json()

    def step(self, cycles: int = 1) -> dict:
        return self._post("/lab/step", {"cycles": cycles})

    def mode(self, mode: str, speed: float | None = None, catch_up: bool = False) -> dict:
        return self._post("/lab/mode", {"mode": mode, "speed": speed, "catch_up": catch_up})

    def surge(self, zone: str = "*", cls: str = "*", multiplier: float = 2.0, ramp_minutes: float = 10,
              hold_minutes: float = 30, start_in_minutes: float = 0) -> dict:
        return self._post("/lab/surge", {"zone": zone, "cls": cls, "multiplier": multiplier,
                                         "ramp_minutes": ramp_minutes, "hold_minutes": hold_minutes,
                                         "start_in_minutes": start_in_minutes})

    def fail_link(self, a: str, b: str, minutes: float | None = None) -> dict:
        body: dict = {"link": [a, b]}
        if minutes is not None:
            body["minutes"] = minutes
        return self._post("/lab/fail", body)

    def repair_link(self, a: str, b: str) -> dict:
        return self._post("/lab/repair", {"link": [a, b]})

    def change(self, change: dict) -> dict:
        return self._post("/lab/change", change)

    def reset(self) -> dict:
        return self._post("/lab/reset")

    def faults(self, enabled: bool | None = None, random_surges: bool | None = None) -> dict:
        body = {}
        if enabled is not None:
            body["enabled"] = enabled
        if random_surges is not None:
            body["random_surges"] = random_surges
        return self._post("/lab/faults", body)

    def truth(self, after: int = 0) -> dict:
        response = self.client.get("/lab/truth", params={"after": after})
        response.raise_for_status()
        return response.json()
