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

    python -m evaluation.e5_report        (after one or more browser runs)
"""
from __future__ import annotations

import json

import numpy as np

from .common import INK_2, SERIES, STATUS, Results, chart, legend

LIMIT_S = 5.0


def summarise(values: list[float]) -> dict:
    data = np.array([v for v in values if v is not None], dtype=float)
    if data.size == 0:
        return {"samples": 0}
    return {"samples": int(data.size), "max_s": round(float(data.max()), 3), "p50_s": round(float(np.median(data)), 3),
            "p95_s": round(float(np.percentile(data, 95)), 3), "mean_s": round(float(data.mean()), 3),
            "share_within_5s": round(float((data <= LIMIT_S).mean()), 4)}


def main() -> None:
    results = Results("E5", "Responsiveness (NFR1)")
    runs = sorted(results.folder.glob("*.samples.json"))
    if not runs:
        raise SystemExit("no measurements yet: run frontend/scripts/e5_responsiveness.mjs first")
    rows, by_run = [], {}
    for path in runs:
        run = json.loads(path.read_text(encoding="utf-8"))
        label = run["label"]
        for sample in run["samples"]:
            rows.append({"run": label, "speed": run.get("speed"), **sample})
        by_run[label] = {
            "speed": run.get("speed"), "url": run.get("url"), "measured": run.get("when"),
            "received_to_screen": summarise([s["received_to_screen_s"] for s in run["samples"]]),
            "received_to_api": summarise([s["received_to_api_s"] for s in run["samples"]]),
            "api_to_screen": summarise([s["api_to_screen_s"] for s in run["samples"]]),
        }
    results.write_csv("samples.csv", rows, ["run", "speed", "cycle", "received_at", "received_to_screen_s",
                                            "received_to_api_s", "api_to_screen_s", "mode"])
    worst = max((r["received_to_screen"].get("max_s", 0) for r in by_run.values()), default=None)
    results.summary = {"runs": by_run, "worst_received_to_screen_s": worst,
                       "target": "maximum within 5 s", "target_met": worst is not None and worst <= LIMIT_S}

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
