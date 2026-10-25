"""Command line for the network emulator.

    python -m netemu serve [--mode live|stepped] [--speed 20] [--start 2026-10-04T00:00:00+01:00]
    python -m netemu lab info
    python -m netemu lab surge --zone HOSTEL --cls video --multiplier 2 --ramp 15 --hold 30
    python -m netemu lab fail --link ISP-B-GW EDGE-RTR-01 [--minutes 20]
    python -m netemu lab fail --device DIST-LIB
    python -m netemu lab repair --link ISP-B-GW EDGE-RTR-01
    python -m netemu lab mode live --speed 20
    python -m netemu lab step --cycles 60
    python -m netemu lab faults off
    python -m netemu lab reset
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TOPOLOGY = PROJECT_DIR / "data" / "topologies" / "campus.yaml"
log = logging.getLogger("netemu")
DEFAULT_STATE = PROJECT_DIR / "var" / "netemu" / "clock.json"
TOKEN_FILE = PROJECT_DIR / "var" / "netemu" / "lab_token"
DEFAULT_URL = os.environ.get("NETEMU_URL", "http://127.0.0.1:9161")


def resolve_token(explicit: str | None, *, create: bool) -> str:
    """The lab token: given explicitly, from NETEMU_LAB_TOKEN, or from var/netemu/lab_token.

    The emulator creates a random token on first start. There is no built-in default,
    and the twin never reads this file (only the lab command line and the test harness do).
    """
    if explicit:
        return explicit
    if os.environ.get("NETEMU_LAB_TOKEN"):
        return os.environ["NETEMU_LAB_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not create:
        raise SystemExit(f"no lab token found: start the emulator once (it creates {TOKEN_FILE}) "
                         "or set NETEMU_LAB_TOKEN")
    import secrets
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def parse_start(value: str, state_file: Path) -> datetime:
    """'resume' continues from the saved network clock (never rewinding); 'now' uses the wall clock."""
    if value == "resume":
        if state_file.exists():
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            return datetime.fromisoformat(saved["time"])
        value = "now"
    if value == "now":
        now = datetime.now(UTC)
        return now.replace(second=0, microsecond=0)
    start = datetime.fromisoformat(value)
    if start.tzinfo is None:
        raise SystemExit("--start needs a time zone, e.g. 2026-10-04T00:00:00+01:00")
    return start


def clock_saver(state_file: Path, attempts: int = 5):
    """Save the network clock after every cycle so a restart resumes instead of rewinding (D26).

    On Windows the replace fails while another program has the file open (a virus scanner,
    or someone reading it), so it is retried briefly; if it still fails, this cycle's save is
    skipped with a warning and the next cycle saves again. A save never stops the network."""
    state_file.parent.mkdir(parents=True, exist_ok=True)

    def save(net) -> None:
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"time": net.t.isoformat(), "cycle_seq": net.cycle_seq,
                                   "origin": net.traffic.start.isoformat()}), encoding="utf-8")
        for attempt in range(attempts):
            try:
                os.replace(tmp, state_file)
                return
            except PermissionError:
                time.sleep(0.05 * (2 ** attempt))
        log.warning("could not save the network clock to %s (file in use); will retry next cycle", state_file)

    return save


def cmd_serve(args) -> None:
    from .network import EmulatedNetwork
    from .server import Runtime, serve
    from .topology import load_topology, with_reality_gap

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    topo = with_reality_gap(load_topology(args.topology), args.reality_gap)
    state_file = Path(args.state)
    saved = json.loads(state_file.read_text(encoding="utf-8")) if args.start == "resume" and state_file.exists() else {}
    # a resumed emulator keeps the first run's traffic calendar, so growth and dated events carry on
    origin = datetime.fromisoformat(saved["origin"]) if saved.get("origin") else None
    net = EmulatedNetwork(topo, parse_start(args.start, state_file), cycle_seconds=args.cycle, seed=args.seed,
                          origin=origin)
    if saved:
        # keep numbering cycles where the last run stopped, so flow and truth cursors stay valid
        net.cycle_seq = int(saved.get("cycle_seq", 0))
    net.on_cycle.append(clock_saver(state_file))
    if args.no_faults:
        net.random_faults = False
    runtime = Runtime(net, mode=args.mode, speed=args.speed)
    server = serve(runtime, args.host, args.port, resolve_token(args.lab_token, create=True))
    logging.getLogger("netemu").info(
        "%s: %d devices, %d links, %d demands; %s mode at %sx; feed on http://%s:%d",
        topo.name, len(net.device_names), len(net.links), len(net.demands),
        runtime.mode, runtime.speed, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.go_stepped()
        server.server_close()


def cmd_lab(args) -> None:
    headers = {"X-Lab-Token": resolve_token(args.token, create=False)}
    action, extra = args.action, args.rest
    p = argparse.ArgumentParser(prog=f"netemu lab {action}")
    if action == "info":
        r = httpx.get(f"{args.url}/v1/info", timeout=10)
    else:
        if action == "surge":
            p.add_argument("--zone", default="*")
            p.add_argument("--cls", default="*")
            p.add_argument("--multiplier", type=float, required=True)
            p.add_argument("--ramp", type=float, default=10)
            p.add_argument("--hold", type=float, default=30)
            p.add_argument("--start-in", type=float, default=0)
            o = p.parse_args(extra)
            body = {"zone": o.zone, "cls": o.cls, "multiplier": o.multiplier,
                    "ramp_minutes": o.ramp, "hold_minutes": o.hold, "start_in_minutes": o.start_in}
        elif action in ("fail", "repair"):
            p.add_argument("--link", nargs=2, metavar=("A", "B"))
            p.add_argument("--device")
            p.add_argument("--minutes", type=float)
            o = p.parse_args(extra)
            body = {"link": o.link} if o.link else {"device": o.device}
            if action == "fail" and o.minutes is not None:
                body["minutes"] = o.minutes
        elif action == "mode":
            p.add_argument("mode", choices=["live", "stepped"])
            p.add_argument("--speed", type=float)
            p.add_argument("--catch-up", action="store_true")
            o = p.parse_args(extra)
            body = {"mode": o.mode, "speed": o.speed, "catch_up": o.catch_up}
        elif action == "step":
            p.add_argument("--cycles", type=int, default=1)
            body = {"cycles": p.parse_args(extra).cycles}
        elif action == "faults":
            p.add_argument("state", choices=["on", "off"])
            body = {"enabled": p.parse_args(extra).state == "on"}
        elif action == "change":
            p.add_argument("json", help="change as JSON, e.g. '{\"type\": \"capacity_change\", ...}'")
            body = json.loads(p.parse_args(extra).json)
        elif action == "reset":
            body = {}
        else:
            raise SystemExit(f"unknown lab action {action}")
        r = httpx.post(f"{args.url}/lab/{action}", json=body, headers=headers, timeout=120)
    print(json.dumps(r.json(), indent=2))
    if r.status_code >= 400:
        sys.exit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="netemu", description="Network emulator (the stand-in real network)")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the emulator and its telemetry feed")
    s.add_argument("--topology", default=str(DEFAULT_TOPOLOGY))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=9161)
    s.add_argument("--mode", choices=["live", "stepped"], default="live")
    s.add_argument("--speed", type=float, default=1.0, help="network seconds per wall-clock second")
    s.add_argument("--start", default="resume",
                   help="ISO time with zone, 'now', or 'resume' (continue the saved clock; default)")
    s.add_argument("--state", default=str(DEFAULT_STATE), help="file where the network clock is saved")
    s.add_argument("--cycle", type=int, default=60, help="seconds of network time per monitoring cycle")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--no-faults", action="store_true", help="disable random failures")
    s.add_argument("--reality-gap", choices=["off", "default", "high"], default="default",
                   help="how much the real network differs from the twin's model (evaluation E1/E4)")
    s.add_argument("--lab-token", help="default: NETEMU_LAB_TOKEN or a random token saved in var/netemu/lab_token")
    s.set_defaults(func=cmd_serve)

    lab = sub.add_parser("lab", help="control the emulator (test harness and demo)")
    lab.add_argument("action")
    lab.add_argument("rest", nargs=argparse.REMAINDER)
    lab.add_argument("--url", default=DEFAULT_URL)
    lab.add_argument("--token")
    lab.set_defaults(func=cmd_lab)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
