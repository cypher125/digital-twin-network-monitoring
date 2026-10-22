"""Live forecasting every cycle (Figure 3.4 process 4.0, FR3, gap G2).

HistoryBuffer keeps the recent history of every link in memory (reloaded from the
database at start-up). Predictor forecasts every link at every horizon, with the
full model once a day of history exists, otherwise the short-history model (D6).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from .features import SHORT_HISTORY, build_features, fill_short_gaps
from .registry import LoadedModel


@dataclass(frozen=True)
class ForecastRow:
    link_id: int
    generated_at: datetime
    horizon_minutes: int
    predicted_utilisation: float
    confidence_score: float
    is_warning: bool
    model_version: str


class HistoryBuffer:
    """The last `capacity` cycles of utilisation and errors per link, in time order."""

    def __init__(self, link_ids: list[int], cycle_seconds: int, capacity: int):
        self.link_ids = list(link_ids)
        self.column = {link_id: i for i, link_id in enumerate(self.link_ids)}
        self.cycle_seconds = cycle_seconds
        self.capacity = capacity
        self.times = np.zeros(capacity, dtype=np.float64)
        self.util = np.full((capacity, len(self.link_ids)), np.nan, dtype=np.float32)
        self.errors = np.full((capacity, len(self.link_ids)), np.nan, dtype=np.float32)
        self.size = 0

    @property
    def last_time(self) -> float | None:
        return float(self.times[self.size - 1]) if self.size else None

    def _push(self, epoch: float, util_row: np.ndarray, error_row: np.ndarray) -> None:
        if self.size == self.capacity:
            self.times[:-1] = self.times[1:]
            self.util[:-1] = self.util[1:]
            self.errors[:-1] = self.errors[1:]
            self.size -= 1
        self.times[self.size] = epoch
        self.util[self.size] = util_row
        self.errors[self.size] = error_row
        self.size += 1

    def append(self, moment: datetime, util: dict[int, float | None], errors: dict[int, float | None]) -> bool:
        """Add one cycle. Missing cycles in between are filled with gaps, so lags stay aligned in time."""
        epoch = moment.timestamp()
        if self.size:
            steps = round((epoch - self.last_time) / self.cycle_seconds)
            if steps <= 0:
                return False
            empty = np.full(len(self.link_ids), np.nan, dtype=np.float32)
            for _missed in range(1, min(steps, self.capacity)):
                self._push(self.last_time + self.cycle_seconds, empty, empty)
        util_row = np.full(len(self.link_ids), np.nan, dtype=np.float32)
        error_row = np.full(len(self.link_ids), np.nan, dtype=np.float32)
        for link_id, value in util.items():
            if link_id in self.column and value is not None:
                util_row[self.column[link_id]] = value
        for link_id, value in errors.items():
            if link_id in self.column and value is not None:
                error_row[self.column[link_id]] = value
        self._push(epoch, util_row, error_row)
        return True

    def arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.times[:self.size], self.util[:self.size], self.errors[:self.size]


class Predictor:
    """Forecasts every link at every horizon.

    predicted_utilisation comes from the regression forest. For a link below the
    critical threshold, is_warning and confidence come from the classification forest:
    warning when P(reaching the threshold within h) >= the threshold chosen at training
    time on a validation slice (warning_probability for models saved without one), with
    confidence = that probability (or 1 - P when there is no warning). A link already
    at or above the threshold is "critical now": its warning follows the regression
    forecast, with confidence = share of regression trees agreeing (D5).
    """

    def __init__(self, models: dict[str, LoadedModel], static: np.ndarray, link_ids: list[int], critical_pct: float,
                 warning_probability: float = 0.5):
        self.models = models
        self.static = static
        self.link_ids = list(link_ids)
        self.critical_pct = critical_pct
        self.warning_probability = warning_probability

    def choose(self, history_cycles: int) -> LoadedModel | None:
        full, short = self.models.get("full"), self.models.get("short")
        if full and history_cycles > full.spec.needed_history:
            return full
        if short and history_cycles > SHORT_HISTORY:
            return short
        return None

    def status(self, buffer: HistoryBuffer) -> dict:
        model = self.choose(buffer.size)
        return {
            "active_model": model.version if model else None,
            "model_kind": model.kind if model else None,
            "history_cycles": buffer.size,
            "short_model_needs": SHORT_HISTORY,
            "full_model_needs": self.models["full"].spec.needed_history if "full" in self.models else None,
            "available": sorted(m.version for m in self.models.values()),
        }

    def predict(self, buffer: HistoryBuffer) -> list[ForecastRow]:
        model = self.choose(buffer.size)
        if model is None or buffer.size == 0:
            return []
        if model.link_ids != buffer.link_ids:
            # topology changed since training: forecast only the links the model knows
            known = [buffer.column[i] for i in model.link_ids if i in buffer.column]
        else:
            known = list(range(len(buffer.link_ids)))
        times, util, errors = buffer.arrays()
        util = fill_short_gaps(util)
        rows = np.array([buffer.size - 1])
        X = build_features(util[:, known], times, self.static[known], errors[:, known], model.spec, rows)[0]
        mean, tree_agreement = model.forest.predict_with_confidence(X, self.critical_pct)
        critical_now = (np.nan_to_num(X[:, 0], nan=0.0) >= self.critical_pct)[:, None]
        warning = mean >= self.critical_pct
        confidence = tree_agreement
        if model.classifier is not None:
            risk = model.classifier.probability(X)
            risky = risk >= getattr(model.classifier, "threshold", self.warning_probability)
            warning = np.where(critical_now, warning, risky)
            confidence = np.where(critical_now, tree_agreement, np.where(risky, risk, 1.0 - risk))
        generated = datetime.fromtimestamp(times[-1], UTC)
        out = []
        for row, column in enumerate(known):
            if np.isnan(X[row, 0]):
                continue                                  # no current reading for this link
            link_id = buffer.link_ids[column]
            for j, horizon in enumerate(model.spec.horizons_minutes):
                out.append(ForecastRow(link_id, generated, horizon, round(float(mean[row, j]), 3),
                                       round(float(confidence[row, j]), 4), bool(warning[row, j]),
                                       model.version))
        return out


def predicted_at(rows: list[ForecastRow], horizon_minutes: int) -> dict[int, float]:
    return {r.link_id: r.predicted_utilisation for r in rows if r.horizon_minutes == horizon_minutes}


def problem_time(rows: list[ForecastRow]) -> datetime | None:
    warnings = [r for r in rows if r.is_warning]
    if not warnings:
        return None
    first = min(warnings, key=lambda r: r.horizon_minutes)
    return first.generated_at + timedelta(minutes=first.horizon_minutes)
