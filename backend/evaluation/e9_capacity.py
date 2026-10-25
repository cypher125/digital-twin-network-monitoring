"""E9 Long-term trend analysis and capacity planning (Chapter 3 weakness 3, plan section 11).

Question: does the Trends page's capacity planning recover the growth that is really in the
traffic? Its two figures are each link's growth per week and the projected date the link reaches
the critical threshold (90 %).

The method under test is exactly the page's. apps/api/views/trends.py (CapacityView) takes, for
each link, the 95th percentile of its one-minute utilisation per complete West Africa Time day
(daily_p95_by_link, percentile_cont). It then calls project(), which fits a least-squares line
over the last 14 days and reports:
- growth_pct_per_week = slope x 7 / mean of the daily values x 100;
- days_until_critical, counted from today.
The fit gives the weekly pattern its own levels: one per day of the week with 9 days or more,
one for Saturdays and Sundays with 5-8 days (apps.api.views.trends.trend_design).

E9's first quick run found that the page's original plain line was pulled by where the quieter
weekends fall in the window:
- a 7-day window ending on a Sunday showed -39 % a week on a campus configured to grow by 1 %;
- over 14 days the bias is about a third of the weekend dip per week, and it changes sign with
  the day of the week.
A single weekend level was not enough either (a busy hostel Saturday, a quiet Sunday). The page
was changed to day-of-week levels (with a test) before the runs reported here.
E9 calls project() itself and computes the daily 95th percentiles the same way (numpy's "linear"
percentile is percentile_cont's interpolation).

Part A: configured growth (the target)
    The world.
    - Five fresh emulated campuses (data/topologies/campus.yaml, seeds 9101-9105; the training
      history used 7), each run for 14 days of network time from Monday 2 November 2026 00:00 WAT.
    - The traffic calendar began 28 days earlier (the emulator's `origin`), so the one-off events
      of the first days of a semester (the registration rush on days 2-3 and the software-update
      day 11) are already over. The configured growth (growth_per_week 1 %, compounding from the
      origin) runs on without a break.
    - Random link and device failures and the daily random flash crowds stay on, as on a normal
      campus.
    - The page reads the twin's stored readings. Here they are the emulator's ground truth, which
      the twin reproduces to within 0.2 points (E1). A link's down minutes are left out, as the
      stored readings of a down link are empty.
    What is compared.
    - For every busy link, meaning a mean daily 95th percentile of 10 % or more, so the
      percentage is not just noise on an idle link: the page's growth_pct_per_week over the 14
      days, and the 95 % interval of the same least-squares fit. That interval is the slope's
      t-interval with n - p degrees of freedom (p columns of the fit), scaled exactly like the page's
      figure. The page
      itself shows no interval.
    - The configured growth is 1 % a week of the demand. Below saturation, a link's utilisation
      is proportional to its demand, so it grows by the same share.
    Target (plan): the configured growth lies inside the interval. The interval is that of the
    mean of the page's growth figure over the busy links, one value per world: a t-interval over
    the five worlds, which are independent. Also reported: the share of busy links whose own
    interval contains 1 %, and the estimate per link and per world.

Part B: ramped links, the projected date of reaching 90 %
    One more world (seed 9201), run for 28 days, in which two zone/class demands are ramped
    linearly from the first day:
    - hostel web traffic (an evening load);
    - School of Science video (a daytime load).
    Each ramp is a lab surge with a 28-day ramp. It is sized before the run, from a one-day fork
    of the world with that demand multiplied, by bisection on the multiplier, so that the zone's
    busiest link reaches a daily 95th percentile of 90 % around day 20. Its links then cross 90 %
    some days after the page's 14-day window.
    - The ramped links are those whose daily 95th percentile rises by 10 points or more from the
      first day to the last; growth alone adds under 4 points.
    - For each ramped link still below 90 % in the window, the page's projection on day 14, from
      days 0-13, gives the projected crossing day: today + floor(days_until_critical + 0.5), as
      the page rounds it.
    - This is compared with the actual crossing: the first day from day 14 on whose daily 95th
      percentile is 90 % or more.
    - Reported per link: the error in days, and links that never cross by day 27 or were not
      projected to.

Part C: the stored history (what the dashboard shows now)
    The same page computation on the local database's last 14 complete days of stored history,
    per link, with the interval. It is reported, not used for the target, for two reasons:
    - The stored history was generated in two emulator runs, and until 25 October 2026 a resumed
      emulator restarted its traffic calendar. That bug is fixed in netemu by the `origin` in the
      saved clock. So its growth clock reset part-way through, and its one-off events happened
      twice.
    - Its growth is therefore not a clean 1 % a week.

Quick mode (--quick): one 7-day growth world, and a 14-day ramp world with the window shortened
to days 0-6 (the same rules). This is a pipeline check, not for Chapter 4.

Run time on the 2-core Celeron laptop: about 20 s per day of network time, so about 25 minutes
for a full run (five 14-day worlds, one 28-day world, the sizing forks), plus Part C's queries.

Limitations
    * The traffic is the emulator's smooth model with compounding growth, and the ramps are
      linear. Real growth is lumpier: a new course or a streaming habit arrives in steps. The
      page's straight line suits these cases better than it would suit many real ones.
    * Two weeks of daily values hold two weekends. The weekly pattern (weekends are quieter) and
      one-off failures widen the intervals, and the per-link intervals assume independent days.
      That is why the target uses the interval across independent worlds.

    python -m evaluation.e9_capacity [--quick] [--no-database]
"""
from __future__ import annotations

import argparse
import copy
import math
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import numpy as np

from netemu.network import EmulatedNetwork
from netemu.topology import Topology, load_topology

from .common import INK_2, MUTED, ROOT, SERIES, Results, chart, legend, threshold_lines

CAMPUS = ROOT / "data" / "topologies" / "campus.yaml"
WAT = timezone(timedelta(hours=1), "WAT")
START = datetime(2026, 11, 2, 0, 0, tzinfo=WAT)        # a Monday, after the training window
ORIGIN_DAYS_BEFORE = 28                                 # the semester's traffic calendar began 4 weeks earlier
CYCLES_PER_DAY = 1440
CRITICAL_PCT = 90.0
BUSY_P95_PCT = 10.0
WINDOW_DAYS = 14                                        # the page fits the last 14 complete days
GROWTH_SEEDS = (9101, 9102, 9103, 9104, 9105)
RAMP_SEED = 9201
RAMP_WORLD_DAYS = 28
RAMPS = (("HOSTEL", "web"), ("SCI", "video"))
CROSS_DAY = 20                                          # the ramps are sized to reach 90 % around this day
RAMPED_RISE_PTS = 10.0


# ------------------------------------------------------------------ the page's method
def page_project(p95: np.ndarray, today_index: int, first_day: date) -> dict:
    """The page's projection (apps.api.views.trends.project) for one link's daily values."""
    from apps.api.views.trends import project

    days = [first_day + timedelta(days=i) for i in range(len(p95)) if not np.isnan(p95[i])]
    values = [float(v) for v in p95 if not np.isnan(v)]
    return project(days, values, CRITICAL_PCT, today=first_day + timedelta(days=today_index))


def growth_interval(p95: np.ndarray, first_day: date, level: float = 0.975) -> tuple[float, float, float] | None:
    """The page's growth figure (% of the daily values' mean per week) with the 95 % t-interval of the
    slope of the same least-squares fit (the page's design: day number and the weekly levels)."""
    from scipy import stats

    from apps.api.views.trends import trend_design

    keep = ~np.isnan(p95)
    days = [first_day + timedelta(days=int(i)) for i in np.nonzero(keep)[0]]
    y = p95[keep]
    if len(y) < 5:
        return None
    design = trend_design(days)
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    dof = len(y) - design.shape[1]
    residuals = y - design @ coef
    cov = float(residuals @ residuals) / dof * np.linalg.inv(design.T @ design)
    se = math.sqrt(float(cov[1, 1]))
    t = float(stats.t.ppf(level, dof))
    scale = 7 / max(float(y.mean()), 1e-6) * 100
    slope = float(coef[1])
    return slope * scale, (slope - t * se) * scale, (slope + t * se) * scale


def t_interval(values: list[float], level: float = 0.975) -> tuple[float, float, float] | None:
    from scipy import stats

    if len(values) < 2:
        return None
    mean, sd = float(np.mean(values)), float(np.std(values, ddof=1))
    half = float(stats.t.ppf(level, len(values) - 1)) * sd / math.sqrt(len(values))
    return mean, mean - half, mean + half


# ------------------------------------------------------------------ worlds
def world_topology(seed: int) -> Topology:
    topo = load_topology(CAMPUS)
    return replace(topo, random_surges=replace(topo.random_surges, seed=seed + 1000))


def new_world(topo: Topology, seed: int) -> EmulatedNetwork:
    return EmulatedNetwork(topo, START, seed=seed, history_cycles=2,
                           origin=START - timedelta(days=ORIGIN_DAYS_BEFORE))


def run_days(net: EmulatedNetwork, days: int, label: str = "") -> np.ndarray:
    """Daily 95th percentiles (days, links) of the one-minute ground-truth utilisation, down minutes left out."""
    out = np.full((days, len(net.links)), np.nan)
    for d in range(days):
        day = np.full((CYCLES_PER_DAY, len(net.links)), np.nan)
        for k in range(CYCLES_PER_DAY):
            for _ in range(net.steps_per_cycle()):
                net.step()
            for i, link in enumerate(net.truth[-1]["links"]):
                if link["up"]:
                    day[k, i] = link["utilisation_pct"]
        with np.errstate(all="ignore"):
            out[d] = np.nanpercentile(day, 95, axis=0, method="linear")
        if label and (d + 1) % 7 == 0:
            print(f"  {label}: day {d + 1}/{days}", flush=True)
    return out


def size_ramp(topo: Topology, seed: int, zone: str, cls: str) -> dict:
    """The multiplier m90 at which the zone's busiest link has a day-0 daily p95 of 90 % (bisection on
    one-day forks), and the 28-day ramp's final multiplier that reaches m90 around CROSS_DAY."""
    base = new_world(topo, seed)
    lo, hi, tries = 1.0, 8.0, []
    for _ in range(7):
        mid = (lo + hi) / 2
        fork = copy.deepcopy(base)
        fork.add_surge(zone, cls, mid, 1, CYCLES_PER_DAY * 2, 0.0)
        peak = float(np.nanmax(run_days(fork, 1)[0]))
        tries.append((round(mid, 3), round(peak, 2)))
        lo, hi = (lo, mid) if peak >= CRITICAL_PCT else (mid, hi)
    m90 = (lo + hi) / 2
    final = 1.0 + (m90 - 1.0) * RAMP_WORLD_DAYS / CROSS_DAY
    return {"zone": zone, "cls": cls, "m90": round(m90, 3), "final_multiplier": round(final, 3), "bisection": tries}


# ------------------------------------------------------------------ parts
def part_a(results: Results, seeds: tuple[int, ...], days: int, labels: list[str]) -> dict:
    rows, world_means = [], []
    for seed in seeds:
        net = new_world(world_topology(seed), seed)
        p95 = run_days(net, days, f"growth world {seed}")
        estimates = []
        for i in range(p95.shape[1]):
            series = p95[:, i]
            if np.nanmean(series) < BUSY_P95_PCT:
                continue
            page = page_project(series, days, START.date())
            interval = growth_interval(series, START.date())
            if interval is None:
                continue
            estimates.append(page["growth_pct_per_week"])
            rows.append({"seed": seed, "link_id": i + 1, "link": labels[i], "mean_daily_p95_pct": float(np.nanmean(series)),
                         "page_growth_pct_per_week": page["growth_pct_per_week"],
                         "interval_low": interval[1], "interval_high": interval[2],
                         "configured_inside": interval[1] <= configured_growth() <= interval[2],
                         "page_days_until_critical": page["days_until_critical"],
                         **{f"day{d}_p95": series[d] for d in range(days)}})
        world_means.append(float(np.mean(estimates)) if estimates else float("nan"))
        print(f"  world {seed}: {len(estimates)} busy links, mean page growth {world_means[-1]:.2f} %/week", flush=True)
    results.write_csv("growth_by_link.csv", rows)
    pooled = t_interval([m for m in world_means if not math.isnan(m)])
    inside = [r["configured_inside"] for r in rows]
    return {"worlds": len(seeds), "days": days, "busy_links_per_world": len(rows) / max(1, len(seeds)),
            "world_mean_growth_pct_per_week": [round(m, 3) for m in world_means],
            "mean_growth_pct_per_week": round(pooled[0], 3) if pooled else round(world_means[0], 3),
            "interval_95": [round(pooled[1], 3), round(pooled[2], 3)] if pooled else None,
            "per_link_median_growth_pct_per_week": round(float(np.median([r["page_growth_pct_per_week"] for r in rows])), 3)
            if rows else None,
            "share_of_links_whose_interval_contains_configured": round(float(np.mean(inside)), 3) if inside else None,
            "rows": rows}


def part_b(results: Results, days: int, window: int, labels: list[str]) -> dict:
    topo = world_topology(RAMP_SEED)
    sizing = [size_ramp(topo, RAMP_SEED, zone, cls) for zone, cls in RAMPS]
    for s in sizing:
        print(f"  ramp {s['zone']}/{s['cls']}: 90 % at x{s['m90']} on day 0; ramp to x{s['final_multiplier']} over "
              f"{RAMP_WORLD_DAYS} days", flush=True)
    net = new_world(topo, RAMP_SEED)
    for s in sizing:
        net.add_surge(s["zone"], s["cls"], s["final_multiplier"], RAMP_WORLD_DAYS * CYCLES_PER_DAY,
                      CYCLES_PER_DAY * 30, 0.0)
    p95 = run_days(net, days, "ramp world")
    rows = []
    for i in range(p95.shape[1]):
        series = p95[:, i]
        if np.nanmax(series) - series[0] < RAMPED_RISE_PTS:
            continue
        fit = series[:window]
        page = page_project(fit, window, START.date())
        if np.nanmax(fit) >= CRITICAL_PCT:
            status, predicted, actual = "at 90 % already in the window", None, None
        else:
            ahead = page["days_until_critical"]
            predicted = None if ahead is None else window + math.floor(ahead + 0.5)
            later = [d for d in range(window, days) if series[d] >= CRITICAL_PCT]
            actual = later[0] if later else None
            status = ("scored" if predicted is not None and actual is not None
                      else "never crossed by the last day" if actual is None else "not projected to cross")
        rows.append({"link_id": i + 1, "link": labels[i], "status": status,
                     "page_growth_pct_per_week": page["growth_pct_per_week"],
                     "page_days_until_critical": page["days_until_critical"],
                     "projected_crossing_day": predicted, "actual_crossing_day": actual,
                     "error_days": predicted - actual if predicted is not None and actual is not None else None,
                     **{f"day{d}_p95": series[d] for d in range(days)}})
    results.write_csv("ramped_links.csv", rows)
    scored = [r for r in rows if r["status"] == "scored"]
    errors = [r["error_days"] for r in scored]
    return {"sizing": sizing, "days": days, "window_days": window, "ramped_links": len(rows),
            "scored_links": len(scored),
            "error_days_median": float(np.median(errors)) if errors else None,
            "abs_error_days_median": float(np.median(np.abs(errors))) if errors else None,
            "within_2_days": sum(abs(e) <= 2 for e in errors), "statuses": {s: sum(r["status"] == s for r in rows)
                                                                         for s in {r["status"] for r in rows}},
            "rows": rows, "p95": p95}


def setup_django() -> None:
    """The page's code (apps.api.views.trends) needs Django's settings, also for parts A and B."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()


def part_c() -> dict:
    """The page's computation on the stored history (local database, read-only)."""
    from apps.api.services import latest_cycle
    from apps.api.views.alerts import link_labels
    from apps.api.views.trends import daily_p95_by_link, project

    end = latest_cycle()
    if end is None:
        return {"available": False}
    now = end.astimezone(WAT)
    today = datetime(now.year, now.month, now.day, tzinfo=WAT)
    labels = link_labels()
    rows = []
    for link_id, (days, p95) in sorted(daily_p95_by_link(today).items()):
        page = project(days, p95, CRITICAL_PCT, today=now.date())
        series = np.full((days[-1] - days[0]).days + 1, np.nan)
        for d, v in zip(days, p95, strict=True):
            series[(d - days[0]).days] = v
        interval = growth_interval(series, days[0])
        rows.append({"link_id": link_id, "link": labels.get(link_id, str(link_id)), "days_of_data": len(days),
                     "first_day": days[0].isoformat(), "last_day": days[-1].isoformat(),
                     "mean_daily_p95_pct": float(np.mean(p95)), **page,
                     "interval_low": interval[1] if interval else None, "interval_high": interval[2] if interval else None})
    busy = [r for r in rows if r["mean_daily_p95_pct"] >= BUSY_P95_PCT and r["growth_pct_per_week"] is not None]
    return {"available": True, "latest_cycle": end.isoformat(), "links": len(rows), "busy_links": len(busy),
            "mean_growth_pct_per_week_busy": round(float(np.mean([r["growth_pct_per_week"] for r in busy])), 3) if busy else None,
            "links_with_a_projected_date": sum(r["days_until_critical"] is not None for r in rows), "rows": rows}


def configured_growth() -> float:
    return load_topology(CAMPUS).growth_per_week * 100


# ------------------------------------------------------------------ charts
def chart_growth(results: Results, rows: list[dict], seed: int, configured: float) -> None:
    mine = sorted((r for r in rows if r["seed"] == seed), key=lambda r: r["page_growth_pct_per_week"])
    if not mine:
        return
    figure, axes = chart(6.6, max(2.8, 0.17 * len(mine) + 0.9))
    y = np.arange(len(mine))
    for k, r in enumerate(mine):
        axes.plot([r["interval_low"], r["interval_high"]], [k, k], color=SERIES[0], linewidth=1.4, alpha=0.55)
    axes.scatter([r["page_growth_pct_per_week"] for r in mine], y, s=18, color=SERIES[0], zorder=3,
                 label="Trends page's growth, with its 95 % interval")
    axes.axvline(configured, color=INK_2, linestyle=(0, (4, 3)), linewidth=1.2, label=f"Configured growth ({configured:g} % a week)")
    axes.set_yticks(y, [r["link"] for r in mine], fontsize=6.5)
    axes.set_xlabel("Growth of the daily 95th percentile (% a week)")
    axes.grid(axis="y", visible=False)
    legend(axes, ncol=1)
    results.save_chart(figure, "e9_growth_by_link.png")


def chart_crossings(results: Results, part: dict) -> None:
    scored = [r for r in part["rows"] if r["status"] == "scored"]
    if not scored:
        return
    figure, axes = chart(4.6, 4.0)
    xs = [r["actual_crossing_day"] for r in scored]
    ys = [r["projected_crossing_day"] for r in scored]
    lo, hi = min(xs + ys) - 2, max(xs + ys) + 2
    axes.plot([lo, hi], [lo, hi], color=MUTED, linewidth=1.0, label="Projection = actual")
    axes.scatter(xs, ys, s=30, color=SERIES[0], zorder=3, label="Ramped link")
    axes.set_xlim(lo, hi)
    axes.set_ylim(lo, hi)
    axes.set_xlabel("Actual day the daily 95th percentile reached 90 %")
    axes.set_ylabel("Day projected by the Trends page")
    legend(axes, ncol=1)
    results.save_chart(figure, "e9_projected_vs_actual_crossing.png")


def chart_example(results: Results, part: dict) -> dict:
    scored = [r for r in part["rows"] if r["status"] == "scored"]
    if not scored:
        return {}
    r = min(scored, key=lambda r: r["actual_crossing_day"])           # rule: the first link to cross
    days, window = part["days"], part["window_days"]
    series = np.array([r[f"day{d}_p95"] for d in range(days)], dtype=float)
    figure, axes = chart(6.6, 3.4)
    axes.plot(np.arange(days), series, color=SERIES[0], linewidth=2.0, marker="o", markersize=3,
              label="Daily 95th percentile")
    from apps.api.views.trends import trend_design

    dates = [START.date() + timedelta(days=i) for i in range(days)]
    coef = np.linalg.lstsq(trend_design(dates[:window]), series[:window], rcond=None)[0]
    line = trend_design(dates)[:, :len(coef)] @ coef
    axes.plot(np.arange(days), line, color=SERIES[1], linestyle=(0, (5, 3)), linewidth=1.6,
              label=f"Trends page's fit from days 0-{window - 1}, continued")
    axes.axvspan(-0.5, window - 0.5, color=MUTED, alpha=0.08, lw=0)
    threshold_lines(axes)
    axes.axvline(r["actual_crossing_day"], color=INK_2, linewidth=1.0)
    axes.text(r["actual_crossing_day"] + 0.2, 4, "reached 90 %", fontsize=8, color=INK_2)
    axes.set_ylim(0, 105)
    axes.set_xlabel(f"Day of the ramp world ({r['link']}); shaded: the 14 days the page fits" if window == 14
                    else f"Day of the ramp world ({r['link']}); shaded: the days the page fits")
    axes.set_ylabel("Link utilisation (%)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e9_ramped_link_example.png")
    return {"link": r["link"], "projected_day": r["projected_crossing_day"], "actual_day": r["actual_crossing_day"]}


# ------------------------------------------------------------------ main
def main() -> None:
    parser = argparse.ArgumentParser(description="E9 capacity planning: projected vs configured growth.")
    parser.add_argument("--quick", action="store_true", help="one 7-day growth world and a 14-day ramp world")
    parser.add_argument("--no-database", action="store_true", help="skip part C (the stored history)")
    args = parser.parse_args()
    quick = args.quick
    seeds = GROWTH_SEEDS[:1] if quick else GROWTH_SEEDS
    growth_days = 7 if quick else WINDOW_DAYS
    ramp_days, window = (14, 7) if quick else (RAMP_WORLD_DAYS, WINDOW_DAYS)
    configured = configured_growth()
    topo = load_topology(CAMPUS)
    labels = [f"{lk.a} - {lk.b}" for lk in topo.links]
    results = Results("E9", "Capacity planning (Chapter 3 weakness 3)", config={
        "quick": quick, "start": START.isoformat(), "traffic_calendar_origin": (START - timedelta(days=ORIGIN_DAYS_BEFORE)).isoformat(),
        "growth_seeds": list(seeds), "growth_days": growth_days, "ramp_seed": RAMP_SEED, "ramp_days": ramp_days,
        "fit_window_days": window, "ramps": [f"{z}/{c}" for z, c in RAMPS], "cross_day_target": CROSS_DAY,
        "busy_link_mean_p95_pct": BUSY_P95_PCT, "ramped_link_rise_pts": RAMPED_RISE_PTS, "critical_pct": CRITICAL_PCT,
        "configured_growth_pct_per_week": configured, "method": "apps.api.views.trends.project on daily p95 "
        "(percentile_cont = numpy linear); emulator ground truth stands in for the twin's readings (E1)"})
    for stale in results.folder.glob("*"):
        if stale.suffix in (".csv", ".png", ".json"):
            stale.unlink()

    setup_django()
    page_project(np.array([1.0, 2.0, 3.0, 4.0]), 4, START.date())      # fail now, not after a simulated week
    print("part A: configured growth", flush=True)
    a = part_a(results, seeds, growth_days, labels)
    print("part B: ramped links", flush=True)
    b = part_b(results, ramp_days, window, labels)
    c = {"available": False, "skipped": True}
    if not args.no_database:
        print("part C: the stored history", flush=True)
        try:
            c = part_c()
        except Exception as error:      # no database: report, the other parts stand
            c = {"available": False, "error": str(error)[:200]}
        if c.get("rows"):
            results.write_csv("stored_history_by_link.csv", c["rows"])

    chart_growth(results, a["rows"], seeds[0], configured)
    chart_crossings(results, b)
    example = chart_example(results, b)
    interval = a["interval_95"]
    met = bool(interval is not None and interval[0] <= configured <= interval[1])
    results.summary = {
        "quick": quick,
        "target": f"configured growth ({configured:g} % a week) inside the 95 % interval of the Trends page's growth "
                  "(mean over busy links, interval across independent worlds)",
        "target_met": met if interval is not None else False,
        "configured_growth_pct_per_week": configured,
        "growth": {k: v for k, v in a.items() if k != "rows"},
        "crossing": {k: v for k, v in b.items() if k not in ("rows", "p95")},
        "example_ramped_link": example,
        "stored_history": {k: v for k, v in c.items() if k != "rows"},
    }
    if interval is None:
        results.summary["target_note"] = "one world only (quick run): no interval across worlds"
    path = results.finish()
    print(f"wrote {path}")
    print(f"mean page growth {a['mean_growth_pct_per_week']} %/week, interval {interval}, configured {configured}: met {met}; "
          f"crossings scored {b['scored_links']}, median error {b['error_days_median']} days")


if __name__ == "__main__":
    main()
