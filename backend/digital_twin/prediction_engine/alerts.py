"""Alert episodes with hysteresis (UC2, plan decision D22).

An episode starts when any horizon of a link's forecast is a warning (>= critical).
It ends only after `clear_cycles` consecutive cycles in which every horizon, and
the current utilisation, are below `clear_below_pct`, so an alert hovering near the
threshold does not flap on and off. The same tracker rebuilds alert history from
stored Prediction rows, so live alerts and history always agree.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Episode:
    link_id: int
    started_at: datetime
    last_warning_at: datetime
    predicted_time: datetime          # generated_at + earliest warning horizon
    horizon_minutes: int
    confidence: float
    peak_predicted: float
    critical_now: bool                # already at or above critical when last updated
    ended_at: datetime | None = None
    new: bool = True                  # started in this update

    def as_dict(self) -> dict:
        return {
            "link_id": self.link_id,
            "started_at": self.started_at.isoformat(),
            "last_warning_at": self.last_warning_at.isoformat(),
            "predicted_time": self.predicted_time.isoformat(),
            "horizon_minutes": self.horizon_minutes,
            "confidence": round(self.confidence, 3),
            "peak_predicted": round(self.peak_predicted, 1),
            "critical_now": self.critical_now,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


@dataclass(frozen=True)
class Forecast:
    horizon_minutes: int
    predicted: float
    confidence: float
    is_warning: bool


@dataclass
class AlertTracker:
    critical_pct: float = 90.0
    clear_below_pct: float = 85.0
    clear_cycles: int = 5
    active: dict[int, Episode] = field(default_factory=dict)
    quiet: dict[int, int] = field(default_factory=dict)

    def update(self, generated_at: datetime, forecasts: dict[int, list[Forecast]],
               current: dict[int, float | None]) -> tuple[list[Episode], list[Episode]]:
        """Process one cycle of forecasts. Returns (episodes started, episodes ended)."""
        started, ended = [], []
        for episode in self.active.values():
            episode.new = False
        for link_id, items in forecasts.items():
            warnings = [f for f in items if f.is_warning]
            now = current.get(link_id)
            if warnings:
                first = min(warnings, key=lambda f: f.horizon_minutes)
                episode = self.active.get(link_id)
                if episode is None:
                    episode = Episode(link_id, generated_at, generated_at,
                                      generated_at + timedelta(minutes=first.horizon_minutes),
                                      first.horizon_minutes, first.confidence, first.predicted, False)
                    self.active[link_id] = episode
                    started.append(episode)
                episode.last_warning_at = generated_at
                episode.predicted_time = generated_at + timedelta(minutes=first.horizon_minutes)
                episode.horizon_minutes = first.horizon_minutes
                episode.confidence = first.confidence
                episode.peak_predicted = max(episode.peak_predicted, max(f.predicted for f in warnings))
                episode.critical_now = now is not None and now >= self.critical_pct
                self.quiet[link_id] = 0
            elif link_id in self.active:
                calm = all(f.predicted < self.clear_below_pct for f in items) and (now is None or now < self.clear_below_pct)
                self.quiet[link_id] = self.quiet.get(link_id, 0) + 1 if calm else 0
                if self.quiet[link_id] >= self.clear_cycles:
                    episode = self.active.pop(link_id)
                    episode.ended_at = generated_at
                    ended.append(episode)
                    self.quiet.pop(link_id, None)
        return started, ended


def replay(rows: Iterable[tuple[int, datetime, int, float, float, bool]], current: dict | None = None,
           **settings) -> tuple[list[Episode], list[Episode]]:
    """Rebuild episodes from stored predictions: rows of (link_id, generated_at, horizon, predicted,
    confidence, is_warning), in any order. Returns (all ended episodes, still-active episodes)."""
    by_time: dict[datetime, dict[int, list[Forecast]]] = {}
    for link_id, generated_at, horizon, predicted, confidence, warning in rows:
        by_time.setdefault(generated_at, {}).setdefault(link_id, []).append(
            Forecast(horizon, predicted, confidence, warning))
    tracker = AlertTracker(**settings)
    finished: list[Episode] = []
    for generated_at in sorted(by_time):
        _, ended = tracker.update(generated_at, by_time[generated_at], current or {})
        finished.extend(ended)
    return finished, list(tracker.active.values())
