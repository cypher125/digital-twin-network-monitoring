"""E6 addendum: a database outage, injected on its own (NFR2).

The 8-hour soak test (evaluation.e6_soak) was meant to include a 90-second database outage. It
did not happen: `deploy/localpg.py stop` called pgserver's cleanup(), which does nothing for a
server meant to outlive the script, so the database never went down. The data shows it: during
the "outage" the dashboard got a new cycle every minute. localpg.py now stops the server with
pg_ctl. This test injects the outage again, against the system as deployed.

Method. With the system running, the API's live state is sampled every 5 s, through Caddy as the
dashboard does: 2 minutes before, during a 90-second stop of the local PostgreSQL, and until
new data reaches the dashboard again (at most 10 minutes). Recovery is the time from the
database coming back to the first fresh sample with a cycle newer than any seen before the
outage. Target (NFR2): recovers with no manual step.

    set DT_SENIOR=senior1:password
    python -m evaluation.e6_database_outage
"""
from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime

from .common import ROOT, Results
from .system import Dashboard

LOCALPG = [str(ROOT / "var" / "localpg" / "pgenv" / "Scripts" / "python.exe"), str(ROOT / "deploy" / "localpg.py")]


def main() -> None:
    results = Results("E6_database", "Database outage (NFR2), injected on its own",
                      config={"outage_seconds": 90, "sample_seconds": 5, "url": "https://localhost"})
    dashboard = Dashboard("https://localhost")
    dashboard.sign_in()
    began = time.monotonic()
    timeline = []

    def sample(phase: str) -> dict | None:
        try:
            live = dashboard.get("live")
        except Exception as error:  # noqa: BLE001 - the API may fail while the database is down
            live, note = None, f"{type(error).__name__}"
        else:
            note = ""
        timeline.append({"t_s": round(time.monotonic() - began, 1), "utc": datetime.now(UTC).isoformat(timespec="seconds"),
                         "phase": phase, "api_ok": live is not None,
                         "fresh": bool(live) and live.get("engine_state") == "running" and not live.get("stale"),
                         "engine_state": (live or {}).get("engine_state"), "last_cycle": (live or {}).get("last_cycle"),
                         "note": note})
        return live

    for _ in range(24):                                   # 2 minutes before
        sample("before")
        time.sleep(5)
    newest = max(r["last_cycle"] for r in timeline if r["last_cycle"])
    stop = subprocess.run([*LOCALPG, "stop"], capture_output=True, text=True, check=False)
    stopped_at = time.monotonic() - began
    while time.monotonic() - began < stopped_at + 90:
        sample("outage")
        time.sleep(5)
    start = subprocess.run([*LOCALPG, "start"], capture_output=True, text=True, check=False)
    back_at = time.monotonic() - began
    recovered_at = None
    while time.monotonic() - began < back_at + 600:
        live = sample("after")
        if live and timeline[-1]["fresh"] and live.get("last_cycle") and live["last_cycle"] > newest:
            recovered_at = time.monotonic() - began
            break
        time.sleep(5)
    results.write_csv("timeline.csv", timeline)
    outage = [r for r in timeline if r["phase"] == "outage"]
    results.summary = {
        "database_stop": {"returncode": stop.returncode, "output": (stop.stdout or stop.stderr).strip()[-200:]},
        "database_start": {"returncode": start.returncode, "output": (start.stdout or start.stderr).strip()[-200:]},
        "outage_samples": len(outage), "outage_samples_api_failed": sum(not r["api_ok"] for r in outage),
        "outage_engine_states": sorted({str(r["engine_state"]) for r in outage}),
        "newest_cycle_before": newest, "recovered": recovered_at is not None,
        "new_data_after_database_back_s": round(recovered_at - back_at, 1) if recovered_at else None,
        "new_data_after_outage_start_s": round(recovered_at - stopped_at, 1) if recovered_at else None,
        "target": "recovers with no manual step", "target_met": recovered_at is not None,
    }
    results.finish()
    print(results.summary)


if __name__ == "__main__":
    main()
