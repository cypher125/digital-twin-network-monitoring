"""E5 Responsiveness (NFR1): summary and chart of the browser measurements.

Method: frontend/scripts/e5_responsiveness.mjs signs in to the dashboard (a real browser,
Microsoft Edge, headless) with the full system running behind Caddy, and for each new
monitoring cycle records when the Digital Twin Engine received the readings (received_at,
server clock), when the API first reported the stored cycle, and when the overview page
showed that cycle's time. Browser and server run on the same laptop, so both use the same
clock. The overview polls the API once a second (D28), so up to a second of the delay is
the poll interval itself.

Target (plan section 9): every update on screen within 5 s of the data arriving (the maximum,
not a percentile). Runs at real time (1x, one cycle a minute) and at demo speed (10x).

A cycle the page did not show within 60 s is recorded as timed out and counts as a breach.
A run made during the E6 soak test can leave out the fault windows (from fault to recovery,
plus two minutes) with --exclude-faults; the samples left out are counted and reported.

    python -m evaluation.e5_report        (after one or more browser runs)
    python -m evaluation.e5_report --exclude-faults evaluation/results/E6/faults.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta

import numpy as np

from .common import INK_2, SERIES, STATUS, Results, chart, legend

LIMIT_S = 5.0
MARGIN = timedelta(minutes=2)


def fault_windows(path) -> list[tuple[datetime, datetime, str]]:
    windows = []
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("skipped") == "True" or not row.get("at_utc"):
                continue
            start = datetime.fromisoformat(row["at_utc"])
            recovered = float(row["recovered_after_s"]) if row.get("recovered_after_s") else 3600.0
            windows.append((start, start + timedelta(seconds=recovered) + MARGIN, row["fault"]))
    return windows


def in_window(sample: dict, windows) -> str | None:
    if not sample.get("received_at"):
        return None
    t = datetime.fromisoformat(sample["received_at"].replace("Z", "+00:00"))
    return next((name for start, end, name in windows if start <= t <= end), None)


def summarise(values: list[float], timed_out: int = 0) -> dict:
    data = np.array([v for v in values if v is not None], dtype=float)
    if data.size == 0:
        return {"samples": 0, "timed_out": timed_out}
    return {"samples": int(data.size) + timed_out, "timed_out": timed_out,
            "max_s": None if timed_out else round(float(data.max()), 3),
            "max_shown_s": round(float(data.max()), 3), "p50_s": round(float(np.median(data)), 3),
            "p95_s": round(float(np.percentile(data, 95)), 3), "mean_s": round(float(data.mean()), 3),
            "share_within_5s": round(float((data <= LIMIT_S).sum() / (data.size + timed_out)), 4)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise the E5 browser measurements.")
    parser.add_argument("--exclude-faults", default=None, help="E6 faults.csv: leave out samples in fault windows")
    args = parser.parse_args()
    windows = fault_windows(args.exclude_faults) if args.exclude_faults else []
    results = Results("E5", "Responsiveness (NFR1)",
                      config={"exclude_fault_windows_from": args.exclude_faults, "fault_margin_s": MARGIN.seconds})
    runs = sorted(results.folder.glob("*.samples.json"))
    if not runs:
        raise SystemExit("no measurements yet: run frontend/scripts/e5_responsiveness.mjs first")
    rows, by_run = [], {}
    for path in runs:
        run = json.loads(path.read_text(encoding="utf-8"))
        label = run["label"]
        kept, left_out = [], {}
        for sample in run["samples"]:
            fault = in_window(sample, windows)
            if fault:
                left_out[fault] = left_out.get(fault, 0) + 1
                continue
            kept.append(sample)
            rows.append({"run": label, "speed": run.get("speed"), **sample})
        timed_out = sum(1 for s in kept if s.get("timed_out"))
        by_run[label] = {
            "speed": run.get("speed"), "url": run.get("url"), "measured": run.get("when"),
            "received_to_screen": summarise([s.get("received_to_screen_s") for s in kept], timed_out),
            "received_to_api": summarise([s.get("received_to_api_s") for s in kept]),
            "api_to_screen": summarise([s.get("api_to_screen_s") for s in kept]),
            "left_out_in_fault_windows": left_out,
        }
    results.write_csv("samples.csv", rows, ["run", "speed", "cycle", "received_at", "received_to_screen_s",
                                            "received_to_api_s", "api_to_screen_s", "timed_out", "mode"])
    any_timeout = any(r["received_to_screen"].get("timed_out") for r in by_run.values())
    worst = max((r["received_to_screen"].get("max_shown_s", 0) for r in by_run.values()), default=None)
    met = worst is not None and worst <= LIMIT_S and not any_timeout
    results.summary = {"runs": by_run, "worst_received_to_screen_s": worst, "any_timed_out": any_timeout,
                       "target": "maximum within 5 s", "target_met": met,
                       "target_nfr1": {"rule": "every new cycle on screen within 5 s of the data arriving (maximum)",
                                       "met": met}}

    figure, axes = chart(7.0, 3.0)
    for index, (label, run) in enumerate(sorted(by_run.items())):
        values = [r["received_to_screen_s"] for r in rows if r["run"] == label and r["received_to_screen_s"] is not None]
        jitter = np.random.default_rng(index).uniform(-0.12, 0.12, len(values))
        axes.scatter(values, np.full(len(values), index) + jitter, s=22, color=SERIES[index % 3],
                     edgecolors="white", linewidths=1.2, zorder=3, label=f"{label} (speed {run['speed']}x)")
    axes.axvline(LIMIT_S, color=STATUS["critical"], linestyle=(0, (4, 3)), linewidth=1.3, label="NFR1 limit 5 s")
    axes.set_yticks(range(len(by_run)), [f"{k}" for k in sorted(by_run)], color=INK_2)
    axes.set_xlabel("Seconds from readings received to shown on the overview")
    axes.set_xlim(0, max(LIMIT_S + 0.5, (worst or 0) + 0.5))
    axes.grid(axis="x")
    axes.grid(axis="y", visible=False)
    legend(axes, ncol=3)
    results.save_chart(figure, "latency.png")
    print(json.dumps(results.summary, indent=2))
    results.finish()


if __name__ == "__main__":
    main()
