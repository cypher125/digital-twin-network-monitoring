"""HTTP interface of the network emulator.

Read-only telemetry feed (what the digital twin's network adapter uses):
    GET  /v1/info                         clock, mode and speed
    GET  /v1/snapshot                     SNMP-style counters and device statistics
    GET  /v1/flows?after=SEQ              aggregated flow records (NetFlow-style), per cycle
    GET  /v1/events?after=SEQ&wait=SECS   up/down events (trap-style), long-poll

Lab interface (test harness and demo only; needs the X-Lab-Token header):
    POST /lab/step      {"cycles": n}                       advance the clock (stepped mode)
    POST /lab/mode      {"mode": "live"|"stepped", "speed": 20, "catch_up": false}
    POST /lab/surge     {"zone": "HOSTEL", "cls": "video", "multiplier": 2, "ramp_minutes": 15, "hold_minutes": 30}
    POST /lab/fail      {"link": ["A", "B"]} or {"device": "X"}, optional "minutes"
    POST /lab/repair    {"link": ["A", "B"]} or {"device": "X"}
    POST /lab/change    a configuration change applied to the "real network" (evaluation E4)
    POST /lab/reset     undo every lab change
    POST /lab/faults    {"enabled": false, "random_surges": false}   random failures / flash crowds on/off
    GET  /lab/truth?after=SEQ                               ground truth per cycle (evaluation only)
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .network import STEP_SECONDS, EmulatedNetwork

log = logging.getLogger("netemu")


class Runtime:
    """Owns the emulated network and its clock (live or stepped)."""

    def __init__(self, net: EmulatedNetwork, mode: str = "live", speed: float = 1.0):
        self.net = net
        self.mode = "stepped"
        self.speed = float(speed)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if mode == "live":
            self.go_live(speed)

    def info(self) -> dict:
        with self.net.lock:
            return {
                "name": self.net.topo.name,
                "mode": self.mode,
                "speed": self.speed,
                "time": self.net.t.isoformat(),
                "cycle_seconds": self.net.cycle_seconds,
                "step_seconds": STEP_SECONDS,
                "cycle_seq": self.net.cycle_seq,
                "devices": len(self.net.device_names),
                "links": len(self.net.links),
            }

    def step_cycles(self, cycles: int) -> None:
        if self.mode != "stepped":
            raise RuntimeError("switch to stepped mode before stepping the clock")
        with self.net.lock:
            for _ in range(int(cycles) * self.net.steps_per_cycle()):
                self.net.step()

    def go_stepped(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self.mode = "stepped"

    def go_live(self, speed: float | None = None, catch_up: bool = False) -> None:
        self.go_stepped()
        if speed is not None:
            self.speed = float(speed)
        if catch_up:
            # Fast-forward until network time reaches the wall clock.
            with self.net.lock:
                now = datetime.now(UTC)
                while self.net.t + timedelta(seconds=STEP_SECONDS) <= now:
                    self.net.step()
        self._stop = threading.Event()
        self.mode = "live"
        self._thread = threading.Thread(target=self._run_live, name="netemu-clock", daemon=True)
        self._thread.start()

    def _run_live(self) -> None:
        wall0 = time.monotonic()
        sim0 = self.net.t
        step = timedelta(seconds=STEP_SECONDS)
        while not self._stop.is_set():
            target = sim0 + timedelta(seconds=(time.monotonic() - wall0) * self.speed)
            with self.net.lock:
                guard = 0
                while self.net.t + step <= target and guard < 2000:
                    self.net.step()
                    guard += 1
            self._stop.wait(0.05)


def _link_arg(net: EmulatedNetwork, body: dict) -> int:
    a, b = body["link"]
    return net.find_link(a, b)


def make_handler(runtime: Runtime, lab_token: str):
    net = runtime.net

    class Handler(BaseHTTPRequestHandler):
        server_version = "netemu/1.0"

        def log_message(self, format, *args):  # noqa: A002 (name fixed by the base class)
            log.debug("%s - %s", self.address_string(), format % args)

        def _send(self, status: int, payload) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _query(self) -> dict:
            return {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def _lab_allowed(self) -> bool:
            token = self.headers.get("X-Lab-Token", "")
            allowed = hmac.compare_digest(token.encode(), lab_token.encode())
            # every lab call is logged with its caller, so the evaluation can show none came from the twin
            log.info("lab %s %s from %s: %s", self.command, urlparse(self.path).path,
                     self.client_address[0], "allowed" if allowed else "REFUSED")
            if allowed:
                return True
            self._send(403, {"error": "lab interface requires a valid X-Lab-Token"})
            return False

        def do_GET(self):  # noqa: N802 (http.server naming)
            path = urlparse(self.path).path
            q = self._query()
            try:
                if path == "/v1/info":
                    return self._send(200, runtime.info())
                if path == "/v1/snapshot":
                    with net.lock:
                        return self._send(200, net.snapshot())
                if path == "/v1/flows":
                    after = int(q.get("after", 0))
                    with net.lock:
                        cycles = net.flows_after(after)
                        latest = net.cycle_seq
                    return self._send(200, {"latest": latest, "cycles": cycles})
                if path == "/v1/events":
                    after = int(q.get("after", 0))
                    wait = min(float(q.get("wait", 0)), 30.0)
                    with net.events_cond:
                        events = net.events_after(after)
                        if not events and wait > 0:
                            net.events_cond.wait(timeout=wait)
                            events = net.events_after(after)
                        latest = net.event_seq
                    return self._send(200, {"latest": latest, "events": events})
                if path == "/lab/truth":
                    if not self._lab_allowed():
                        return None
                    after = int(q.get("after", 0))
                    with net.lock:
                        return self._send(200, {"latest": net.cycle_seq, "cycles": net.truth_after(after)})
                return self._send(404, {"error": f"unknown path {path}"})
            except (ValueError, KeyError) as exc:
                return self._send(400, {"error": str(exc)})

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            if not path.startswith("/lab/"):
                return self._send(405, {"error": "the telemetry feed is read-only"})
            if not self._lab_allowed():
                return None
            try:
                body = self._body()
                if path == "/lab/step":
                    runtime.step_cycles(int(body.get("cycles", 1)))
                    return self._send(200, runtime.info())
                if path == "/lab/mode":
                    if body.get("mode") == "live":
                        runtime.go_live(body.get("speed"), bool(body.get("catch_up", False)))
                    else:
                        runtime.go_stepped()
                    return self._send(200, runtime.info())
                with net.lock:
                    if path == "/lab/surge":
                        surge = net.add_surge(body.get("zone", "*"), body.get("cls", "*"),
                                              float(body["multiplier"]), float(body.get("ramp_minutes", 10)),
                                              float(body.get("hold_minutes", 30)),
                                              float(body.get("start_in_minutes", 0)))
                        return self._send(200, {"surge_start": surge.start.isoformat(),
                                                "surge_end": surge.end.isoformat()})
                    if path == "/lab/fail":
                        minutes = body.get("minutes")
                        if "link" in body:
                            net.fail_link(_link_arg(net, body), minutes=minutes)
                        else:
                            net.fail_device(net.dev_index[body["device"]], minutes=minutes)
                        return self._send(200, {"ok": True, "time": net.t.isoformat()})
                    if path == "/lab/repair":
                        if "link" in body:
                            net.repair_link(_link_arg(net, body))
                        else:
                            net.repair_device(net.dev_index[body["device"]])
                        return self._send(200, {"ok": True, "time": net.t.isoformat()})
                    if path == "/lab/change":
                        return self._send(200, {"applied": net.apply_change(body), "time": net.t.isoformat()})
                    if path == "/lab/reset":
                        net.reset_changes()
                        return self._send(200, {"ok": True})
                    if path == "/lab/faults":
                        if "enabled" in body:
                            net.random_faults = bool(body["enabled"])
                        if "random_surges" in body:
                            net.traffic.random_surges_enabled = bool(body["random_surges"])
                        return self._send(200, {"random_faults": net.random_faults,
                                                "random_surges": net.traffic.random_surges_enabled})
                return self._send(404, {"error": f"unknown path {path}"})
            except RuntimeError as exc:
                return self._send(409, {"error": str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                return self._send(400, {"error": str(exc)})

    return Handler


def serve(runtime: Runtime, host: str, port: int, lab_token: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(runtime, lab_token))
    server.daemon_threads = True
    return server
