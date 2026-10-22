"""E6 Reliability soak test (NFR2: the system keeps running and recovers without manual steps).

Method. The whole system runs as deployed (deploy/start.ps1: supervisor, emulator, API on
Waitress, Digital Twin Engine, Caddy on https://localhost) for several hours while faults are
injected on a fixed schedule (scaled to the run length):

    10 %  the engine's process tree is killed
    25 %  the API's process tree is killed
    40 %  the emulator's process tree is killed (the twin must resume with no time going back)
    55 %  a "real" failure: the ISP-B internet link fails in the emulator for 20 network minutes;
          the twin must show it down within one cycle (event path) and up again after repair
    70 %  database outage, 90 s (only when the database is the local PostgreSQL; on Neon this
          step is skipped and reported)
    85 %  Caddy's process tree is killed

Every 10 s the script asks the API (through Caddy, as the dashboard does) for the live state.
A sample is "fresh" when the API answers, the engine is running and the data is not stale
(the API's own rule: a cycle stored within three cycle periods). Every minute it records each
service's memory and CPU (psutil, whole process trees) and the engine's counters.

Measures: availability (share of fresh samples, overall and outside the fault windows), the
recovery time of every fault (fault -> first fresh sample again), missed cycles reported by the
engine, link-failure detection delay, and memory growth per hour per service (a leak check).
Target (plan): recovers with no manual steps.

    set DT_SENIOR=senior1:password
    python -m evaluation.e6_soak --hours 6          (system started with deploy/start.ps1 first)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime

import numpy as np

from .common import INK_2, ROOT, SERIES, Results, chart, legend
from .system import Dashboard, ResourceSampler, kill_tree, lab, service_pids, supervisor_state

LINK = ("ISP-B-GW", "EDGE-RTR-01")
LINK_LABEL = "ISP-B-GW <-> EDGE-RTR-01"
LOCALPG = [str(ROOT / "var" / "localpg" / "pgenv" / "Scripts" / "python.exe"), str(ROOT / "deploy" / "localpg.py")]


def link_status(dashboard: Dashboard) -> str | None:
    topology = dashboard.get("topology")
    if not topology:
        return None
    for link in topology["links"]:
        if link["label"] == LINK_LABEL:
            return link["status"]
    return None


def database_is_local() -> bool:
    """The supervisor names the database it was started with (deploy/supervisor.py describe_database)."""
    label = str((supervisor_state() or {}).get("database", ""))
    return "local" in label or "127.0.0.1" in label


def main() -> None:
    parser = argparse.ArgumentParser(description="Soak test with injected faults (NFR2).")
    parser.add_argument("--hours", type=float, default=6.0)
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--sample-seconds", type=float, default=10.0)
    parser.add_argument("--quick", action="store_true", help="15 minutes, for a dry run")
    args = parser.parse_args()
    hours = 0.25 if args.quick else args.hours
    if not service_pids():
        sys.exit("The system is not running: start it with deploy/start.ps1 first.")

    results = Results("E6", "Reliability soak test (NFR2)",
                      config={"hours": hours, "url": args.url, "sample_seconds": args.sample_seconds,
                              "quick": args.quick, "faults_at_share_of_run": [0.10, 0.25, 0.40, 0.55, 0.70, 0.85]})
    dashboard = Dashboard(args.url)
    dashboard.sign_in()
    sampler = ResourceSampler()
    local_db = database_is_local()
    duration = hours * 3600
    began = time.monotonic()
    started_at = datetime.now().isoformat(timespec="seconds")

    def elapsed() -> float:
        return time.monotonic() - began

    faults = [
        {"at": 0.10, "name": "engine killed", "do": lambda: kill_tree(service_pids()["engine"])},
        {"at": 0.25, "name": "API killed", "do": lambda: kill_tree(service_pids()["api"])},
        {"at": 0.40, "name": "emulator killed", "do": lambda: kill_tree(service_pids()["emulator"])},
        {"at": 0.55, "name": "ISP-B link failure (20 network minutes)",
         "do": lambda: lab("/lab/fail", {"link": list(LINK), "minutes": 20})},
        {"at": 0.70, "name": "database outage (90 s)", "do": None},
        {"at": 0.85, "name": "Caddy killed", "do": lambda: kill_tree(service_pids()["caddy"])},
    ]
    timeline, resources, fault_rows = [], [], []
    pending = list(faults)
    active: dict | None = None
    next_resources = 0.0
    link_down_seen: float | None = None
    database_back_at: float | None = None

    print(f"soak test for {hours:g} h against {args.url}; local database: {local_db}")
    while elapsed() < duration:
        now = elapsed()
        if pending and now >= pending[0]["at"] * duration:
            fault = pending.pop(0)
            row = {"fault": fault["name"], "at_s": round(now, 1), "skipped": False}
            if fault["name"].startswith("database"):
                if local_db:
                    subprocess.run([*LOCALPG, "stop"], capture_output=True, check=False)
                    database_back_at = now + 90          # sampling carries on during the outage
                else:
                    row["skipped"] = True
                    row["note"] = "database is Neon: an outage cannot be injected from here"
            else:
                try:
                    fault["do"]()
                except Exception as error:  # report, do not stop the soak test
                    row["error"] = str(error)
            print(f"{now / 60:6.1f} min  fault: {fault['name']}{' (skipped)' if row['skipped'] else ''}")
            fault_rows.append(row)
            active = None if row["skipped"] else row
            link_down_seen = None

        if database_back_at is not None and now >= database_back_at:
            subprocess.run([*LOCALPG, "start"], capture_output=True, check=False)
            database_back_at = None
            if active is not None:
                active["outage_ended_s"] = round(now, 1)
        live = dashboard.get("live")
        fresh = bool(live) and live.get("engine_state") == "running" and not live.get("stale")
        timeline.append({"t_s": round(now, 1), "api_ok": live is not None, "fresh": fresh,
                         "engine_state": (live or {}).get("engine_state"), "last_cycle": (live or {}).get("last_cycle")})
        if active is not None:
            if active["fault"].startswith("ISP-B"):
                status = link_status(dashboard)
                if status == "down" and link_down_seen is None:
                    link_down_seen = now
                    active["twin_shows_down_after_s"] = round(now - active["at_s"], 1)
                if link_down_seen is not None and status == "up" and fresh:
                    active["twin_shows_up_again_after_s"] = round(now - active["at_s"], 1)
                    active["recovered_after_s"] = active["twin_shows_up_again_after_s"]
                    active = None
            elif fresh and now - active["at_s"] > 5 and database_back_at is None:
                active["recovered_after_s"] = round(now - active["at_s"], 1)
                active = None
        if now >= next_resources:
            usage = sampler.sample()
            status = dashboard.get("system/status") or {}
            engine = status.get("engine") or {}
            for name, info in usage.items():
                resources.append({"t_s": round(now, 1), "service": name, **info,
                                  "cycles_stored": engine.get("cycles_stored"), "cycles_missed": engine.get("cycles_missed")})
            next_resources = now + 60
        time.sleep(max(0.0, args.sample_seconds - (elapsed() - now)))

    # ---------------------------------------------------------------- summary
    fresh_flags = np.array([r["fresh"] for r in timeline], dtype=bool)
    times = np.array([r["t_s"] for r in timeline])
    in_fault = np.zeros(len(times), dtype=bool)
    for row in fault_rows:
        if row.get("skipped"):
            continue
        end = row["at_s"] + row.get("recovered_after_s", duration)
        in_fault |= (times >= row["at_s"]) & (times <= end)
    growth = {}
    for name in sorted({r["service"] for r in resources}):
        points = [(r["t_s"], r["rss_mb"]) for r in resources if r["service"] == name]
        if len(points) >= 3:
            x = np.array([p[0] for p in points]) / 3600
            y = np.array([p[1] for p in points])
            growth[name] = {"rss_start_mb": round(float(y[0]), 1), "rss_end_mb": round(float(y[-1]), 1),
                            "rss_max_mb": round(float(y.max()), 1),
                            "growth_mb_per_hour": round(float(np.polyfit(x, y, 1)[0]), 2)}
    missed = [r["cycles_missed"] for r in resources if r["service"] == "engine" and r["cycles_missed"] is not None]
    recovered = [r for r in fault_rows if not r.get("skipped")]
    results.write_csv("timeline.csv", timeline, ["t_s", "api_ok", "fresh", "engine_state", "last_cycle"])
    results.write_csv("resources.csv", resources, ["t_s", "service", "pid", "rss_mb", "cpu_pct", "processes",
                                                   "cycles_stored", "cycles_missed"])
    results.write_csv("faults.csv", fault_rows, ["fault", "at_s", "skipped", "recovered_after_s", "twin_shows_down_after_s",
                                                 "twin_shows_up_again_after_s", "outage_ended_s", "note", "error"])
    all_recovered = all("recovered_after_s" in r for r in recovered)
    results.summary = {
        "started": started_at, "hours": hours, "samples": len(timeline),
        "availability_pct": round(100 * float(fresh_flags.mean()), 2) if len(fresh_flags) else None,
        "availability_outside_faults_pct": round(100 * float(fresh_flags[~in_fault].mean()), 2) if (~in_fault).any() else None,
        "faults": fault_rows, "all_faults_recovered_without_manual_steps": all_recovered,
        "max_recovery_s": max((r.get("recovered_after_s", 0) for r in recovered), default=None),
        "engine_cycles_missed_reported": missed[-1] if missed else None,
        "memory": growth, "local_database": local_db,
        "target": "recovers with no manual steps", "target_met": all_recovered,
    }

    # data freshness over the run, with the faults marked
    figure, axes = chart(8.0, 2.8)
    hours_axis = times / 3600
    axes.fill_between(hours_axis, 0, fresh_flags.astype(float), step="post", color=SERIES[0], alpha=0.25, linewidth=0)
    axes.step(hours_axis, fresh_flags.astype(float), where="post", color=SERIES[0], linewidth=1.5, label="Fresh data on the dashboard")
    for row in fault_rows:
        axes.axvline(row["at_s"] / 3600, color=INK_2, linewidth=0.8)
        axes.text(row["at_s"] / 3600, 1.05, row["fault"].split(" (")[0], rotation=30, fontsize=7, color=INK_2,
                  ha="left", va="bottom")
    axes.set_yticks([0, 1], ["no", "yes"])
    axes.set_ylim(-0.05, 1.6)
    axes.set_xlabel("Hours since the start of the soak test")
    results.save_chart(figure, "freshness.png")

    figure, axes = chart(8.0, 3.0)
    for index, name in enumerate(["engine", "api", "emulator"]):
        points = [(r["t_s"] / 3600, r["rss_mb"]) for r in resources if r["service"] == name]
        if points:
            axes.plot([p[0] for p in points], [p[1] for p in points], color=SERIES[index], label=name)
    axes.set_xlabel("Hours since the start of the soak test")
    axes.set_ylabel("Resident memory (MB)")
    axes.set_ylim(bottom=0)
    legend(axes, ncol=3)
    results.save_chart(figure, "memory.png")
    results.finish()
    print(results.summary)


if __name__ == "__main__":
    main()
