"""The ONE feature function, used by training, live forecasting and evaluation E2 (plan section 7.5).

Inputs are time-aligned arrays: one row per monitoring cycle (oldest first) and
one column per link, with NaN for gaps. Features for row t use rows <= t only,
so they never see the future (a unit test checks this).

Features per link at time t:
  util now; lags 1-5, 10, 15, 30, 60 cycles; rolling mean, std and max over 5, 15
  and 60 cycles; 5- and 15-cycle slopes; trend projections (util now + 5-cycle
  slope x horizon) for each horizon; errors over the last 5 cycles; time of day and
  day of week (cyclic), weekend flag; link capacity and tier;
  full model only: the value at the same time "yesterday" and at each target time "yesterday",
  where "yesterday" is the previous day of the SAME type (weekday or weekend): the day before,
  except Monday -> Friday and Saturday -> the previous Sunday. A quiet Sunday is no guide to a
  Monday-morning ramp. If that day is not in the history yet, the values are taken as unchanged
  from now (no seasonal information). The live buffer keeps 7 days, so serving sees the same days.

The short slope and the projections let the model recognise a ramp within a few
minutes of it starting, which is what gives warnings their lead time.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

WAT_OFFSET_SECONDS = 3600            # West Africa Time, no daylight saving
LAGS = (1, 2, 3, 4, 5, 10, 15, 30, 60)
WINDOWS = (5, 15, 60)
SLOPE_WINDOW = 15
SHORT_SLOPE_WINDOW = 5
ERROR_WINDOW = 5
TIERS = ("wan", "core", "distribution", "access", "server")
SHORT_HISTORY = 60                   # cycles the short-history model needs (longest lag and window)
SAME_TYPE_DAYS_BACK = (3, 1, 1, 1, 1, 6, 1)   # Monday..Sunday: days back to the previous day of that type
MAX_FILL_GAP = 5                     # missing polls up to this many cycles are forward-filled


@dataclass(frozen=True)
class FeatureSpec:
    cycle_seconds: int
    horizons_minutes: tuple[int, ...]
    full: bool                        # include same-time-yesterday features

    @property
    def horizon_steps(self) -> tuple[int, ...]:
        return tuple(int(h * 60 // self.cycle_seconds) for h in self.horizons_minutes)

    @property
    def day_steps(self) -> int:
        return int(86400 // self.cycle_seconds)

    @property
    def needed_history(self) -> int:
        """Rows of history required before the first row that can be featurised."""
        return self.day_steps if self.full else SHORT_HISTORY

    def names(self) -> list[str]:
        names = ["util_now"] + [f"lag_{k}" for k in LAGS]
        for w in WINDOWS:
            names += [f"mean_{w}", f"std_{w}", f"max_{w}"]
        names += [f"slope_{SLOPE_WINDOW}", f"slope_{SHORT_SLOPE_WINDOW}"]
        names += [f"projection_{h}" for h in self.horizons_minutes]
        names += [f"errors_{ERROR_WINDOW}", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "weekend",
                  "log_capacity"]
        names += [f"tier_{t}" for t in TIERS]
        if self.full:
            names += ["yesterday_now"] + [f"yesterday_plus_{h}" for h in self.horizons_minutes]
            # what yesterday did over the next h minutes, and where yesterday's level is relative to now:
            # the model predicts the change from now, so these give it yesterday's pattern directly
            names += [f"yesterday_change_{h}" for h in self.horizons_minutes]
            names += [f"seasonal_gap_{h}" for h in self.horizons_minutes]
        return names


def link_tier(roles: tuple[str, str], device_types: tuple[str, str]) -> str:
    """Coarse position of a link in the hierarchy, from the roles of its two ends."""
    if "wan" in roles or "wan_gateway" in device_types:
        return "wan"
    if "server" in roles or "server" in device_types:
        return "server"
    if "access" in roles:
        return "access"
    if "distribution" in roles:
        return "distribution"
    return "core"


def static_features(capacities: np.ndarray, tiers: list[str]) -> np.ndarray:
    """(L, 1 + len(TIERS)): log10 capacity and one-hot tier."""
    out = np.zeros((len(capacities), 1 + len(TIERS)), dtype=np.float32)
    out[:, 0] = np.log10(np.maximum(capacities, 1.0))
    for i, tier in enumerate(tiers):
        out[i, 1 + TIERS.index(tier)] = 1.0
    return out


def fill_short_gaps(values: np.ndarray, max_gap: int = MAX_FILL_GAP) -> np.ndarray:
    """Forward-fill up to `max_gap` missing cycles after the last reading; beyond that, NaN.

    Vectorised (no loop over cycles): the live engine runs it over a 7-day buffer every cycle."""
    out = np.array(values, dtype=np.float32, copy=True)
    if out.size == 0:
        return out
    steps = np.arange(out.shape[0])[:, None]
    valid = ~np.isnan(out)
    last = np.maximum.accumulate(np.where(valid, steps, -1), axis=0)   # row of the latest reading so far
    fill = ~valid & (last >= 0) & (steps - last <= max_gap)
    rows, cols = np.nonzero(fill)
    out[rows, cols] = out[last[rows, cols], cols]
    return out


def _shifted(values: np.ndarray, rows: np.ndarray, offset: int) -> np.ndarray:
    """values[rows + offset], NaN where that index falls outside the array."""
    idx = rows + offset
    ok = (idx >= 0) & (idx < values.shape[0])
    out = np.full((len(rows), values.shape[1]), np.nan, dtype=np.float32)
    out[ok] = values[idx[ok]]
    return out


def _rolling(values: np.ndarray, rows: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean, standard deviation (population) and maximum over values[t-window+1 .. t]."""
    filled = np.nan_to_num(values, nan=0.0).astype(np.float64)
    present = (~np.isnan(values)).astype(np.float64)
    zero = np.zeros((1, values.shape[1]))
    c1 = np.vstack([zero, np.cumsum(filled, axis=0)])
    c2 = np.vstack([zero, np.cumsum(filled ** 2, axis=0)])
    cn = np.vstack([zero, np.cumsum(present, axis=0)])
    hi = rows + 1
    lo = np.maximum(rows + 1 - window, 0)
    count = cn[hi] - cn[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (c1[hi] - c1[lo]) / count
        var = np.maximum((c2[hi] - c2[lo]) / count - mean ** 2, 0.0)
    enough = (count >= max(2, window // 2)) & ((rows + 1 - window) >= 0)[:, None]
    mean = np.where(enough, mean, np.nan)
    std = np.where(enough, np.sqrt(var), np.nan)
    maximum = np.full((len(rows), values.shape[1]), np.nan)
    if values.shape[0] >= window:
        view = np.lib.stride_tricks.sliding_window_view(values, window, axis=0)  # (T-w+1, L, w)
        valid = rows - window + 1 >= 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            maximum[valid] = np.nanmax(view[rows[valid] - window + 1], axis=-1)
    maximum = np.where(enough, maximum, np.nan)
    return mean.astype(np.float32), std.astype(np.float32), maximum.astype(np.float32)


def _slope(values: np.ndarray, rows: np.ndarray, window: int = SLOPE_WINDOW) -> np.ndarray:
    """Least-squares slope (percentage points per cycle) over the last `window` cycles."""
    out = np.full((len(rows), values.shape[1]), np.nan, dtype=np.float32)
    if values.shape[0] < window:
        return out
    kernel = np.arange(window, dtype=np.float64) - (window - 1) / 2.0
    kernel /= (kernel ** 2).sum()
    view = np.lib.stride_tricks.sliding_window_view(values, window, axis=0)
    valid = rows - window + 1 >= 0
    out[valid] = (view[rows[valid] - window + 1] @ kernel).astype(np.float32)
    return out


def _calendar(epoch_seconds: np.ndarray) -> np.ndarray:
    local = epoch_seconds.astype(np.int64) + WAT_OFFSET_SECONDS
    hour = (local % 86400) / 3600.0
    dow = ((local // 86400) + 3) % 7                    # 1970-01-01 was a Thursday; Monday = 0
    return np.stack([np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),
                     np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7),
                     (dow >= 5).astype(np.float64)], axis=1).astype(np.float32)


def _reference_rows(times: np.ndarray, rows: np.ndarray, day_steps: int) -> np.ndarray:
    """Row at the same time on the previous day of the same type, per row (negative: not in the history)."""
    local = times[rows].astype(np.int64) + WAT_OFFSET_SECONDS
    dow = ((local // 86400) + 3) % 7                    # Monday = 0, as in _calendar
    return rows - np.asarray(SAME_TYPE_DAYS_BACK)[dow] * day_steps


def build_features(util: np.ndarray, times: np.ndarray, static: np.ndarray, errors: np.ndarray | None,
                   spec: FeatureSpec, rows: np.ndarray) -> np.ndarray:
    """Features for the given rows: array of shape (len(rows), L, F), float32.

    util, errors: (T, L) with NaN gaps (short gaps should already be filled).
    times: (T,) epoch seconds of each row. static: (L, S) from static_features().
    """
    rows = np.asarray(rows, dtype=np.int64)
    n, n_links = len(rows), util.shape[1]
    columns: list[np.ndarray] = [_shifted(util, rows, 0)]
    columns += [_shifted(util, rows, -k) for k in LAGS]
    for w in WINDOWS:
        columns += list(_rolling(util, rows, w))
    columns.append(_slope(util, rows, SLOPE_WINDOW))
    short_slope = _slope(util, rows, SHORT_SLOPE_WINDOW)
    columns.append(short_slope)
    now = columns[0]
    columns += [now + short_slope * step for step in spec.horizon_steps]
    if errors is None:
        columns.append(np.zeros((n, n_links), dtype=np.float32))
    else:
        err_sum = _rolling(np.nan_to_num(errors, nan=0.0).astype(np.float32), rows, ERROR_WINDOW)[0] * ERROR_WINDOW
        columns.append(np.log1p(np.maximum(np.nan_to_num(err_sum, nan=0.0), 0.0)).astype(np.float32))
    calendar = _calendar(times[rows])                    # (n, 5) same for every link
    columns += [np.repeat(calendar[:, j:j + 1], n_links, axis=1) for j in range(calendar.shape[1])]
    columns += [np.repeat(static[None, :, j], n, axis=0) for j in range(static.shape[1])]
    if spec.full:
        reference = _reference_rows(times, rows, spec.day_steps)
        known = (reference >= 0)[:, None]
        yesterday_now = np.where(known, _shifted(util, reference, 0), now)
        yesterday_later = [np.where(known, _shifted(util, reference, step), now) for step in spec.horizon_steps]
        columns.append(yesterday_now)
        columns += yesterday_later
        columns += [later - yesterday_now for later in yesterday_later]
        columns += [later - now for later in yesterday_later]
    return np.stack(columns, axis=2).astype(np.float32)


def build_targets(util: np.ndarray, rows: np.ndarray, spec: FeatureSpec) -> np.ndarray:
    """Targets for the given rows: utilisation at each horizon, shape (len(rows), L, H)."""
    rows = np.asarray(rows, dtype=np.int64)
    return np.stack([_shifted(util, rows, step) for step in spec.horizon_steps], axis=2)


def build_crossing_labels(util: np.ndarray, rows: np.ndarray, spec: FeatureSpec, critical: float) -> np.ndarray:
    """1 if the link reaches `critical` at ANY cycle in (t, t+h], else 0; NaN if unknown. Shape (n, L, H)."""
    rows = np.asarray(rows, dtype=np.int64)
    total = util.shape[0]
    out = np.full((len(rows), util.shape[1], len(spec.horizon_steps)), np.nan, dtype=np.float32)
    for j, step in enumerate(spec.horizon_steps):
        ok = rows + step < total
        if not ok.any():
            continue
        view = np.lib.stride_tricks.sliding_window_view(util, step, axis=0)   # window i covers util[i .. i+step-1]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            peak = np.nanmax(view[rows[ok] + 1], axis=-1)                     # util[t+1 .. t+step]
        labels = (peak >= critical).astype(np.float32)
        labels[np.isnan(peak)] = np.nan
        out[ok, :, j] = labels
    return out
