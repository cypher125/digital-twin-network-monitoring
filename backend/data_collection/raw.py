"""Raw monitoring data as collected (process 1.0 output, process 2.0 input).

Plain data types only. Kept apart from the adapters so the preprocessing module,
the network model and the simulation engine never depend on adapter code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class InterfaceSample:
    device: str
    if_index: int
    peer: str            # neighbouring device on this interface (LLDP-style)
    in_octets: int       # cumulative counter (ifHCInOctets)
    out_octets: int      # cumulative counter (ifHCOutOctets)
    in_errors: int       # cumulative counter (ifInErrors)
    oper_up: bool
    speed_mbps: float


@dataclass(frozen=True)
class DeviceSample:
    device: str
    reachable: bool
    uptime_ticks: int | None = None   # hundredths of a second since boot (sysUpTime)
    cpu_pct: float | None = None
    interfaces: tuple[InterfaceSample, ...] = ()


@dataclass(frozen=True)
class FlowSample:
    """Aggregated flow record (NetFlow-style): traffic between two devices for one class."""

    src: str
    dst: str             # a device name, or "INTERNET"
    cls: str
    octets_fwd: int      # src -> dst
    octets_rev: int      # dst -> src


@dataclass
class RawBatch:
    """One poll of the network: what process 1.0 passes to process 2.0."""

    source: str
    measured_at: datetime    # the data source's own clock (network time)
    received_at: datetime    # wall clock when the adapter received the data
    devices: list[DeviceSample]
    flows: list[FlowSample] = field(default_factory=list)
    flow_seconds: float = 0.0  # length of the period the flow records cover


@dataclass(frozen=True)
class RawEvent:
    """An up/down notification (trap-style), used for event-driven updates (FR2)."""

    seq: int
    time: datetime           # network time of the event
    type: str                # link_down, link_up, device_down, device_up
    element: str             # device name, or "A|B" for a link
    detail: str
    received_at: datetime
