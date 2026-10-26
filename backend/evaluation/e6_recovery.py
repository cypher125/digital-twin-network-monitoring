"""E6 recovery, measured as new data on the dashboard again (run after evaluation.e6_soak).

The soak test counts a fault as recovered at the first "fresh" sample after it. That is when the
API answers, the engine reports "running" and the data is not stale. But at real time (1x), the
API calls data stale only after three missed cycles (three minutes). So for a while after a kill,
the last stored cycle still looks fresh, and "recovered" can come before the service is back.

This adds a stricter measure for each fault: the time from the fault to the first sample showing
a cycle newer than the newest one seen at the fault. For the ISP-B link failure, the soak's own
figures (shown down, shown up again) are kept.

    python -m evaluation.e6_recovery          (reads and updates results/E6/)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime

from .common import RESULTS


def main() -> None:
    folder = RESULTS / "E6"
    timeline = list(csv.DictReader(open(folder / "timeline.csv", encoding="utf-8", newline="")))
    faults = list(csv.DictReader(open(folder / "faults.csv", encoding="utf-8", newline="")))
    rows = []
    for fault in faults:
        if fault.get("skipped") == "True":
            continue
        at = float(fault["at_s"])
        before = [r for r in timeline if float(r["t_s"]) <= at and r.get("last_cycle")]
        newest = max((datetime.fromisoformat(r["last_cycle"]) for r in before), default=None)
        after = (r for r in timeline if float(r["t_s"]) > at and r.get("last_cycle") and r.get("fresh") == "True"
                 and (newest is None or datetime.fromisoformat(r["last_cycle"]) > newest))
        first = next(after, None)
        rows.append({"fault": fault["fault"], "at_utc": fault.get("at_utc"),
                     "soak_recovered_after_s": fault.get("recovered_after_s"),
                     "new_data_after_s": round(float(first["t_s"]) - at, 1) if first else None,
                     "newest_cycle_at_fault": newest.isoformat() if newest else None,
                     "first_new_cycle": first["last_cycle"] if first else None})
    with open(folder / "recovery.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["fault"])
        writer.writeheader()
        writer.writerows(rows)
    path = folder / "results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["summary"]["recovery_new_data"] = {
        "rule": "seconds from the fault to the first fresh sample showing a cycle newer than any seen at the fault",
        "faults": rows,
        "all_recovered": all(r["new_data_after_s"] is not None for r in rows),
        "max_new_data_after_s": max((r["new_data_after_s"] for r in rows if r["new_data_after_s"] is not None),
                                    default=None)}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for r in rows:
        print(f"{r['fault']:<42} soak: {r['soak_recovered_after_s']:>7} s   new data after: {r['new_data_after_s']} s")


if __name__ == "__main__":
    main()
