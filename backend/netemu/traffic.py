"""Traffic demand model of the emulated campus network.

A demand is the traffic between one user-side device (an access switch or a
Wi-Fi access point) and one destination (a server, or the internet behind the
WAN gateways) for one traffic class. Its offered rate at time t is

    users(zone, access device) * activity(profile, t) * per_user_mbps(class)
    * zone multiplier(class) * growth(t) * scheduled events(t) * lab surges(t)
    * random noise(t)

System flows (for example the night-time offsite backup) are added on top.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from .topology import INTERNET, Topology

WAT = timezone(timedelta(hours=1), name="WAT")  # West Africa Time (no daylight saving)


@dataclass(frozen=True)
class Demand:
    index: int
    source: str        # user-side access device, or the source of a system flow
    dest: str          # a server device, or INTERNET
    cls: str
    zone: str | None   # None for system flows
    down_ratio: float  # share of the traffic flowing destination -> source


@dataclass
class Surge:
    """A temporary change in demand injected through the lab interface."""

    zone: str          # zone id or "*"
    cls: str           # class name or "*"
    multiplier: float
    start: datetime
    ramp: timedelta
    hold: timedelta

    @property
    def end(self) -> datetime:
        return self.start + self.ramp + self.hold + self.ramp


def trapezoid(t: datetime, start: datetime, end: datetime, ramp: timedelta) -> float:
    """0 outside [start, end], rising linearly over `ramp`, flat, then falling."""
    if t <= start or t >= end:
        return 0.0
    ramp_s = ramp.total_seconds()
    if ramp_s <= 0:
        return 1.0
    up = (t - start).total_seconds() / ramp_s
    down = (end - t).total_seconds() / ramp_s
    return max(0.0, min(1.0, up, down))


def interpolate(points: list[tuple[float, float]], hour: float) -> float:
    for (h0, v0), (h1, v1) in zip(points, points[1:], strict=False):
        if h0 <= hour <= h1:
            return v1 if h1 == h0 else v0 + (v1 - v0) * (hour - h0) / (h1 - h0)
    return points[-1][1]


def window_level(hour: float, windows, ramp_minutes: float) -> float:
    """Trapezoid level (0-1) of a set of daily hour windows at a given local hour."""
    ramp_h = ramp_minutes / 60.0
    level = 0.0
    for start, end in windows:
        if start < hour < end:
            if ramp_h <= 0:
                return 1.0
            level = max(level, min(1.0, (hour - start) / ramp_h, (end - hour) / ramp_h))
    return level


class TrafficModel:
    def __init__(self, topo: Topology, start: datetime, seed: int = 7):
        self.topo = topo
        self.start = start
        self.start_day = start.astimezone(WAT).date()
        self.rng = np.random.default_rng(seed)
        self.demands = self._build_demands()
        n = len(self.demands)
        self.down_ratio = np.array([d.down_ratio for d in self.demands])
        self.noise_state = np.zeros(n)
        self.surges: list[Surge] = []
        self.random_surges_enabled = topo.random_surges.enabled
        self._surge_days: set[int] = set()
        # Changes applied to the real network through the lab (used by evaluation E4).
        self.scale = np.ones(n)               # traffic_increase applied for real
        self.blocked = np.zeros(n, dtype=bool)  # access_control_rule applied for real
        self._precompute()

    def _schedule_random_surges(self, local: datetime) -> None:
        """Plan the day's unplanned flash crowds the first time the day is seen (deterministic per day)."""
        day = (local.date() - self.start_day).days
        if day in self._surge_days:
            return
        self._surge_days.add(day)
        cfg = self.topo.random_surges
        if not (self.random_surges_enabled and cfg.per_day > 0 and (cfg.templates or (cfg.zones and cfg.classes))):
            return
        rng = np.random.default_rng(cfg.seed * 1000 + day)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        weights = np.array([t.weight for t in cfg.templates], dtype=float)
        for _ in range(cfg.per_day):
            if cfg.templates:
                template = cfg.templates[int(rng.choice(len(cfg.templates), p=weights / weights.sum()))]
                zone, cls, hours, multiplier = template.zone, template.cls, template.hours, template.multiplier
            else:
                zone, cls = str(rng.choice(cfg.zones)), str(rng.choice(cfg.classes))
                hours, multiplier = cfg.hours, cfg.multiplier
            start = midnight + timedelta(hours=float(rng.uniform(*hours)))
            self.surges.append(Surge(
                zone=zone, cls=cls, multiplier=float(rng.uniform(*multiplier)), start=start,
                ramp=timedelta(minutes=float(rng.uniform(*cfg.ramp_minutes))),
                hold=timedelta(minutes=float(rng.uniform(*cfg.hold_minutes)))))

    # ------------------------------------------------------------------ setup
    def _build_demands(self) -> list[Demand]:
        exam = {(e.zone, e.cls) for e in self.topo.events if e.kind == "exam"}
        demands: list[Demand] = []
        for zone in self.topo.zones.values():
            for device in zone.access:
                for cls in self.topo.classes.values():
                    if cls.per_user_mbps <= 0 and (zone.id, cls.name) not in exam:
                        continue
                    dest = INTERNET if cls.dest == "internet" else cls.dest
                    demands.append(Demand(len(demands), device, dest, cls.name, zone.id, cls.down_ratio))
        for flow in self.topo.system_flows:
            dest = INTERNET if flow.dest == "internet" else flow.dest
            demands.append(Demand(len(demands), flow.source, dest, flow.cls, None, flow.down_ratio))
        return demands

    def _precompute(self) -> None:
        topo = self.topo
        n = len(self.demands)
        self.zone_ids = list(topo.zones)
        self.users = np.zeros(n)
        self.base = np.zeros(n)          # users * per-user rate * zone multiplier
        self.zone_index = np.full(n, -1)
        self.system_mbps = np.zeros(n)
        self.system_hours: list[tuple[int, tuple[float, float]]] = []
        for d in self.demands:
            if d.zone is None:
                flow = next(f for f in topo.system_flows if f.source == d.source and f.cls == d.cls)
                self.system_mbps[d.index] = flow.mbps
                self.system_hours.append((d.index, flow.hours))
                continue
            zone = topo.zones[d.zone]
            cls = topo.classes[d.cls]
            users = zone.population * zone.access[d.source]
            self.users[d.index] = users
            self.base[d.index] = users * cls.per_user_mbps * zone.multipliers.get(d.cls, 1.0)
            self.zone_index[d.index] = self.zone_ids.index(d.zone)
        self.event_masks = []
        for event in topo.events:
            mask = np.array([
                d.zone is not None and (event.zone in ("*", d.zone)) and d.cls == event.cls
                for d in self.demands
            ])
            self.event_masks.append((event, mask))

    # ------------------------------------------------------------- per step
    def mask(self, zone: str = "*", cls: str = "*", source: str = "*", dest: str = "*") -> np.ndarray:
        return np.array([
            (zone == "*" or d.zone == zone)
            and (cls == "*" or d.cls == cls)
            and (source == "*" or d.source == source)
            and (dest == "*" or d.dest == dest)
            for d in self.demands
        ])

    def _advance_noise(self, dt_seconds: float) -> np.ndarray:
        gap = self.topo.reality_gap
        phi = gap.noise_phi ** (dt_seconds / 60.0)
        sigma_step = gap.noise_sigma * math.sqrt(max(0.0, 1.0 - phi * phi))
        self.noise_state = phi * self.noise_state + sigma_step * self.rng.standard_normal(len(self.demands))
        return np.exp(self.noise_state - 0.5 * gap.noise_sigma ** 2)

    def _day_matches(self, days, local: datetime) -> bool:
        if days == "all":
            return True
        if days == "weekdays":
            return local.weekday() < 5
        return (local.date() - self.start_day).days in days

    def offered(self, t: datetime, dt_seconds: float) -> np.ndarray:
        """Offered rate in Mbps (both directions together) of every demand at time t."""
        local = t.astimezone(WAT)
        self._schedule_random_surges(local)
        hour = local.hour + local.minute / 60.0 + local.second / 3600.0
        day_type = "weekend" if local.weekday() >= 5 else "weekday"
        activity = np.array([
            interpolate(self.topo.profiles[self.topo.zones[z].profile][day_type], hour)
            for z in self.zone_ids
        ])
        rates = np.where(self.zone_index >= 0, self.base * activity[np.maximum(self.zone_index, 0)], 0.0)

        for event, mask in self.event_masks:
            if not self._day_matches(event.days, local):
                continue
            level = window_level(hour, event.windows, event.ramp_minutes)
            if level <= 0:
                continue
            if event.kind == "exam":
                rates = rates + np.where(mask, self.users * event.per_user_mbps * level, 0.0)
            else:
                rates = np.where(mask, rates * (1.0 + (event.multiplier - 1.0) * level), rates)

        for index, (start_h, end_h) in self.system_hours:
            if start_h <= hour < end_h:
                rates[index] += self.system_mbps[index]

        for surge in self.surges:
            level = trapezoid(t, surge.start, surge.end, surge.ramp)
            if level > 0:
                rates = np.where(self.mask(surge.zone, surge.cls), rates * (1.0 + (surge.multiplier - 1.0) * level), rates)
        self.surges = [s for s in self.surges if s.end > t]

        elapsed_weeks = max(0.0, (t - self.start).total_seconds()) / (7 * 86400)
        growth = (1.0 + self.topo.growth_per_week) ** elapsed_weeks
        rates = rates * growth * self._advance_noise(dt_seconds) * self.scale
        rates[self.blocked] = 0.0
        return rates
