"""Network adapters: read monitoring data from the network (Figure 3.4, process 1.0 Collect Monitoring Data)."""
from collections.abc import Callable

from .base import DeviceSample, FlowSample, InterfaceSample, NetworkAdapter, RawBatch, RawEvent
from .telemetry_http import TelemetryHttpAdapter

# The adapter registry (NFR5): `manage.py run_twin --adapter <key> --source <address>` picks one.
# A new data source is one module implementing NetworkAdapter plus one line here.
ADAPTERS: dict[str, Callable[[str], NetworkAdapter]] = {
    "telemetry-http": TelemetryHttpAdapter,
}


def make_adapter(key: str, source: str) -> NetworkAdapter:
    try:
        factory = ADAPTERS[key]
    except KeyError:
        raise ValueError(f"Unknown adapter '{key}'. Known adapters: {', '.join(sorted(ADAPTERS))}.") from None
    return factory(source)


__all__ = [
    "ADAPTERS",
    "DeviceSample",
    "FlowSample",
    "InterfaceSample",
    "NetworkAdapter",
    "RawBatch",
    "RawEvent",
    "TelemetryHttpAdapter",
    "make_adapter",
]
