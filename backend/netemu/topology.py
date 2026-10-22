"""Load and validate the topology and traffic description used by the emulator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

INTERNET = "INTERNET"  # virtual destination behind the WAN gateways
DAY_TYPES = ("weekday", "weekend")


class TopologyError(ValueError):
    """The topology file is inconsistent."""


@dataclass(frozen=True)
class Device:
    name: str
    type: str
    role: str
    zone: str
    ip: str
    location: str
    position: tuple[float, float]
    internet_egress: bool = False


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    capacity_mbps: float
    cost: float | None = None


@dataclass(frozen=True)
class TrafficClass:
    name: str
    per_user_mbps: float
    dest: str          # "internet" or a server device name
    down_ratio: float  # share of the traffic that flows destination -> user


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    population: int
    profile: str
    access: dict[str, float]       # access device -> share of the zone's users
    multipliers: dict[str, float]  # class -> zone-specific multiplier


@dataclass(frozen=True)
class SystemFlow:
    name: str
    source: str
    dest: str
    cls: str
    mbps: float
    down_ratio: float
    hours: tuple[float, float]


@dataclass(frozen=True)
class ScheduledEvent:
    name: str
    kind: str                     # "exam": sets a per-user rate; "surge": multiplies demand
    zone: str                     # zone id or "*"
    cls: str
    per_user_mbps: float
    multiplier: float
    days: str | tuple[int, ...]   # "weekdays", "all", or day numbers counted from the start date
    windows: tuple[tuple[float, float], ...]
    ramp_minutes: float


@dataclass(frozen=True)
class FaultConfig:
    enabled: bool = True
    link_mtbf_hours: float = 1500.0
    link_mttr_minutes: float = 20.0
    device_mtbf_hours: float = 3000.0
    device_mttr_minutes: float = 8.0


@dataclass(frozen=True)
class DataQualityConfig:
    missing_sample_prob: float = 0.0
    spike_prob: float = 0.0


@dataclass(frozen=True)
class RealityGapConfig:
    ecmp_imbalance: float = 0.0
    overhead_pct: float = 0.0
    noise_sigma: float = 0.08
    noise_phi: float = 0.90
    flow_sampling: int = 1             # NetFlow-style 1:N packet sampling (1 = every packet)
    flow_export_delay_cycles: int = 0  # flow records become available this many cycles late


REALITY_GAP_PRESETS = {
    # sanity check: the emulator and the twin agree except for random noise
    "off": {"ecmp_imbalance": 0.0, "overhead_pct": 0.0, "flow_sampling": 1, "flow_export_delay_cycles": 0},
    # the defaults in campus.yaml
    "default": {},
    # a harder test of the twin
    "high": {"ecmp_imbalance": 0.25, "overhead_pct": 5.0, "flow_sampling": 1000, "flow_export_delay_cycles": 2},
}


@dataclass(frozen=True)
class SurgeTemplate:
    """One kind of flash crowd: where, what traffic, at what time of day, and how big."""

    zone: str
    cls: str
    hours: tuple[float, float]
    multiplier: tuple[float, float]
    weight: float = 1.0


@dataclass(frozen=True)
class RandomSurgeConfig:
    """Unplanned flash crowds (e.g. a live football match), a few per day, reproducible by seed.

    With templates, each surge picks a template by weight; otherwise zone, class and
    hour are drawn uniformly from the lists below."""

    enabled: bool = False
    per_day: int = 0
    multiplier: tuple[float, float] = (1.5, 2.0)
    ramp_minutes: tuple[float, float] = (10.0, 30.0)
    hold_minutes: tuple[float, float] = (15.0, 45.0)
    hours: tuple[float, float] = (9.0, 23.0)
    zones: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    templates: tuple[SurgeTemplate, ...] = ()
    seed: int = 11


@dataclass
class Topology:
    name: str
    reference_bandwidth_mbps: float
    growth_per_week: float
    devices: dict[str, Device]
    links: list[Link]
    classes: dict[str, TrafficClass]
    zones: dict[str, Zone]
    profiles: dict[str, dict[str, list[tuple[float, float]]]]
    system_flows: list[SystemFlow]
    events: list[ScheduledEvent]
    faults: FaultConfig
    data_quality: DataQualityConfig
    reality_gap: RealityGapConfig
    random_surges: RandomSurgeConfig = RandomSurgeConfig()

    @property
    def egress_devices(self) -> list[str]:
        return [d.name for d in self.devices.values() if d.internet_egress]

    def link_cost(self, link: Link) -> float:
        if link.cost is not None:
            return link.cost
        return self.reference_bandwidth_mbps / link.capacity_mbps


def load_topology(path: str | Path) -> Topology:
    with open(path, encoding="utf-8") as fh:
        return parse_topology(yaml.safe_load(fh))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TopologyError(message)


def parse_topology(raw: dict) -> Topology:
    devices: dict[str, Device] = {}
    for d in raw.get("devices", []):
        name = d["name"]
        _require(name not in devices, f"duplicate device {name}")
        x, y = d.get("position", (0, 0))
        devices[name] = Device(
            name=name,
            type=d["type"],
            role=d.get("role", ""),
            zone=d.get("zone", ""),
            ip=str(d.get("ip", "")),
            location=d.get("location", ""),
            position=(float(x), float(y)),
            internet_egress=bool(d.get("internet_egress", False)),
        )

    links: list[Link] = []
    pairs: set[frozenset[str]] = set()
    for entry in raw.get("links", []):
        a, b, capacity = entry[0], entry[1], float(entry[2])
        cost = float(entry[3]) if len(entry) > 3 and entry[3] is not None else None
        _require(a in devices and b in devices, f"link {a}-{b} refers to an unknown device")
        _require(a != b, f"link {a}-{b} connects a device to itself")
        _require(capacity > 0, f"link {a}-{b} must have a positive capacity")
        pair = frozenset((a, b))
        _require(pair not in pairs, f"duplicate link {a}-{b}")
        pairs.add(pair)
        links.append(Link(a, b, capacity, cost))

    classes: dict[str, TrafficClass] = {}
    for name, c in raw.get("classes", {}).items():
        dest = c["dest"]
        _require(dest == "internet" or dest in devices, f"class {name} has unknown destination {dest}")
        classes[name] = TrafficClass(name, float(c["per_user_mbps"]), dest, float(c["down_ratio"]))

    profiles: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for name, p in raw.get("profiles", {}).items():
        profiles[name] = {}
        for day_type in DAY_TYPES:
            _require(day_type in p, f"profile {name} needs a {day_type} curve")
            points = sorted((float(h), float(v)) for h, v in p[day_type])
            _require(points[0][0] == 0 and points[-1][0] == 24, f"profile {name}/{day_type} must span hours 0-24")
            profiles[name][day_type] = points

    zones: dict[str, Zone] = {}
    for zone_id, z in raw.get("zones", {}).items():
        access = {k: float(v) for k, v in z.get("access", {}).items()}
        for device in access:
            _require(device in devices, f"zone {zone_id} uses unknown access device {device}")
        _require(abs(sum(access.values()) - 1.0) < 1e-6, f"zone {zone_id} access shares must add up to 1")
        _require(z["profile"] in profiles, f"zone {zone_id} uses unknown profile {z['profile']}")
        multipliers = {k: float(v) for k, v in (z.get("multipliers") or {}).items()}
        for cls in multipliers:
            _require(cls in classes, f"zone {zone_id} has a multiplier for unknown class {cls}")
        zones[zone_id] = Zone(zone_id, z.get("name", zone_id), int(z["population"]), z["profile"], access, multipliers)

    system_flows = []
    for f in raw.get("system_flows", []):
        _require(f["source"] in devices, f"system flow {f['name']} has unknown source")
        _require(f["dest"] == "internet" or f["dest"] in devices, f"system flow {f['name']} has unknown destination")
        start_h, end_h = f["hours"]
        system_flows.append(
            SystemFlow(f["name"], f["source"], f["dest"], f["class"], float(f["mbps"]),
                       float(f.get("down_ratio", 0.5)), (float(start_h), float(end_h)))
        )

    events = []
    for e in raw.get("events", []):
        _require(e["kind"] in {"exam", "surge"}, f"event {e['name']} has unknown kind {e['kind']}")
        _require(e["zone"] == "*" or e["zone"] in zones, f"event {e['name']} has unknown zone")
        _require(e["class"] in classes, f"event {e['name']} has unknown class")
        days = e.get("days", "all")
        events.append(
            ScheduledEvent(
                name=e["name"],
                kind=e["kind"],
                zone=e["zone"],
                cls=e["class"],
                per_user_mbps=float(e.get("per_user_mbps", 0.0)),
                multiplier=float(e.get("multiplier", 1.0)),
                days=days if isinstance(days, str) else tuple(int(x) for x in days),
                windows=tuple((float(a), float(b)) for a, b in e["windows"]),
                ramp_minutes=float(e.get("ramp_minutes", 0)),
            )
        )

    surges_raw = dict(raw.get("random_surges") or {})
    for key in ("multiplier", "ramp_minutes", "hold_minutes", "hours"):
        if key in surges_raw:
            low, high = surges_raw[key]
            surges_raw[key] = (float(low), float(high))
    for key in ("zones", "classes"):
        if key in surges_raw:
            surges_raw[key] = tuple(surges_raw[key])
    templates = []
    for t in surges_raw.pop("templates", None) or []:
        templates.append(SurgeTemplate(zone=t["zone"], cls=t["class"],
                                       hours=(float(t["hours"][0]), float(t["hours"][1])),
                                       multiplier=(float(t["multiplier"][0]), float(t["multiplier"][1])),
                                       weight=float(t.get("weight", 1.0))))
    random_surges = RandomSurgeConfig(**surges_raw, templates=tuple(templates))
    for zone in list(random_surges.zones) + [t.zone for t in templates]:
        _require(zone in zones, f"random_surges uses unknown zone {zone}")
    for cls in list(random_surges.classes) + [t.cls for t in templates]:
        _require(cls in classes, f"random_surges uses unknown class {cls}")

    return Topology(
        name=raw.get("name", "network"),
        reference_bandwidth_mbps=float(raw.get("reference_bandwidth_mbps", 10000)),
        growth_per_week=float(raw.get("growth_per_week", 0.0)),
        devices=devices,
        links=links,
        classes=classes,
        zones=zones,
        profiles=profiles,
        system_flows=system_flows,
        events=events,
        faults=FaultConfig(**(raw.get("faults") or {})),
        data_quality=DataQualityConfig(**(raw.get("data_quality") or {})),
        reality_gap=RealityGapConfig(**(raw.get("reality_gap") or {})),
        random_surges=random_surges,
    )


def with_reality_gap(topo: Topology, preset: str) -> Topology:
    """A copy of the topology with one of REALITY_GAP_PRESETS applied (evaluation E1/E4)."""
    from dataclasses import replace

    if preset not in REALITY_GAP_PRESETS:
        raise TopologyError(f"unknown reality-gap preset {preset}; use one of {sorted(REALITY_GAP_PRESETS)}")
    return replace(topo, reality_gap=replace(topo.reality_gap, **REALITY_GAP_PRESETS[preset]))
