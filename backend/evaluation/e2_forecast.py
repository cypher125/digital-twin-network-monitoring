"""E2 Forecast accuracy (FR3): how well the trained models forecast link utilisation 5, 10, 15 and
30 minutes ahead, compared with gradient boosting and three simple baselines.

What is measured. The two active Random Forest models are scored on the held-out test period of
their own training split. The models are the full model, which uses the same time "yesterday",
and the short-history model, which serves the first day. They are compared with gradient
boosting (HistGradientBoostingRegressor, one model per horizon, the candidate from Table 3.4) and
three baselines computed by the training code (models.baseline_predictions):
  * persistence: utilisation stays where it is now;
  * linear trend: the 15-minute least-squares slope, continued for h minutes;
  * same time yesterday: the value at the target time on the previous day of the same type
    (Monday uses Friday, Saturday the previous Sunday, every other day the day before).
All regression models predict the change from now and add it to the current utilisation.

Data and split. The history is the one the models were trained on: 14 days of emulator traffic
collected by the twin (network time 14 Oct 2026 01:33 to 28 Oct 2026 01:33 UTC, one cycle a
minute, 43 links). It is loaded with the same function and arguments as `manage.py
train_models`, with the end pinned to the end of the recorded training history, so live cycles
stored later cannot change the result. The split is reproduced with the training code
(training.split_rows: train fraction 10/14, every 3rd cycle for training and every 2nd for
testing). The run stops unless the reproduced split gives exactly the training window recorded
in each model's metadata. Only test rows are scored. Training targets end at least 30 minutes
before the first test row, so no test value was seen in training (checked). The test period
runs from Saturday 24 October 09:03 to Wednesday 28 October 02:03 West Africa Time (WAT) for
the full model, and from 02:28 on the Saturday for the short model. It covers a weekend and two
weekdays.
Since training, the 14-day retention has removed the oldest hours of that history from the
database. Those cycles are treated as gaps. They lie days before the first test row, so no
test feature or target reaches them (checked). The run also checks that the reproduced test
scores of the Random Forest, the baselines and the warning classifier equal those recorded at
training time ("reproduction" in results.json).

Gradient boosting. The model registry stores the Random Forests but not the gradient-boosting
model trained beside them. E2 therefore refits it on the training rows of the same split, with
the training code's settings, row sampling and seed. Because of the pruned hours, the refit
sees slightly fewer training rows than the original, so its scores are reported next to the
scores recorded at training time.

Metrics, per model and horizon (error = forecast minus actual utilisation, in percentage
points): MAE, RMSE, MAPE (only samples whose actual utilisation is at least 10 %; percentage
errors on near-idle links are meaningless), R², and skill against persistence
(1 - MAE / MAE of persistence). Breakdowns: per link tier (WAN, core, distribution, access,
server, from the roles of the link's two ends, features.link_tier), for the high-load subset
(utilisation now at least 70 %, the warning threshold), and per test day. A daily-load table
covers every day of the history. It gives the mean utilisation from 10:00 to 16:00 WAT (the
software-update surge window in campus.yaml) relative to the median of the other days of the
same type, and so shows on which day that unseen event actually fell.

Uncertainty. Errors on one link a few minutes apart are strongly correlated, so ordinary
confidence intervals would be far too narrow. The 95 % intervals for the difference in MAE
(Random Forest minus each other method) therefore come from a block bootstrap. The test samples
are grouped into (link, calendar day in WAT) blocks. Whole blocks are resampled with
replacement, 2,000 times, with the same resamples for every comparison. The 2.5th and 97.5th
percentiles of the pooled difference are reported. A difference is called clear when its
interval excludes zero.

Warnings. The classification forest that raises warnings is scored on the same test rows,
where the link is below 90 % now, as training does (training.classification_metrics). A
positive is a sample where the link reaches 90 % at any cycle within the horizon. The model
warns when its probability reaches the threshold that was chosen at training time on the last
20 % of the training period, never on the test period. Its precision, recall and F1 are
compared with the linear-trend alarm (warn when the trend line reaches 90 % at the horizon) and
with the regression-forecast alarm (warn when the Random Forest forecast reaches 90 %).

Also reported:
  * feature importance as recorded at training time: the forest's impurity importance, and
    permutation importance (the increase in MAE of the predicted change when one feature is
    shuffled, averaged over the four horizons, on 20,000 test samples with 2 repeats);
  * training time and model sizes, as recorded in the model metadata;
  * inference time for one live cycle: the engine's Predictor forecasting all 43 links at four
    horizons from a history buffer the length the live engine keeps. That is 7 days + 60 cycles
    for the full model, and 1 day for the short model (the most history it ever serves with).
    The figure is the median of 20 runs after a warm-up, on the 2-core Celeron laptop.

Target (plan section 11): the Random Forest beats every baseline at every horizon, judged on
MAE. The short model is judged against persistence and linear trend, the baselines that exist
when it is in use (there is no previous day yet). Same time yesterday is shown for it as a
reference only. Gradient boosting is a compared candidate, not a baseline: the run says plainly
where it is as good as or better than the Random Forest.

Limitations.
  * The data are synthetic. The emulator's traffic is smooth daily profiles times noise, plus
    random flash crowds, so the errors are far lower than they would be on real traffic. The
    results show the method works on this emulated campus, not how it would do on a real
    network. Vinayakumar et al. (LSTM on real traffic) are context only.
  * One test period of about 3.7 days: one weekend, two weekdays and the start of a third. The
    plan's table says "Thursday to Sunday", but the as-built split puts Saturday to Tuesday in
    the test period. The per-day table shows how much the error varies from day to day.
  * The plan expects the test period to contain the scheduled software-update day (campus.yaml
    event "day 11", 10:00-16:00, web traffic x1.6 everywhere), an event the model never saw.
    The emulator counts event days from its own start, and an emulator resumed from its saved
    clock starts counting again. In this history no test day shows that surge: on the
    daily-load table every test day is within 1 % of the median of other days of its type.
    The most unusual daytime (Wednesday 21 October, about 6 % above other weekdays) lies in the
    training period, and its hourly shape does not match the event cleanly. Chapter 4 should
    therefore not claim that E2 tested the forecasts on an unseen event.
  * R² pools links with very different average loads, so it mostly measures the differences
    between links and is close to 1 even for persistence. MAE and skill are the informative
    measures.
  * Warning positives are counted per sample (per minute), not per event. They come from a
    handful of congestion episodes, so precision and recall are noisy and the samples are not
    independent. E3 measures warnings per event.
  * The bootstrap treats (link, day) blocks as independent. Links share the daily traffic
    pattern, so the intervals may still be somewhat narrow.
  * Gradient boosting is a refit (see above). Training times come from the metadata and were
    measured while training on this laptop. Inference times depend on what else is running, so
    the run records how busy the machine's CPU was just before each timing. A figure taken
    while another program kept the CPU busy overstates the time a cycle needs.

Quick mode (--quick) checks the pipeline in a few minutes. It uses every 10th test row and 100
bootstrap resamples, and refits gradient boosting on every 8th training sample with 60 rounds
instead of 250. Its numbers are not for Chapter 4, least of all the gradient-boosting ones. The
reproduction check always uses the full test set.

    python -m evaluation.e2_forecast [--quick] [--resamples 2000] [--timing-runs 20] [--selftest]
"""
from __future__ import annotations

import argparse
import gc
import os
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from digital_twin.prediction_engine.features import (
    MAX_FILL_GAP,
    SAME_TYPE_DAYS_BACK,
    SHORT_HISTORY,
    TIERS,
    WAT_OFFSET_SECONDS,
    FeatureSpec,
    build_crossing_labels,
    build_features,
    build_targets,
    fill_short_gaps,
    static_features,
)
from digital_twin.prediction_engine.models import BoostingForecaster, baseline_predictions
from digital_twin.prediction_engine.training import (
    History,
    _limit,
    classification_metrics,
    metrics,
    split_rows,
)

from .common import INK_2, SERIES, Results, chart, legend

TRAIN_FRACTION = 10 / 14          # train_models default (D20); the split is checked against the metadata
TRAIN_STRIDE, TEST_STRIDE = 3, 2  # training.train defaults
MAX_TRAIN_SAMPLES = 200_000       # train_models default
TRAIN_SEED = 7                    # training.train default (row sampling); models use random_state 7
BOOT_SEED = 2026
FULL_RESAMPLES, QUICK_RESAMPLES = 2000, 100
QUICK_TEST_EVERY = 10             # quick mode: every 10th test row
QUICK_TRAIN_EVERY = 8             # quick mode: boosting refit on every 8th training sample ...
QUICK_BOOSTING_ITERATIONS = 60    # ... with 60 boosting rounds instead of 250 (a pipeline check only)
EVENT_HOURS_WAT = (10, 16)        # the software-update day's surge window (campus.yaml events)
HIGH_LOAD_PCT = 70.0              # warning threshold: the high-load subset is "utilisation now >= 70 %"
TOLERANCE = 1e-6                  # reproduction check (absolute, on metrics in their own units)

METHODS = ("random_forest", "gradient_boosting", "persistence", "linear_trend", "same_time_yesterday")
BASELINES = ("persistence", "linear_trend", "same_time_yesterday")
LABELS = {"random_forest": "Random Forest", "gradient_boosting": "Gradient boosting",
          "persistence": "Persistence", "linear_trend": "Linear trend",
          "same_time_yesterday": "Same time yesterday"}
KIND_LABELS = {"full": "Full model", "short": "Short-history model"}
TIER_LABELS = {"wan": "WAN", "core": "Core", "distribution": "Distribution", "access": "Access",
               "server": "Server"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


_STARTED = time.perf_counter()


def log(message: str) -> None:
    print(f"{time.perf_counter() - _STARTED:6.0f} s  {message}", flush=True)


def cpu_busy_pct(seconds: float = 1.0) -> float | None:
    """Whole-machine CPU use just before a timing (other programs inflate timings)."""
    try:
        import psutil
        return float(psutil.cpu_percent(interval=seconds))
    except ImportError:
        return None


# ------------------------------------------------------------------ helpers (pure, self-tested)
def iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), UTC).isoformat(timespec="minutes")


def wat_day(epoch: np.ndarray) -> np.ndarray:
    """Calendar day number in West Africa Time (the network's local time, features.WAT_OFFSET_SECONDS)."""
    return ((np.asarray(epoch, dtype=np.int64) + WAT_OFFSET_SECONDS) // 86400).astype(np.int64)


def day_label(day: int) -> str:
    date = datetime.fromtimestamp(int(day) * 86400, UTC).date()
    return f"{date.isoformat()} {WEEKDAYS[date.weekday()]}"


def daily_load(times: np.ndarray, util: np.ndarray, tiers: list[str], test_start: float,
               hours: tuple[int, int] = EVENT_HOURS_WAT) -> list[dict]:
    """Per calendar day (WAT): mean utilisation of all links and of the WAN links during `hours`, and
    that mean relative to the median of the other days of the same type (weekday or weekend).

    Used to see where a network-wide daytime event (the software-update day) fell."""
    times = np.asarray(times, dtype=np.float64)
    local = times.astype(np.int64) + WAT_OFFSET_SECONDS
    day, hour = local // 86400, (local % 86400) / 3600.0
    inside = (hour >= hours[0]) & (hour < hours[1])
    step = float(np.median(np.diff(times))) if len(times) > 1 else 60.0
    needed = 0.9 * (hours[1] - hours[0]) * 3600 / step
    wan = np.array([t == "wan" for t in tiers])
    rows = []
    with np.errstate(invalid="ignore"):
        for d in np.unique(day):
            mask = (day == d) & inside
            block = util[mask]
            if np.isfinite(block).any(axis=1).sum() < needed:
                continue                                   # the window is not (almost) complete that day
            weekend = datetime.fromtimestamp(int(d) * 86400, UTC).weekday() >= 5
            rows.append({"day_wat": day_label(d), "weekend": weekend,
                         "in_test": bool(times[mask][0] >= test_start),
                         "mean_util_all_links_pct": float(np.nanmean(block)),
                         "mean_util_wan_pct": float(np.nanmean(block[:, wan])) if wan.any() else None,
                         "max_util_wan_pct": float(np.nanmax(block[:, wan])) if wan.any() else None})
    for row in rows:
        others = [r["mean_util_all_links_pct"] for r in rows if r["weekend"] == row["weekend"] and r is not row]
        row["vs_same_type_median"] = row["mean_util_all_links_pct"] / float(np.median(others)) if others else None
    return rows


def place_on_grid(times: np.ndarray, util: np.ndarray, errors: np.ndarray, since: float, end: float,
                  cycle: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Put loaded history rows on the training-time grid since..end (inclusive).

    Rows after `end` (live cycles stored later) are dropped, and cycles with no stored rows (removed
    by retention) become gaps. Returns (times, util, errors, leading cycles with no data at all)."""
    count = int(round((end - since) / cycle)) + 1
    grid = since + np.arange(count, dtype=np.float64) * cycle
    out_u = np.full((count, util.shape[1]), np.nan, dtype=np.float32)
    out_e = np.full((count, util.shape[1]), np.nan, dtype=np.float32)
    if len(times):
        idx = np.round((np.asarray(times) - since) / cycle).astype(np.int64)
        if np.abs(since + idx * cycle - times).max() > 1.0:
            raise ValueError("stored cycles are not on the training grid")
        ok = (idx >= 0) & (idx < count)
        out_u[idx[ok]] = util[ok]
        out_e[idx[ok]] = errors[ok]
    present = np.flatnonzero(~np.isnan(out_u).all(axis=1))
    leading = int(present[0]) if len(present) else count
    return grid, out_u, out_e, leading


def window_of(times: np.ndarray, train_rows: np.ndarray, test_rows: np.ndarray) -> dict[str, str]:
    return {"train_start": iso(times[train_rows[0]]), "train_end": iso(times[train_rows[-1]]),
            "test_start": iso(times[test_rows[0]]), "test_end": iso(times[test_rows[-1]])}


def recorded_window(meta: dict) -> dict[str, str]:
    return {k: iso(datetime.fromisoformat(v).timestamp()) for k, v in meta["window"].items()}


def pinned_history(meta: dict, spec: FeatureSpec) -> tuple[float, float]:
    """(since, end) epoch seconds of the history the model was trained on, from its metadata.

    The last test row lies within one test stride of `end - longest horizon`; the candidate whose
    split reproduces the whole recorded window is the training history."""
    cycle, cycles = spec.cycle_seconds, int(meta["rows"]["history_cycles"])
    target = recorded_window(meta)
    test_end = datetime.fromisoformat(meta["window"]["test_end"]).timestamp()
    probe_static = np.zeros((1, 1 + len(TIERS)), dtype=np.float32)
    for extra in range(TEST_STRIDE):
        end = test_end + (max(spec.horizon_steps) + extra) * cycle
        since = end - (cycles - 1) * cycle
        times = since + np.arange(cycles, dtype=np.float64) * cycle
        probe = History(times, np.zeros((cycles, 1), np.float32), None, probe_static, [0], cycle)
        train_rows, test_rows = split_rows(probe, spec, TRAIN_FRACTION, TRAIN_STRIDE, TEST_STRIDE)
        if window_of(times, train_rows, test_rows) == target:
            return since, end
    raise SystemExit(f"cannot reproduce the training split of {meta['version']}: window {target}")


def earliest_lookback(test_rows: np.ndarray, spec: FeatureSpec) -> int:
    """The earliest history row any test feature can read (lags, windows, gap filling, 'yesterday')."""
    back = SHORT_HISTORY + MAX_FILL_GAP
    if spec.full:
        back = max(back, max(SAME_TYPE_DAYS_BACK) * spec.day_steps + MAX_FILL_GAP)
    return int(test_rows[0]) - back


def indexed_matrices(history: History, spec: FeatureSpec, rows: np.ndarray, critical: float,
                     chunk: int = 600) -> tuple[np.ndarray, ...]:
    """training.matrices, plus the history row and link column of every kept sample.

    Built in chunks of rows to keep peak memory low: the features of a row depend only on the
    history, never on the other rows requested, so the result equals training.matrices (selftest)."""
    util = fill_short_gaps(history.util)
    parts = []
    for start in range(0, len(rows), chunk):
        part = np.asarray(rows[start:start + chunk], dtype=np.int64)
        X = build_features(util, history.times, history.static, history.errors, spec, part)
        Y = build_targets(history.util, part, spec)            # targets use the raw (unfilled) values
        C = build_crossing_labels(history.util, part, spec, critical)
        links = X.shape[1]
        row_of, link_of = np.repeat(part, links), np.tile(np.arange(links), len(part))
        X, Y, C = X.reshape(-1, X.shape[2]), Y.reshape(-1, Y.shape[2]), C.reshape(-1, C.shape[2])
        keep = ~np.isnan(Y).any(axis=1) & ~np.isnan(X[:, 0]) & ~np.isnan(C).any(axis=1)
        parts.append((X[keep], Y[keep], C[keep], row_of[keep], link_of[keep]))
        del X, Y, C
    return tuple(np.concatenate(p) for p in zip(*parts, strict=True))


class BlockBootstrap:
    """Percentile intervals for a pooled mean difference, resampling whole blocks with replacement.

    The same resamples are used for every comparison (`weights[r, b]` = times block b is drawn)."""

    def __init__(self, blocks: np.ndarray, resamples: int, seed: int):
        self.ids, self.inverse = np.unique(blocks, return_inverse=True)
        self.blocks = len(self.ids)
        self.counts = np.bincount(self.inverse, minlength=self.blocks).astype(np.float64)
        pick = np.random.default_rng(seed).integers(0, self.blocks, size=(resamples, self.blocks))
        self.weights = np.zeros((resamples, self.blocks))
        np.add.at(self.weights, (np.arange(resamples)[:, None], pick), 1.0)
        self.resamples = resamples

    def interval(self, diff: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """diff: (n, H) per-sample differences. Returns (point, low, high), each (H,)."""
        diff = np.asarray(diff, dtype=np.float64).reshape(len(diff), -1)
        sums = np.stack([np.bincount(self.inverse, weights=diff[:, j], minlength=self.blocks)
                         for j in range(diff.shape[1])], axis=1)
        point = sums.sum(axis=0) / self.counts.sum()
        stats = (self.weights @ sums) / (self.weights @ self.counts)[:, None]
        low, high = np.percentile(stats, [2.5, 97.5], axis=0)
        return point, low, high


def verdict(low: float, high: float) -> str:
    if high < 0:
        return "random forest better"
    if low > 0:
        return "random forest worse"
    return "no clear difference"


def feature_label(name: str, cycle_seconds: int = 60) -> str:
    """Plain-English name of a feature (features.FeatureSpec.names) for the importance chart."""
    head, _, tail = name.rpartition("_")
    in_cycles = head in ("lag", "mean", "std", "max", "slope")       # the others are named in minutes
    fixed = {"util_now": "Utilisation now", "errors_5": "Errors, last 5 min", "hour_sin": "Time of day (sin)",
             "hour_cos": "Time of day (cos)", "dow_sin": "Day of week (sin)", "dow_cos": "Day of week (cos)",
             "weekend": "Weekend flag", "log_capacity": "Link capacity (log)", "yesterday_now": "Yesterday, now"}
    if name in fixed:
        return fixed[name]
    if name.startswith("tier_"):
        return f"Tier: {TIER_LABELS.get(name[5:], name[5:])}"
    patterns = {"lag": "Utilisation {} ago", "mean": "Mean, last {}", "std": "Std. dev., last {}",
                "max": "Maximum, last {}", "slope": "Slope, last {}", "projection": "Trend projection, +{}",
                "yesterday_plus": "Yesterday, +{}", "yesterday_change": "Yesterday's change over {}",
                "seasonal_gap": "Yesterday at +{} minus now"}
    if head in patterns and tail.isdigit():
        minutes = int(tail) * cycle_seconds // 60 if in_cycles else int(tail)
        return patterns[head].format(f"{minutes} min")
    return name


# ------------------------------------------------------------------ data (Django)
def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django
    django.setup()


def topology(link_ids: list[int], twin: dict) -> tuple[np.ndarray, list[str], list[str]]:
    """Static features, tier and name of each link, from the Topology Store as train_models builds them.

    The network model is built without seeding the latest readings (persistence.build_model does
    that): static features use only capacities and device roles, which seeding does not touch."""
    from digital_twin.network_model import NetworkModel
    from digital_twin.runtime import persistence
    from digital_twin.runtime.forecasting import link_static

    _, devices, links = persistence.load_topology()
    model = NetworkModel(devices, links, warning_pct=twin["WARNING_THRESHOLD_PCT"],
                         critical_pct=twin["CRITICAL_THRESHOLD_PCT"],
                         reference_bandwidth_mbps=twin["REFERENCE_BANDWIDTH_MBPS"])
    if sorted(model.link_ends) != list(link_ids):
        raise SystemExit("the links in the database differ from those the models were trained on")
    static = link_static(model, link_ids)
    tiers = [TIERS[int(np.argmax(static[i, 1:]))] for i in range(len(link_ids))]
    names = []
    for link_id in link_ids:
        u, v = model.link_ends[link_id]
        names.append(f"{model.device(u)['name']} - {model.device(v)['name']}")
    return static, tiers, names


def training_history(link_ids: list[int], cycle: int, since: float, end: float,
                     static: np.ndarray) -> tuple[History, int]:
    """The training history, loaded as train_models does (persistence.load_history from `since`)."""
    from digital_twin.runtime import persistence

    times, util, errors = persistence.load_history(link_ids, cycle, datetime.fromtimestamp(since, UTC))
    grid, util, errors, leading = place_on_grid(times, util, errors, since, end, cycle)
    return History(grid, util, errors, static, list(link_ids), cycle), leading


# ------------------------------------------------------------------ one model
@dataclass
class Tables:
    overall: list
    tiers: list
    high: list
    days: list
    day_context: list
    bootstrap: list
    warnings: list
    importance: list
    timing: list
    reproduction: list
    models: list
    daily_load: list


def metric_rows(kind: str, subset: dict, scores: dict, horizons, persistence_key: str = "persistence") -> list[dict]:
    rows = []
    for method, by_h in scores.items():
        for h in horizons:
            m = by_h[str(h)]
            base = scores.get(persistence_key, {}).get(str(h), {}).get("mae")
            rows.append({"model": kind, **subset, "method": method, "horizon_min": h, "mae": m["mae"],
                         "rmse": m["rmse"], "mape_busy_pct": m["mape_busy"], "r2": m["r2"],
                         "skill_vs_persistence": (1 - m["mae"] / base) if base else None,
                         "mae_actual_at_least_70": m["mae_high"], "samples": m["samples"],
                         "samples_actual_at_least_70": m["samples_high"]})
    return rows


def refit_boosting(history: History, spec: FeatureSpec, train_rows: np.ndarray, critical: float,
                   quick: bool) -> tuple[BoostingForecaster, dict]:
    """Gradient boosting refit on the training rows, with training.train's sampling and settings
    (quick mode: fewer samples and rounds, to check the pipeline only)."""
    X, Y, C, _, _ = indexed_matrices(history, spec, train_rows, critical)
    X, Y, C = _limit(X, Y, C, MAX_TRAIN_SAMPLES, np.random.default_rng(TRAIN_SEED))
    params = {"max_iter": QUICK_BOOSTING_ITERATIONS} if quick else {}
    if quick:
        X, Y = X[::QUICK_TRAIN_EVERY], Y[::QUICK_TRAIN_EVERY]
    began = time.perf_counter()
    boosting = BoostingForecaster(**params).fit(X, Y)
    info = {"seconds": round(time.perf_counter() - began, 1), "samples": int(len(X)),
            "bytes": boosting.size_bytes(), "settings_changed_for_quick": params}
    del X, Y, C
    gc.collect()
    return boosting, info


def reproduction_rows(kind: str, meta: dict, scores: dict, classification: dict) -> list[dict]:
    rows = []
    for method, recorded in meta["metrics"].items():
        for h, rec in recorded.items():
            for metric in ("mae", "rmse", "mape_busy", "r2", "mae_high", "samples", "samples_high"):
                new = scores.get(method, {}).get(h, {}).get(metric)
                rows.append(_compared(kind, "refit, informative" if method == "gradient_boosting" else "must match",
                                      method, h, metric, rec.get(metric), new))
    for method, recorded in meta.get("classification", {}).items():
        for h, rec in recorded.items():
            for metric in ("positives", "samples", "precision", "recall", "f1"):
                new = classification.get(method, {}).get(h, {}).get(metric)
                rows.append(_compared(kind, "must match", method, h, metric, rec.get(metric), new))
    return rows


def _compared(kind: str, check: str, method: str, horizon: str, metric: str, old, new) -> dict:
    diff = abs(new - old) if new is not None and old is not None else None
    if diff is None:
        match = old is None and new is None
    else:
        match = diff <= TOLERANCE * max(1.0, abs(old))
    return {"model": kind, "check": check, "method": method, "horizon_min": int(horizon), "metric": metric,
            "recorded": old, "reproduced": new, "abs_diff": diff, "match": match}


def inference_ms(model, static: np.ndarray, history: History, cycles: int, runs: int,
                 critical: float) -> list[float]:
    """One live cycle: the engine's Predictor on a history buffer of `cycles` cycles."""
    from digital_twin.prediction_engine import HistoryBuffer, Predictor

    n = min(cycles, len(history.times))
    buffer = HistoryBuffer(history.link_ids, history.cycle_seconds, cycles)
    buffer.times[:n] = history.times[-n:]          # the grid is regular: same as appending cycle by cycle
    buffer.util[:n] = history.util[-n:]
    buffer.errors[:n] = history.errors[-n:]
    buffer.size = n
    predictor = Predictor({model.kind: model}, static, history.link_ids, critical)
    if predictor.choose(buffer.size) is not model:
        raise RuntimeError(f"the predictor would not use the {model.kind} model on {n} cycles")
    expected = len(history.link_ids) * len(model.spec.horizons_minutes)
    if len(predictor.predict(buffer)) != expected:           # warm-up, and a sanity check
        raise RuntimeError("the predictor did not forecast every link at every horizon")
    out = []
    for _ in range(runs):
        began = time.perf_counter()
        predictor.predict(buffer)
        out.append((time.perf_counter() - began) * 1000)
    return out


def evaluate(kind: str, model, history: History, leading: int, tiers: list[str], args, resamples: int,
             critical: float, tables: Tables) -> dict:
    spec, meta = model.spec, model.meta
    horizons = spec.horizons_minutes
    hs = [str(h) for h in horizons]
    log(f"[{kind}] {model.version}")

    # ---- the split, reproduced and checked
    if len(history.times) != int(meta["rows"]["history_cycles"]):
        raise SystemExit(f"{kind}: history has {len(history.times)} cycles, training had {meta['rows']['history_cycles']}")
    train_rows, test_rows = split_rows(history, spec, TRAIN_FRACTION, TRAIN_STRIDE, TEST_STRIDE)
    window = window_of(history.times, train_rows, test_rows)
    if window != recorded_window(meta):
        raise SystemExit(f"{kind}: reproduced split {window} differs from the recorded {recorded_window(meta)}")
    last_target = history.times[train_rows[-1]] + max(spec.horizon_steps) * spec.cycle_seconds
    if not history.times[test_rows[0]] > last_target:
        raise SystemExit(f"{kind}: a training target reaches into the test period")
    if earliest_lookback(test_rows, spec) <= leading:
        raise SystemExit(f"{kind}: test features would read cycles removed by retention")

    # ---- gradient boosting, refit on the training rows
    boosting, gb_info = refit_boosting(history, spec, train_rows, critical, args.quick)
    log(f"[{kind}] gradient boosting refit on {gb_info['samples']} samples in {gb_info['seconds']:.0f} s")

    # ---- test samples (all of them, for the reproduction check)
    X, Y, C, row_of, link_of = indexed_matrices(history, spec, test_rows, critical)
    preds = {"random_forest": model.forest.predict(X), "gradient_boosting": boosting.predict(X)}
    preds.update(baseline_predictions(X, spec))
    log(f"[{kind}] {len(X)} test samples featurised and forecast")
    reference_only = []
    if not spec.full:
        # the short model serves before a previous day exists; same time yesterday is a reference only
        full_spec = FeatureSpec(spec.cycle_seconds, horizons, full=True)
        Xf, _, _, rf_row, rf_link = indexed_matrices(history, full_spec, test_rows, critical)
        if not (np.array_equal(rf_row, row_of) and np.array_equal(rf_link, link_of)):
            raise RuntimeError("full-spec features do not line up with the short model's test samples")
        preds["same_time_yesterday"] = baseline_predictions(Xf, full_spec)["same_time_yesterday"]
        reference_only = ["same_time_yesterday"]
        del Xf
        gc.collect()
    below = X[:, 0] < critical
    threshold = float(getattr(model.classifier, "threshold", 0.5)) if model.classifier is not None else None
    full_class = {"linear_trend": classification_metrics(
        C[below], (preds["linear_trend"][below] >= critical).astype(float), horizons),
        "regression_forecast": classification_metrics(
            C[below], (preds["random_forest"][below] >= critical).astype(float), horizons)}
    if model.classifier is not None:
        full_class["random_forest_classifier"] = classification_metrics(
            C[below], model.classifier.probability(X[below]), horizons, threshold)
    full_scores = {m: metrics(Y, p, horizons) for m, p in preds.items()}
    repro = reproduction_rows(kind, meta, full_scores, full_class)
    tables.reproduction += repro
    must = [r for r in repro if r["check"] == "must match"]
    mismatches = [r for r in must if not r["match"]]
    gb_vs_recorded = {h: {"recorded_mae": meta["metrics"].get("gradient_boosting", {}).get(h, {}).get("mae"),
                          "refit_mae": full_scores["gradient_boosting"][h]["mae"]} for h in hs}
    reproduction = {"passed": not mismatches, "checked_values": len(must), "mismatches": len(mismatches),
                    "max_abs_diff": max((r["abs_diff"] or 0.0) for r in must) if must else None,
                    "gradient_boosting_refit_vs_recorded": gb_vs_recorded}
    log(f"[{kind}] reproduction of recorded test scores: {'passed' if not mismatches else 'FAILED'} "
        f"({len(must)} values, {len(mismatches)} mismatches)")

    # ---- the analysed samples (quick mode: every 10th test row)
    samples_test = int(len(row_of))
    if args.quick:
        keep = np.isin(row_of, test_rows[::QUICK_TEST_EVERY])
        X, Y, C, row_of, link_of = X[keep], Y[keep], C[keep], row_of[keep], link_of[keep]
        preds = {m: p[keep] for m, p in preds.items()}
    gc.collect()
    scores = {m: metrics(Y, p, horizons) for m, p in preds.items()}
    tables.overall += metric_rows(kind, {}, scores, horizons)

    tier_of = np.array(tiers)[link_of]
    tier_scores = {}
    for tier in TIERS:
        mask = tier_of == tier
        if mask.any():
            tier_scores[tier] = {m: metrics(Y[mask], p[mask], horizons) for m, p in preds.items()}
            links = len(np.unique(link_of[mask]))
            tables.tiers += metric_rows(kind, {"tier": tier, "links": links}, tier_scores[tier], horizons)
    high = X[:, 0] >= HIGH_LOAD_PCT
    high_scores = {m: metrics(Y[high], p[high], horizons) for m, p in preds.items()} if high.any() else {}
    tables.high += metric_rows(kind, {"subset": f"utilisation now >= {HIGH_LOAD_PCT:g} %"}, high_scores, horizons)

    days = wat_day(history.times[row_of])
    day_mae = {}
    for day in np.unique(days):
        mask = days == day
        label = day_label(day)
        day_mae[label] = {}
        for m, p in preds.items():
            err = np.abs(p[mask] - Y[mask]).mean(axis=0)
            day_mae[label][m] = {h: float(err[j]) for j, h in enumerate(hs)}
            for j, h in enumerate(horizons):
                tables.days.append({"model": kind, "day_wat": label, "method": m, "horizon_min": h,
                                    "mae": float(err[j]), "samples": int(mask.sum())})
        for tier in TIERS:
            tmask = mask & (tier_of == tier)
            if tmask.any():
                tables.day_context.append({"model": kind, "day_wat": label, "tier": tier,
                                           "mean_util_now_pct": float(X[tmask, 0].mean()),
                                           "max_util_now_pct": float(X[tmask, 0].max()),
                                           "samples": int(tmask.sum())})

    # ---- block bootstrap: Random Forest minus each other method
    boot = BlockBootstrap(link_of.astype(np.int64) * 1_000_000 + days, resamples, BOOT_SEED)
    rf_abs = np.abs(preds["random_forest"] - Y).astype(np.float64)
    intervals = {}
    for other in [m for m in METHODS if m != "random_forest" and m in preds]:
        point, low, high_ = boot.interval(rf_abs - np.abs(preds[other] - Y))
        intervals[other] = {}
        for j, h in enumerate(horizons):
            row = {"model": kind, "comparison": f"random_forest - {other}", "horizon_min": h,
                   "mae_random_forest": scores["random_forest"][hs[j]]["mae"], "mae_other": scores[other][hs[j]]["mae"],
                   "difference": float(point[j]), "ci_low": float(low[j]), "ci_high": float(high_[j]),
                   "verdict": verdict(low[j], high_[j]), "blocks": boot.blocks, "resamples": resamples}
            tables.bootstrap.append(row)
            intervals[other][hs[j]] = {k: row[k] for k in ("difference", "ci_low", "ci_high", "verdict")}
    log(f"[{kind}] breakdowns and block bootstrap ({boot.blocks} blocks, {resamples} resamples) done")

    # ---- warnings
    below = X[:, 0] < critical
    alarms = {"linear_trend": (preds["linear_trend"][below] >= critical).astype(float),
              "regression_forecast": (preds["random_forest"][below] >= critical).astype(float)}
    if args.quick:
        warning = {}
        if model.classifier is not None:
            warning["random_forest_classifier"] = classification_metrics(
                C[below], model.classifier.probability(X[below]), horizons, threshold)
        for name, alarm in alarms.items():
            warning[name] = classification_metrics(C[below], alarm, horizons)
    else:
        warning = full_class                       # the same samples: no need to score them twice
    for method, by_h in warning.items():
        for h in horizons:
            m = by_h[str(h)]
            tables.warnings.append({"model": kind, "method": method, "horizon_min": h,
                                    "threshold": threshold if method == "random_forest_classifier" else None,
                                    **{k: m[k] for k in ("positives", "samples", "precision", "recall", "f1",
                                                         "roc_auc")}})

    # ---- importance, sizes, training time (as recorded), inference time (measured)
    perm = dict(meta.get("permutation_importance") or [])
    mdi = meta.get("importance") or []
    perm_rank = {n: i + 1 for i, (n, _) in enumerate(sorted(perm.items(), key=lambda x: -x[1]))}
    for rank, (name, value) in enumerate(mdi, start=1):
        tables.importance.append({"model": kind, "feature": name, "label": feature_label(name, spec.cycle_seconds),
                                  "forest_importance": value, "forest_rank": rank,
                                  "permutation_importance_pp": perm.get(name), "permutation_rank": perm_rank.get(name)})
    from digital_twin.runtime.forecasting import HISTORY_DAYS
    buffer_cycles = (HISTORY_DAYS * 86400 // spec.cycle_seconds + 60) if spec.full else spec.day_steps
    busy = cpu_busy_pct()
    timing = inference_ms(model, history.static, history, buffer_cycles, args.timing_runs, critical)
    tables.timing += [{"model": kind, "version": model.version, "buffer_cycles": buffer_cycles, "run": i + 1,
                       "ms": ms} for i, ms in enumerate(timing)]
    seconds, sizes = meta.get("seconds", {}), meta.get("sizes", {})
    tables.models.append({"model": kind, "version": model.version, "created_at": meta.get("created_at"),
                          "train_samples": meta["rows"].get("train_samples"),
                          "test_samples": meta["rows"].get("test_samples"),
                          "warning_threshold": threshold, **{f"train_seconds_{k}": v for k, v in seconds.items()},
                          **{k: v for k, v in sizes.items()},
                          "gb_refit_seconds": gb_info["seconds"], "gb_refit_samples": gb_info["samples"],
                          "gb_refit_bytes": gb_info["bytes"]})
    log(f"[{kind}] inference median {statistics.median(timing):.0f} ms on {buffer_cycles} cycles "
        f"(machine CPU {busy}% busy just before)")

    # ---- headline
    target_baselines = [b for b in BASELINES if b in preds and b not in reference_only]
    beats = {h: {b: scores["random_forest"][h]["mae"] < scores[b][h]["mae"] for b in target_baselines} for h in hs}
    mae = {m: {h: scores[m][h]["mae"] for h in hs} for m in preds}
    load = daily_load(history.times, history.util, tiers, history.times[test_rows[0]])
    tables.daily_load += [{"model": kind, **row} for row in load]
    unusual = max((r for r in load if r["vs_same_type_median"] is not None),
                  key=lambda r: r["vs_same_type_median"], default=None)
    return {
        "version": model.version,
        "busiest_daytime_vs_same_type": unusual,
        "test_window_utc": window | {"test_days_wat": sorted({day_label(d) for d in np.unique(days)})},
        "samples_test": samples_test,
        "samples_analysed": int(len(row_of)),
        "samples_high_load": int(high.sum()),
        "history_cycles_missing_at_start": leading,
        "mae": mae,
        "rmse": {m: {h: scores[m][h]["rmse"] for h in hs} for m in preds},
        "mape_busy_pct": {m: {h: scores[m][h]["mape_busy"] for h in hs} for m in preds},
        "r2": {m: {h: scores[m][h]["r2"] for h in hs} for m in preds},
        "skill_vs_persistence": {m: {h: 1 - mae[m][h] / mae["persistence"][h] for h in hs} for m in preds},
        "mae_high_load": {m: {h: high_scores[m][h]["mae"] for h in hs} for m in high_scores},
        "mae_by_tier_30min": {t: {m: s[m]["30"]["mae"] for m in ("random_forest", "persistence")}
                              for t, s in tier_scores.items()} if "30" in hs else {},
        "mae_by_day": day_mae,
        "target_baselines": target_baselines,
        "reference_only": reference_only,
        "beats_baselines": beats,
        "target_met": all(all(v.values()) for v in beats.values()),
        "bootstrap_rf_minus": intervals,
        "warning": {m: {h: {k: by_h[h][k] for k in ("precision", "recall", "f1", "positives")} for h in hs}
                    for m, by_h in warning.items()},
        "warning_threshold": threshold,
        "inference_ms": {"median": statistics.median(timing), "max": max(timing), "runs": len(timing),
                         "buffer_cycles": buffer_cycles, "machine_cpu_busy_pct_before": busy},
        "training_seconds_recorded": seconds,
        "sizes_bytes_recorded": sizes,
        "model_file_within_100_mb": (sizes.get("file_bytes") or 0) <= 100e6,
        "gradient_boosting_refit": gb_info,
        "reproduction": reproduction,
        "_tier_scores": tier_scores,
        "_perm": sorted(perm.items(), key=lambda x: -x[1]),
    }


# ------------------------------------------------------------------ charts
def chart_mae_by_horizon(results: Results, kind: str, out: dict, horizons) -> None:
    figure, axes = chart(6.4, 3.4)
    for colour, method, z in zip(SERIES, ("random_forest", "gradient_boosting", "persistence"), (4, 3, 2),
                                 strict=True):
        axes.plot(horizons, [out["mae"][method][str(h)] for h in horizons], color=colour, marker="o",
                  markersize=4.5, label=LABELS[method], zorder=z)
    axes.set_xticks(list(horizons))
    axes.set_xlabel("Forecast horizon (minutes)")
    axes.set_ylabel("Mean absolute error (percentage points)")
    axes.set_ylim(bottom=0)
    legend(axes, ncol=3)
    results.save_chart(figure, f"mae_by_horizon_{kind}.png")


def chart_bootstrap(results: Results, models: dict, horizons) -> None:
    figure, axes = chart(6.4, 3.4)
    kinds = list(models)
    offsets = np.linspace(-0.45, 0.45, len(kinds)) if len(kinds) > 1 else [0.0]
    for colour, kind, offset in zip(SERIES, kinds, offsets, strict=False):
        data = models[kind]["bootstrap_rf_minus"]["persistence"]
        point = np.array([data[str(h)]["difference"] for h in horizons])
        low = np.array([data[str(h)]["ci_low"] for h in horizons])
        high = np.array([data[str(h)]["ci_high"] for h in horizons])
        axes.errorbar(np.array(horizons, dtype=float) + offset, point, yerr=[point - low, high - point], fmt="o",
                      color=colour, ecolor=colour, elinewidth=1.6, capsize=3, markersize=5,
                      label=KIND_LABELS.get(kind, kind))
    axes.axhline(0.0, color=INK_2, linewidth=0.9, zorder=1)          # no difference
    axes.annotate("Below 0: the Random Forest is more accurate", xy=(0.99, 0.0),
                  xycoords=("axes fraction", "data"), xytext=(0, -4), textcoords="offset points",
                  ha="right", va="top", fontsize=8, color=INK_2)
    axes.set_xticks(list(horizons))
    axes.set_xlabel("Forecast horizon (minutes)")
    axes.set_ylabel("RF MAE minus persistence MAE\n(percentage points)")
    if len(kinds) > 1:
        legend(axes, ncol=2)
    results.save_chart(figure, "rf_minus_persistence_mae.png")


def chart_importance(results: Results, kind: str, perm: list, cycle_seconds: int) -> None:
    top = perm[:15][::-1]
    if not top:
        return
    figure, axes = chart(6.4, 4.4)
    axes.barh(range(len(top)), [v for _, v in top], color=SERIES[0], height=0.62)
    axes.set_yticks(range(len(top)), [feature_label(n, cycle_seconds) for n, _ in top])
    axes.grid(axis="x")
    axes.grid(axis="y", visible=False)
    axes.set_xlabel("Increase in MAE when the feature is shuffled (percentage points)")
    results.save_chart(figure, f"feature_importance_{kind}.png")


def chart_tiers(results: Results, kind: str, tier_scores: dict, links: dict) -> None:
    tiers = [t for t in TIERS if t in tier_scores]
    figure, axes = chart(6.4, 3.4)
    x = np.arange(len(tiers))
    width = 0.38
    for i, (method, colour) in enumerate((("random_forest", SERIES[0]), ("persistence", SERIES[2]))):
        axes.bar(x + (i - 0.5) * width, [tier_scores[t][method]["30"]["mae"] for t in tiers], width,
                 color=colour, label=LABELS[method])
    axes.set_xticks(x, [f"{TIER_LABELS[t]}\n({links[t]} links)" for t in tiers])
    axes.set_xlabel("Link tier")
    axes.set_ylabel("MAE at +30 min (percentage points)")
    legend(axes, ncol=2)
    results.save_chart(figure, f"mae_by_tier_30min_{kind}.png")


# ------------------------------------------------------------------ summary text
def statements(kind: str, out: dict, horizons) -> list[str]:
    hs = [str(h) for h in horizons]
    name = KIND_LABELS.get(kind, kind)
    lines = []
    misses = [(h, b) for h in hs for b in out["target_baselines"] if not out["beats_baselines"][h][b]]
    names = ", ".join(LABELS[b].lower() for b in out["target_baselines"])
    if not misses:
        lines.append(f"{name}: the Random Forest had a lower MAE than every baseline ({names}) at every horizon.")
    for h, b in misses:
        lines.append(f"{name}: the Random Forest did NOT beat {LABELS[b].lower()} at +{h} min "
                     f"(MAE {out['mae']['random_forest'][h]:.3f} vs {out['mae'][b][h]:.3f}).")
    for b in out["target_baselines"]:
        unclear = [h for h in hs if out["bootstrap_rf_minus"][b][h]["verdict"] != "random forest better"]
        if unclear:
            lines.append(f"{name}: against {LABELS[b].lower()} the bootstrap interval does not show a clear "
                         f"advantage at +{', +'.join(unclear)} min.")
    for b in out["reference_only"]:
        worse = [h for h in hs if out["mae"]["random_forest"][h] >= out["mae"][b][h]]
        lines.append(f"{name}: {LABELS[b].lower()} (reference only, not available when this model serves) "
                     + (f"was as good or better at +{', +'.join(worse)} min." if worse else "was worse at every horizon."))
    gb = out["bootstrap_rf_minus"].get("gradient_boosting", {})
    better = [h for h in hs if out["mae"]["gradient_boosting"][h] < out["mae"]["random_forest"][h]]
    if better:
        detail = "; ".join(f"+{h} min: {out['mae']['gradient_boosting'][h]:.3f} vs {out['mae']['random_forest'][h]:.3f}, "
                           + ("a clear difference" if gb[h]["verdict"] != "no clear difference"
                              else "within the bootstrap interval") for h in better)
        lines.append(f"{name}: gradient boosting (refit) had a lower MAE than the Random Forest at "
                     f"+{', +'.join(better)} min ({detail}).")
    else:
        lines.append(f"{name}: the Random Forest had a lower MAE than gradient boosting (refit) at every horizon.")
    return lines


# ------------------------------------------------------------------ run
def run(args) -> None:
    setup_django()
    from django.conf import settings

    from digital_twin.prediction_engine import load_active

    twin = settings.TWIN
    critical = float(twin["CRITICAL_THRESHOLD_PCT"])
    models = load_active(twin["MODEL_DIR"])
    kinds = [k for k in ("full", "short") if k in models]
    if not kinds:
        raise SystemExit("no active models in the registry")
    link_ids = models[kinds[0]].link_ids
    if any(models[k].link_ids != link_ids for k in kinds):
        raise SystemExit("the active models were trained on different links")
    resamples = args.resamples or (QUICK_RESAMPLES if args.quick else FULL_RESAMPLES)
    static, tiers, names = topology(link_ids, twin)
    links_per_tier = {t: tiers.count(t) for t in TIERS if t in tiers}
    pinned = {k: pinned_history(models[k].meta, models[k].spec) for k in kinds}
    config = {
        "quick": bool(args.quick),
        "models": {k: models[k].version for k in kinds},
        "history_utc": {k: {"since": iso(s), "end": iso(e)} for k, (s, e) in pinned.items()},
        "train_fraction": TRAIN_FRACTION, "train_stride": TRAIN_STRIDE, "test_stride": TEST_STRIDE,
        "max_train_samples": MAX_TRAIN_SAMPLES, "train_seed": TRAIN_SEED,
        "horizons_minutes": list(models[kinds[0]].spec.horizons_minutes),
        "cycle_seconds": models[kinds[0]].spec.cycle_seconds,
        "critical_pct": critical, "high_load_pct": HIGH_LOAD_PCT, "mape_min_actual_pct": 10.0,
        "bootstrap": {"blocks": "(link, calendar day in WAT)", "resamples": resamples, "seed": BOOT_SEED,
                      "interval": "95 % percentile"},
        "test_rows_analysed": f"every {QUICK_TEST_EVERY}th test row" if args.quick else "all test rows",
        "gradient_boosting": "refit on the training rows (not stored in the registry); "
                             + (f"quick: every {QUICK_TRAIN_EVERY}th training sample, "
                                f"{QUICK_BOOSTING_ITERATIONS} rounds" if args.quick
                                else "all sampled training rows and the training settings, as training did"),
        "inference_timing_runs": args.timing_runs,
        "links": len(link_ids), "links_per_tier": links_per_tier,
    }
    results = Results("E2", "Forecast accuracy (FR3)", config)
    tables = Tables(*[[] for _ in range(12)])
    histories: dict[tuple[float, float], tuple[History, int]] = {}
    out = {}
    for kind in kinds:
        model = models[kind]
        key = pinned[kind]
        if key not in histories:
            began = time.perf_counter()
            histories[key] = training_history(link_ids, model.spec.cycle_seconds, *key, static)
            log(f"history {iso(key[0])} .. {iso(key[1])} loaded in {time.perf_counter() - began:.0f} s "
                f"({histories[key][1]} cycles at the start no longer stored)")
        history, leading = histories[key]
        out[kind] = evaluate(kind, model, history, leading, tiers, args, resamples, critical, tables)
        gc.collect()

    horizons = models[kinds[0]].spec.horizons_minutes
    for kind in kinds:
        chart_mae_by_horizon(results, kind, out[kind], horizons)
        chart_tiers(results, kind, out[kind]["_tier_scores"], links_per_tier)
        chart_importance(results, kind, out[kind]["_perm"], models[kind].spec.cycle_seconds)
    chart_bootstrap(results, out, horizons)

    results.write_csv("metrics_overall.csv", tables.overall)
    results.write_csv("metrics_by_tier.csv", tables.tiers)
    results.write_csv("metrics_high_load.csv", tables.high)
    results.write_csv("mae_by_day.csv", tables.days)
    results.write_csv("test_days_load.csv", tables.day_context)
    results.write_csv("bootstrap_mae_difference.csv", tables.bootstrap)
    results.write_csv("warning_classifier.csv", tables.warnings)
    results.write_csv("feature_importance.csv", tables.importance)
    results.write_csv("inference_timing.csv", tables.timing)
    results.write_csv("reproduction_check.csv", tables.reproduction)
    results.write_csv("models.csv", tables.models, fields=sorted({k for row in tables.models for k in row},
                                                              key=lambda k: (k != "model", k)))
    results.write_csv("daily_load.csv", tables.daily_load)
    results.write_csv("links.csv", [{"link_id": i, "name": n, "tier": t}
                                     for i, n, t in zip(link_ids, names, tiers, strict=True)])

    lines = [line for kind in kinds for line in statements(kind, out[kind], horizons)]
    results.summary = {
        "quick": bool(args.quick),
        "target": "Random Forest MAE below every baseline at every horizon (plan section 11)",
        "target_met": all(out[k]["target_met"] for k in kinds),
        "reproduction_passed": all(out[k]["reproduction"]["passed"] for k in kinds),
        "statements": lines,
        "models": {k: {key: value for key, value in v.items() if not key.startswith("_")} for k, v in out.items()},
    }
    path = results.finish()
    for line in lines:
        print(" -", line)
    print(f"target met: {results.summary['target_met']}; reproduction passed: {results.summary['reproduction_passed']}")
    print(f"wrote {path}")


# ------------------------------------------------------------------ self-test
def _synthetic_history(cycles: int, links: int, seed: int = 3) -> History:
    rng = np.random.default_rng(seed)
    times = 1_792_000_000.0 + np.arange(cycles) * 60.0
    base = np.linspace(20, 70, links)[None, :]
    util = (base + 15 * np.sin(np.arange(cycles)[:, None] / 90.0) + rng.normal(0, 2, (cycles, links))).astype(np.float32)
    util[rng.random(util.shape) < 0.01] = np.nan
    util[100:108, 0] = np.nan                       # a gap longer than MAX_FILL_GAP
    errors = rng.poisson(0.2, (cycles, links)).astype(np.float32)
    static = static_features(np.full(links, 1000.0), ["core"] * links)
    return History(times, np.clip(util, 0, 100), errors, static, list(range(1, links + 1)), 60)


def _selftest() -> None:
    from digital_twin.prediction_engine.training import matrices

    # 1. indexed_matrices equals training.matrices (short and full feature sets), with correct indices
    for full, cycles in ((False, 400), (True, 1600)):
        history = _synthetic_history(cycles, 3)
        spec = FeatureSpec(60, (5, 10, 15, 30), full=full)
        rows = np.arange(spec.needed_history, cycles - 31, 2)
        X0, Y0, C0 = matrices(history, spec, rows, 80.0)
        X1, Y1, C1, row_of, link_of = indexed_matrices(history, spec, rows, 80.0, chunk=37)
        for a, b in ((X0, X1), (Y0, Y1), (C0, C1)):
            assert a.shape == b.shape and np.array_equal(a, b, equal_nan=True)
        assert np.array_equal(X1[:, 0], fill_short_gaps(history.util)[row_of, link_of], equal_nan=True)
        assert np.allclose(Y1[:, 0], history.util[row_of + 5, link_of])

    # 2. place_on_grid: late start becomes leading gaps, rows after the end are dropped
    times = 1000.0 + np.arange(3, 12) * 60.0
    util = np.arange(9, dtype=np.float32)[:, None].repeat(2, axis=1)
    grid, u, e, leading = place_on_grid(times, util, util.copy(), 1000.0, 1000.0 + 9 * 60, 60)
    assert len(grid) == 10 and leading == 3 and np.isnan(u[:3]).all() and u[3, 0] == 0 and u[9, 1] == 6

    # 3. pinned_history recovers the history end for either test-stride parity
    for full in (True, False):
        spec = FeatureSpec(60, (5, 10, 15, 30), full=full)
        cycles = 14 * 1440 + 1
        for end in (1_792_999_980.0, 1_793_000_040.0):
            times = end - (cycles - 1) * 60 + np.arange(cycles) * 60.0
            probe = History(times, np.zeros((cycles, 1), np.float32), None, np.zeros((1, 6), np.float32), [0], 60)
            tr, te = split_rows(probe, spec, TRAIN_FRACTION, TRAIN_STRIDE, TEST_STRIDE)
            meta = {"version": "test", "rows": {"history_cycles": cycles},
                    "window": {k: datetime.fromisoformat(v).isoformat() for k, v in window_of(times, tr, te).items()}}
            assert pinned_history(meta, spec)[1] == end
            assert earliest_lookback(te, spec) > 0

    # 4. block bootstrap: a constant difference gives a zero-width interval at that value; otherwise the
    #    point estimate is the pooled MAE difference and lies inside the interval
    blocks = np.repeat(np.arange(20), 15)
    point, low, high = BlockBootstrap(blocks, 200, 1).interval(np.full((300, 2), 0.5))
    assert np.allclose(point, 0.5) and np.allclose(low, 0.5) and np.allclose(high, 0.5)
    rng = np.random.default_rng(5)
    truth = rng.normal(50, 10, (300, 1))
    a, b = truth + rng.normal(0, 1, (300, 1)), truth + rng.normal(0, 2, (300, 1))
    diff = np.abs(a - truth) - np.abs(b - truth)
    point, low, high = BlockBootstrap(blocks, 500, 2).interval(diff)
    assert np.isclose(point[0], np.abs(a - truth).mean() - np.abs(b - truth).mean())
    assert low[0] <= point[0] <= high[0] and high[0] < 0 and verdict(low[0], high[0]) == "random forest better"
    assert verdict(-0.1, 0.1) == "no clear difference" and verdict(0.1, 0.2) == "random forest worse"

    # 5. daily load: a day with double daytime load stands out against days of the same type
    t0 = datetime(2026, 10, 19, 0, 0, tzinfo=UTC).timestamp() - WAT_OFFSET_SECONDS       # Monday 00:00 WAT
    times = t0 + np.arange(0, 10 * 1440) * 60.0
    util = np.full((len(times), 2), 20.0, dtype=np.float32)
    util[(times >= t0 + 86400) & (times < t0 + 2 * 86400), :] = 40.0                       # Tuesday
    rows = daily_load(times, util, ["wan", "core"], test_start=t0 + 7 * 86400)
    tue = next(r for r in rows if r["day_wat"].endswith("Tue") and not r["in_test"])
    assert len(rows) == 10 and np.isclose(tue["vs_same_type_median"], 2.0)
    assert [r["in_test"] for r in rows].count(True) == 3

    # 6. calendar day in WAT: 23:30 UTC is already the next day in Lagos
    late = datetime(2026, 10, 24, 23, 30, tzinfo=UTC).timestamp()
    assert day_label(wat_day(np.array([late]))[0]) == "2026-10-25 Sun"
    assert feature_label("seasonal_gap_30") == "Yesterday at +30 min minus now"
    assert feature_label("lag_10") == "Utilisation 10 min ago"
    print("selftest passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2 forecast accuracy (FR3).")
    parser.add_argument("--quick", action="store_true",
                        help="every 10th test row, 100 resamples, boosting refit on a quarter of the samples")
    parser.add_argument("--resamples", type=int, default=None,
                        help=f"bootstrap resamples (default {FULL_RESAMPLES}, quick {QUICK_RESAMPLES})")
    parser.add_argument("--timing-runs", type=int, default=20, help="inference timing runs per model")
    parser.add_argument("--selftest", action="store_true", help="run the unit-level checks and exit")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return
    run(args)


if __name__ == "__main__":
    main()
