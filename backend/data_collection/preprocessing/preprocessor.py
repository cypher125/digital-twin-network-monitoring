"""Validate, clean and normalise raw monitoring data (write-up section 3.6).

* Required fields and known devices are checked; unknown elements are rejected.
* Cumulative byte counters become rates: Mbps = delta_octets * 8 / delta_t / 10**6.
* Utilisation = max(traffic_in, traffic_out) / capacity * 100 (the busier direction).
* A counter that goes backwards (device rebooted) starts a new baseline: that
  interval is dropped and counted as a counter reset.
* A rate above the interface speed (+5 %) is a bogus reading: it is rejected and
  the previous good reading is kept, so the next poll measures over both intervals.
* Utilisation slightly above 100 % (up to 105 %) is clipped to 100 % and flagged.
* Timestamps are checked against the data source's own clock: never earlier than
  the last cycle (D26). Polling the same cycle twice is ignored.
* If the devices report an interface speed different from the stored link
  capacity (the link was upgraded or downgraded), the new capacity is adopted
  and reported, so the replica's configuration stays in step with the network.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from ..raw import RawBatch
from .topology import TopologyIndex

COUNTER64 = 2 ** 64
COUNTER32 = 2 ** 32
SPIKE_FACTOR = 1.05      # a rate above 105 % of the interface speed is impossible
CLIP_LIMIT_PCT = 105.0   # utilisation between 100 % and this is clipped to 100 %
CAPACITY_TOLERANCE = 0.01  # reported speed differing by more than 1 % is a capacity change


class ClockWentBackwards(RuntimeError):
    """The data source reported a time earlier than data already stored."""


def align_to_cycle(moment: datetime, cycle_seconds: int) -> datetime:
    epoch = moment.timestamp()
    return datetime.fromtimestamp(epoch - (epoch % cycle_seconds), UTC)


def counter_delta(previous: int, current: int, modulus: int) -> int | None:
    """Increase of a cumulative counter, allowing for wrap-around. None means it was reset."""
    if current >= previous:
        return current - previous
    if previous > modulus // 2:          # close to the top: a genuine wrap-around
        return current + modulus - previous
    return None                          # dropped sharply: the counter was reset


@dataclass
class LinkReading:
    link_id: int
    status: str                          # up, down or unknown
    traffic_out: float | None = None     # Mbps, source -> destination
    traffic_in: float | None = None      # Mbps, destination -> source
    utilisation_pct: float | None = None
    error_count: int | None = None


@dataclass
class DeviceReading:
    device_id: int
    status: str
    cpu_util: float | None = None
    traffic_in: float | None = None
    traffic_out: float | None = None
    error_count: int | None = None


@dataclass(frozen=True)
class DemandReading:
    source_id: int
    dest_id: int | None                  # None means the internet
    cls: str
    mbps: float                          # both directions together
    down_ratio: float                    # share flowing destination -> source


@dataclass
class QualityReport:
    interfaces_expected: int = 0
    interfaces_received: int = 0
    interfaces_missing: int = 0
    spikes_rejected: int = 0
    counter_resets: int = 0
    utilisation_clipped: int = 0
    links_without_rate: int = 0
    unknown_elements: int = 0
    cpu_rejected: int = 0
    flows_rejected: int = 0
    capacity_changes: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CleanBatch:
    timestamp: datetime                  # cycle the readings belong to (network time)
    measured_at: datetime
    received_at: datetime
    interval_seconds: float | None
    links: dict[int, LinkReading]
    devices: dict[int, DeviceReading]
    demands: list[DemandReading] | None  # None when the batch carried no flow records
    quality: QualityReport = field(default_factory=QualityReport)
    capacity_changes: dict[int, float] = field(default_factory=dict)  # link_id -> new capacity (Mbps)


@dataclass
class _Previous:
    at: datetime
    in_octets: int
    out_octets: int
    in_errors: int


class Preprocessor:
    def __init__(self, topology: TopologyIndex, cycle_seconds: int, last_timestamp: datetime | None = None):
        self.topology = topology
        self.cycle_seconds = cycle_seconds
        self.last_timestamp = last_timestamp
        self._previous: dict[tuple[str, int], _Previous] = {}
        self._uptime: dict[str, int] = {}
        self._last_measured: datetime | None = None

    def process(self, batch: RawBatch) -> CleanBatch | None:
        timestamp = align_to_cycle(batch.measured_at, self.cycle_seconds)
        if self.last_timestamp is not None:
            if timestamp < self.last_timestamp:
                raise ClockWentBackwards(
                    f"data source time {timestamp.isoformat()} is earlier than the stored "
                    f"{self.last_timestamp.isoformat()}")
            if timestamp == self.last_timestamp:
                return None  # the same cycle polled twice
        quality = QualityReport()
        interval = ((batch.measured_at - self._last_measured).total_seconds()
                    if self._last_measured else None)

        rates: dict[tuple[str, int], tuple[float, float, int]] = {}
        oper: dict[tuple[str, str], bool] = {}          # (device, peer) -> interface up?
        by_peer: dict[tuple[str, str], int] = {}        # (device, peer) -> ifIndex
        speeds: dict[tuple[str, str], float] = {}       # (device, peer) -> reported speed (Mbps)
        reachable: dict[str, bool] = {}
        cpu: dict[str, float | None] = {}

        for device in batch.devices:
            ref = self.topology.devices.get(device.device)
            if ref is None:
                quality.unknown_elements += 1
                continue
            reachable[device.device] = device.reachable
            if not device.reachable:
                continue
            expected = len(self.topology.incident_links(device.device))
            quality.interfaces_expected += expected
            quality.interfaces_received += len(device.interfaces)
            quality.interfaces_missing += max(0, expected - len(device.interfaces))

            previous_uptime = self._uptime.get(device.device)
            if (previous_uptime is not None and device.uptime_ticks is not None
                    and device.uptime_ticks < previous_uptime):
                quality.counter_resets += 1
                for key in [k for k in self._previous if k[0] == device.device]:
                    del self._previous[key]
            if device.uptime_ticks is not None:
                self._uptime[device.device] = device.uptime_ticks

            if device.cpu_pct is None or not 0.0 <= device.cpu_pct <= 100.0:
                quality.cpu_rejected += device.cpu_pct is not None
                cpu[device.device] = None
            else:
                cpu[device.device] = device.cpu_pct

            for sample in device.interfaces:
                if self.topology.link_between(sample.device, sample.peer) is None:
                    quality.unknown_elements += 1
                    continue
                key = (sample.device, sample.if_index)
                by_peer[(sample.device, sample.peer)] = sample.if_index
                oper[(sample.device, sample.peer)] = sample.oper_up
                if sample.speed_mbps > 0:
                    speeds[(sample.device, sample.peer)] = sample.speed_mbps
                current = _Previous(batch.measured_at, sample.in_octets, sample.out_octets, sample.in_errors)
                previous = self._previous.get(key)
                if previous is None:
                    self._previous[key] = current
                    continue
                dt = (batch.measured_at - previous.at).total_seconds()
                if dt <= 0:
                    continue
                d_in = counter_delta(previous.in_octets, sample.in_octets, COUNTER64)
                d_out = counter_delta(previous.out_octets, sample.out_octets, COUNTER64)
                d_err = counter_delta(previous.in_errors, sample.in_errors, COUNTER32)
                if d_in is None or d_out is None:
                    quality.counter_resets += 1
                    self._previous[key] = current
                    continue
                rate_in = d_in * 8 / dt / 1e6
                rate_out = d_out * 8 / dt / 1e6
                limit = sample.speed_mbps * SPIKE_FACTOR
                if rate_in > limit or rate_out > limit:
                    quality.spikes_rejected += 1
                    continue  # keep the previous good reading as the baseline
                self._previous[key] = current
                rates[key] = (rate_in, rate_out, d_err or 0)

        capacity_changes: dict[int, float] = {}
        for link in list(self.topology.links.values()):
            reported = speeds.get((link.source, link.dest)) or speeds.get((link.dest, link.source))
            if reported and abs(reported - link.capacity_mbps) > CAPACITY_TOLERANCE * link.capacity_mbps:
                capacity_changes[link.link_id] = reported
                self.topology.set_capacity(link.link_id, reported)
                quality.capacity_changes += 1

        links: dict[int, LinkReading] = {}
        for link in self.topology.links.values():
            links[link.link_id] = self._link_reading(link, rates, oper, by_peer, reachable, quality)

        devices: dict[int, DeviceReading] = {}
        for name, ref in self.topology.devices.items():
            if name not in reachable:
                devices[ref.device_id] = DeviceReading(ref.device_id, "unknown")
                continue
            if not reachable[name]:
                devices[ref.device_id] = DeviceReading(ref.device_id, "down")
                continue
            own = [rates[(name, i)] for (dev, _peer), i in by_peer.items() if dev == name and (name, i) in rates]
            devices[ref.device_id] = DeviceReading(
                ref.device_id,
                "up",
                cpu_util=cpu.get(name),
                traffic_in=sum(r[0] for r in own) if own else None,
                traffic_out=sum(r[1] for r in own) if own else None,
                error_count=sum(r[2] for r in own) if own else None,
            )

        demands = self._demands(batch, quality)
        self.last_timestamp = timestamp
        self._last_measured = batch.measured_at
        return CleanBatch(timestamp, batch.measured_at, batch.received_at, interval, links, devices,
                          demands, quality, capacity_changes)

    def _link_reading(self, link, rates, oper, by_peer, reachable, quality) -> LinkReading:
        ends = [(link.source, link.dest), (link.dest, link.source)]
        statuses = [oper[end] for end in ends if end in oper]
        endpoint_down = any(reachable.get(name) is False for name in (link.source, link.dest))
        if (statuses and not all(statuses)) or endpoint_down:
            status = "down"
        elif statuses:
            status = "up"
        else:
            status = "unknown"

        source_rate = rates.get((link.source, by_peer.get((link.source, link.dest), -1)))
        dest_rate = rates.get((link.dest, by_peer.get((link.dest, link.source), -1)))
        if source_rate is not None:
            traffic_out, traffic_in = source_rate[1], source_rate[0]
        elif dest_rate is not None:
            traffic_out, traffic_in = dest_rate[0], dest_rate[1]  # seen from the other end
        elif status == "down":
            traffic_out = traffic_in = 0.0
        else:
            if status == "up":
                quality.links_without_rate += 1
            return LinkReading(link.link_id, status)
        errors = sum(r[2] for r in (source_rate, dest_rate) if r is not None)
        utilisation = max(traffic_in, traffic_out) / link.capacity_mbps * 100.0
        if utilisation > 100.0:
            if utilisation > CLIP_LIMIT_PCT:  # cannot happen after the spike check; reject to be safe
                return LinkReading(link.link_id, status)
            quality.utilisation_clipped += 1
            utilisation = 100.0
        return LinkReading(link.link_id, status, traffic_out, traffic_in, utilisation, errors)

    def _demands(self, batch: RawBatch, quality: QualityReport) -> list[DemandReading] | None:
        if not batch.flows or batch.flow_seconds <= 0:
            return None
        demands = []
        for flow in batch.flows:
            source = self.topology.devices.get(flow.src)
            dest = None if flow.dst == "INTERNET" else self.topology.devices.get(flow.dst)
            if source is None or (flow.dst != "INTERNET" and dest is None):
                quality.flows_rejected += 1
                continue
            total = flow.octets_fwd + flow.octets_rev
            if total <= 0:
                continue
            demands.append(DemandReading(
                source_id=source.device_id,
                dest_id=dest.device_id if dest else None,
                cls=flow.cls,
                mbps=total * 8 / batch.flow_seconds / 1e6,
                down_ratio=flow.octets_rev / total,
            ))
        return demands
