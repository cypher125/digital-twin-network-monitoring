"""A read-only index of the known topology (from the Topology Store, D1), used to map raw data to IDs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceRef:
    device_id: int
    name: str
    device_type: str
    internet_egress: bool = False


@dataclass(frozen=True)
class LinkRef:
    link_id: int
    source: str          # device name of NetworkLink.source_device
    dest: str            # device name of NetworkLink.dest_device
    capacity_mbps: float
    routing_cost: float | None = None


@dataclass
class TopologyIndex:
    devices: dict[str, DeviceRef]
    links: dict[int, LinkRef]
    _by_pair: dict[frozenset[str], LinkRef] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_pair = {frozenset((lk.source, lk.dest)): lk for lk in self.links.values()}

    def link_between(self, a: str, b: str) -> LinkRef | None:
        return self._by_pair.get(frozenset((a, b)))

    def set_capacity(self, link_id: int, capacity_mbps: float) -> LinkRef:
        """Adopt a capacity change reported by the devices (configuration drift)."""
        old = self.links[link_id]
        new = LinkRef(old.link_id, old.source, old.dest, capacity_mbps, old.routing_cost)
        self.links[link_id] = new
        self._by_pair[frozenset((new.source, new.dest))] = new
        return new

    def device_by_id(self, device_id: int) -> DeviceRef | None:
        return next((d for d in self.devices.values() if d.device_id == device_id), None)

    def incident_links(self, device: str) -> list[LinkRef]:
        return [lk for lk in self.links.values() if device in (lk.source, lk.dest)]
