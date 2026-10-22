"""The network adapter interface.

An adapter only READS from the network. There is deliberately no method that
sends commands or configuration to devices, so nothing in the system can change
the real network (write-up section 3.8 and gap G3). A unit test enforces this.
"""
from __future__ import annotations

from typing import Protocol

from ..raw import DeviceSample, FlowSample, InterfaceSample, RawBatch, RawEvent

__all__ = ["DeviceSample", "FlowSample", "InterfaceSample", "NetworkAdapter", "RawBatch", "RawEvent"]


class NetworkAdapter(Protocol):
    """Read-only access to a monitoring data source."""

    name: str

    def describe(self) -> dict:
        """Information about the source: its clock, speed and cycle length."""
        ...

    def poll(self) -> RawBatch:
        """Read the current counters, device statistics and new flow records."""
        ...

    def events(self, wait_seconds: float) -> list[RawEvent]:
        """Return new up/down events, waiting up to `wait_seconds` for one to arrive."""
        ...
