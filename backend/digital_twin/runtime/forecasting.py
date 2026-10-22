"""Forecasting in the running engine (Figure 3.4 process 4.0): history buffer, predictions, alerts.

Every stored cycle is added to an in-memory history buffer (reloaded from the
database at start-up), every link is forecast at every horizon, the forecasts are
stored (D3 Predictions), and alert episodes are updated with hysteresis (D22).
New trained models are picked up automatically when the registry changes.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import numpy as np

from data_collection.preprocessing import CleanBatch
from digital_twin.network_model import NetworkModel
from digital_twin.prediction_engine import (
    AlertTracker,
    Episode,
    Forecast,
    ForecastRow,
    HistoryBuffer,
    Predictor,
    link_tier,
    load_active,
    predicted_at,
    static_features,
)

from . import persistence

log = logging.getLogger("digital_twin.forecasting")
HISTORY_DAYS = 7          # the full model looks back up to 6 days (Saturday -> previous Sunday)


def link_static(model: NetworkModel, link_ids: list[int]) -> np.ndarray:
    """Static features (capacity and tier) for each link, from the current model."""
    capacities, tiers = [], []
    for link_id in link_ids:
        u, v = model.link_ends[link_id]
        nodes = (model.device(u), model.device(v))
        capacities.append(model.link(link_id)["capacity_mbps"])
        tiers.append(link_tier(tuple(str(n["configuration"].get("role", "")) for n in nodes),
                               tuple(n["device_type"] for n in nodes)))
    return static_features(np.array(capacities, dtype=float), tiers)


class ForecastService:
    def __init__(self, model: NetworkModel, *, cycle_seconds: int, critical_pct: float, warning_probability: float,
                 model_dir: str, clear_below_pct: float = 85.0, clear_cycles: int = 5):
        self.model_dir = model_dir
        self.cycle_seconds = cycle_seconds
        self.critical_pct = critical_pct
        self.warning_probability = warning_probability
        self.link_ids = sorted(model.link_ends)
        self.static = link_static(model, self.link_ids)
        capacity = HISTORY_DAYS * 86400 // cycle_seconds + 60
        self.buffer = HistoryBuffer(self.link_ids, cycle_seconds, capacity)
        self.tracker = AlertTracker(critical_pct, clear_below_pct, clear_cycles)
        self.last_rows: list[ForecastRow] = []
        self._registry_stamp: float | None = None
        self.predictor = self._load_models()

    # ----------------------------------------------------------- models
    def _active_file(self) -> Path:
        return Path(self.model_dir) / "active.json"

    def _load_models(self) -> Predictor:
        models = load_active(self.model_dir) if self._active_file().exists() else {}
        self._registry_stamp = self._active_file().stat().st_mtime if self._active_file().exists() else None
        if models:
            log.info("forecasting with %s", ", ".join(m.version for m in models.values()))
        else:
            log.warning("no trained model yet: run `manage.py train_models` once history exists")
        return Predictor(models, self.static, self.link_ids, self.critical_pct, self.warning_probability)

    def reload_if_changed(self) -> bool:
        stamp = self._active_file().stat().st_mtime if self._active_file().exists() else None
        if stamp != self._registry_stamp:
            self.predictor = self._load_models()
            return True
        return False

    def refresh_static(self, model: NetworkModel) -> None:
        """Capacities can change (configuration drift), so the static features follow the model."""
        self.static = link_static(model, self.link_ids)
        self.predictor.static = self.static

    # ---------------------------------------------------------- history
    def seed_from_database(self, until) -> int:
        since = until - timedelta(days=HISTORY_DAYS) if until else None
        times, util, errors = persistence.load_history(self.link_ids, self.cycle_seconds, since)
        for i in range(len(times)):
            moment = _utc(times[i])
            self.buffer.append(moment, dict(zip(self.link_ids, util[i].tolist(), strict=True)),
                               dict(zip(self.link_ids, errors[i].tolist(), strict=True)))
        return len(times)

    # ------------------------------------------------------------ cycle
    def on_cycle(self, clean: CleanBatch) -> tuple[list[ForecastRow], list[Episode], list[Episode]]:
        util = {link_id: r.utilisation_pct for link_id, r in clean.links.items()}
        errors = {link_id: (float(r.error_count) if r.error_count is not None else None)
                  for link_id, r in clean.links.items()}
        self.buffer.append(clean.timestamp, util, errors)
        rows = self.predictor.predict(self.buffer)
        if rows:
            persistence.write_predictions(rows)
        forecasts: dict[int, list[Forecast]] = {}
        for r in rows:
            forecasts.setdefault(r.link_id, []).append(
                Forecast(r.horizon_minutes, r.predicted_utilisation, r.confidence_score, r.is_warning))
        started, ended = self.tracker.update(clean.timestamp, forecasts, util)
        self.last_rows = rows
        return rows, started, ended

    def latest_forecast(self, horizon_minutes: int) -> dict[int, float] | None:
        return predicted_at(self.last_rows, horizon_minutes) or None

    def status(self) -> dict:
        return {**self.predictor.status(self.buffer),
                "active_alerts": [e.as_dict() for e in self.tracker.active.values()]}


def _utc(epoch: float):
    from datetime import UTC, datetime
    return datetime.fromtimestamp(float(epoch), UTC)
