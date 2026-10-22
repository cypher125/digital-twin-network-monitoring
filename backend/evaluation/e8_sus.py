"""E8 Usability (NFR3): score the System Usability Scale and the task results.

Method: see docs/evaluation/E8_USABILITY_KIT.md. At least five IT or network staff without
data-science training do six tasks unaided (UC1-UC3 and trends), then answer the ten standard
SUS statements (Brooke, 1996) on a 1-5 scale. SUS score per participant: odd items contribute
(answer - 1), even items (5 - answer); the sum times 2.5 gives 0-100. Reported: mean with a 95 %
t-interval, the band (Bangor, Kortum and Miller, 2009: about 68 average, 71 good, 85 excellent),
task success rate and median time per task. Student participants are reported separately.

    python -m evaluation.e8_sus            (reads results/E8_usability/sus_responses.csv)
    python -m evaluation.e8_sus --selftest
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics

from .common import INK_2, SERIES, STATUS, Results, chart, legend

TASKS = ["t1", "t2", "t3", "t4", "t5", "t6"]
TASK_NAMES = {"t1": "T1 busiest link", "t2": "T2 link forecast", "t3": "T3 predictive alert",
              "t4": "T4 link-failure simulation", "t5": "T5 compare with now", "t6": "T6 trends and planning"}
FIELDS = (["participant_id", "role", "years_experience", "data_science_training", "is_student"]
          + [f"{t}_score" for t in TASKS] + [f"{t}_seconds" for t in TASKS] + [f"q{i}" for i in range(1, 11)]
          + ["comments"])
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23, 15: 2.13, 20: 2.09,
       30: 2.04}


def sus_score(answers: list[int]) -> float:
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        raise ValueError("SUS needs ten answers from 1 to 5")
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))   # i = 0 is item 1 (odd)
    return total * 2.5


def band(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 71:
        return "good"
    if score >= 51:
        return "ok"
    return "poor"


def interval(values: list[float]) -> tuple[float, float, float] | None:
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    df = len(values) - 1
    # nearest tabulated df at or below the real one (the larger, more cautious t)
    t = next(T95[k] for k in sorted(T95, reverse=True) if k <= df) if df <= 30 else 1.96
    half = t * sd / math.sqrt(len(values))
    return mean, mean - half, mean + half


def summarise(rows: list[dict]) -> dict:
    out: dict = {"participants": len(rows)}
    scores = [r["sus"] for r in rows]
    out["sus_scores"] = scores
    if scores:
        out["sus_mean"] = round(statistics.mean(scores), 1)
        out["sus_median"] = round(statistics.median(scores), 1)
        out["band"] = band(out["sus_mean"])
        ci = interval(scores)
        if ci:
            out["sus_mean_95ci"] = [round(ci[1], 1), round(ci[2], 1)]
    tasks = {}
    for t in TASKS:
        done = [r[f"{t}_score"] for r in rows if r.get(f"{t}_score") is not None]
        secs = [r[f"{t}_seconds"] for r in rows if r.get(f"{t}_seconds") is not None]
        tasks[t] = {"name": TASK_NAMES[t], "success_rate": round(sum(done) / len(done), 3) if done else None,
                    "median_seconds": round(statistics.median(secs), 1) if secs else None}
    out["tasks"] = tasks
    return out


def _number(value: str):
    value = (value or "").strip()
    return None if value == "" else float(value)


def load(path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if not (raw.get("participant_id") or "").strip():
                continue
            row = {k: (raw.get(k) or "").strip() for k in FIELDS}
            row["sus"] = sus_score([int(raw[f"q{i}"]) for i in range(1, 11)])
            for t in TASKS:
                row[f"{t}_score"] = _number(raw.get(f"{t}_score", ""))
                row[f"{t}_seconds"] = _number(raw.get(f"{t}_seconds", ""))
            rows.append(row)
    return rows


def _selftest() -> None:
    assert sus_score([5, 1, 5, 1, 5, 1, 5, 1, 5, 1]) == 100.0
    assert sus_score([1, 5, 1, 5, 1, 5, 1, 5, 1, 5]) == 0.0
    assert sus_score([3] * 10) == 50.0
    assert sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 2]) == 75.0
    result = interval([60, 70, 80, 75, 65])
    assert result is not None
    mean, low, high = result
    assert mean == 70 and low < 70 < high
    print("selftest passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the E8 usability test.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return
    results = Results("E8_usability", "Usability (NFR3)")
    template = results.folder / "sus_responses_TEMPLATE.csv"
    if not template.exists():
        with template.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(FIELDS)
    source = results.folder / "sus_responses.csv"
    if not source.exists():
        raise SystemExit(f"No responses yet. Copy {template.name} to {source.name} and enter one row per participant.")
    rows = load(source)
    staff = [r for r in rows if r["is_student"].lower() not in ("yes", "y", "1", "true")]
    students = [r for r in rows if r not in staff]
    results.summary = {"staff": summarise(staff), "students": summarise(students),
                       "staff_without_data_science_training": sum(
                           1 for r in staff if r["data_science_training"].lower() in ("no", "n", "0", "false")),
                       "target": "at least five IT/network staff; scores reported with their interval",
                       "enough_participants": len(staff) >= 5}
    results.write_csv("scores.csv", [{"participant_id": r["participant_id"], "role": r["role"], "student": r["is_student"],
                                      "sus": r["sus"], **{f"{t}_score": r[f"{t}_score"] for t in TASKS},
                                      **{f"{t}_seconds": r[f"{t}_seconds"] for t in TASKS}} for r in rows])

    figure, axes = chart(6.5, 2.8)
    ordered = sorted(staff, key=lambda r: r["sus"])
    axes.barh([r["participant_id"] for r in ordered], [r["sus"] for r in ordered], height=0.5, color=SERIES[0],
              label="SUS score (staff)")
    for i, r in enumerate(ordered):
        axes.text(r["sus"] + 1, i, f"{r['sus']:.1f}", va="center", fontsize=8, color=INK_2)
    axes.axvline(68, color=STATUS["warning"], linestyle=(0, (4, 3)), linewidth=1.3, label="Published average (68)")
    axes.set_xlim(0, 100)
    axes.set_xlabel("SUS score (0-100)")
    axes.grid(axis="x")
    axes.grid(axis="y", visible=False)
    legend(axes, ncol=2)
    results.save_chart(figure, "sus_scores.png")

    figure, axes = chart(6.5, 2.8)
    tasks = results.summary["staff"]["tasks"]
    names = [tasks[t]["name"] for t in TASKS][::-1]
    rates = [(tasks[t]["success_rate"] or 0) * 100 for t in TASKS][::-1]
    axes.barh(names, rates, height=0.5, color=SERIES[0], label="Task success (staff)")
    for i, rate in enumerate(rates):
        axes.text(rate + 1, i, f"{rate:.0f}%", va="center", fontsize=8, color=INK_2)
    axes.set_xlim(0, 105)
    axes.set_xlabel("Success rate (%), unaided = 1, one hint = 0.5")
    axes.grid(axis="x")
    axes.grid(axis="y", visible=False)
    results.save_chart(figure, "task_success.png")
    results.finish()
    print(results.summary)


if __name__ == "__main__":
    main()
