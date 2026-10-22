"""The twin's own pipeline, driven by an emulator in this process (evaluation only).

`direct_feed(net)` is the production TelemetryHttpAdapter with only the network socket
replaced by an in-memory transport that answers exactly as the emulator's HTTP server does
(same JSON, same paths). So readings reach the twin through the same parsing, the same
preprocessing and the same network model as in operation, without a server per run. That
matters for E4, which forks the emulator into identical branches.

`Twin(topology, net)` holds what the Digital Twin Engine holds: the topology index, the
preprocessor and the network model, built from the topology the same way `import_topology`
does (devices and links numbered from 1 in file order).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx

from data_collection.network_adapter import RawEvent
from data_collection.network_adapter.telemetry_http import TelemetryHttpAdapter
from data_collection.preprocessing import (
    CleanBatch,
    DeviceRef,
    LinkRef,
    Preprocessor,
    TopologyIndex,
)
from digital_twin.network_model import NetworkModel, StatusChange
from netemu.network import STEP_SECONDS, EmulatedNetwork
from netemu.topology import Topology


def _feed_transport(net: EmulatedNetwork) -> httpx.MockTransport:
    """Answers /v1/info, /v1/snapshot, /v1/flows and /v1/events like netemu/server.py (stepped clock)."""

    def handle(request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        after = int(query.get("after", 0))
        with net.lock:
            if url.path == "/v1/info":
                body = {"name": net.topo.name, "mode": "stepped", "speed": 1.0, "time": net.t.isoformat(),
                        "cycle_seconds": net.cycle_seconds, "step_seconds": STEP_SECONDS,
                        "cycle_seq": net.cycle_seq, "devices": len(net.device_names), "links": len(net.links)}
            elif url.path == "/v1/snapshot":
                body = net.snapshot()
            elif url.path == "/v1/flows":
                body = {"latest": net.cycle_seq, "cycles": net.flows_after(after)}
            elif url.path == "/v1/events":
                body = {"latest": net.event_seq, "events": net.events_after(after)}
            else:
                return httpx.Response(404, json={"error": f"unknown path {url.path}"})
        # through JSON, exactly as the HTTP server sends it
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"),
                              headers={"Content-Type": "application/json"})

    return httpx.MockTransport(handle)


def direct_feed(net: EmulatedNetwork) -> TelemetryHttpAdapter:
    adapter = TelemetryHttpAdapter("http://emulator")
    adapter.client.close()
    adapter.event_client.close()
    transport = _feed_transport(net)
    adapter.client = httpx.Client(base_url="http://emulator", transport=transport)
    adapter.event_client = httpx.Client(base_url="http://emulator", transport=transport)
    return adapter


def index_for(topo: Topology) -> TopologyIndex:
    devices = {name: DeviceRef(i + 1, name, d.type, d.internet_egress)
               for i, (name, d) in enumerate(topo.devices.items())}
    links = {i + 1: LinkRef(i + 1, lk.a, lk.b, lk.capacity_mbps, lk.cost) for i, lk in enumerate(topo.links)}
    return TopologyIndex(devices, links)


def model_for(topo: Topology, index: TopologyIndex | None = None, warning_pct: float = 70.0,
              critical_pct: float = 90.0) -> NetworkModel:
    index = index or index_for(topo)
    devices = [{"device_id": ref.device_id, "name": ref.name, "device_type": ref.device_type, "status": "unknown",
                "configuration": {"internet_egress": ref.internet_egress, "zone": topo.devices[ref.name].zone,
                                  "role": topo.devices[ref.name].role}}
               for ref in index.devices.values()]
    links = [{"link_id": lk.link_id, "source_device_id": index.devices[lk.source].device_id,
              "dest_device_id": index.devices[lk.dest].device_id, "capacity_mbps": lk.capacity_mbps,
              "status": "unknown", "routing_cost": lk.routing_cost}
             for lk in index.links.values()]
    return NetworkModel(devices, links, warning_pct=warning_pct, critical_pct=critical_pct,
                        reference_bandwidth_mbps=topo.reference_bandwidth_mbps)


@dataclass
class Twin:
    """The engine's ingest path (processes 1.0-3.0) for one emulator."""

    topo: Topology
    net: EmulatedNetwork
    cycle_seconds: int = 60
    index: TopologyIndex = field(init=False)
    model: NetworkModel = field(init=False)
    preprocessor: Preprocessor = field(init=False)
    feed: TelemetryHttpAdapter = field(init=False)

    def __post_init__(self):
        self.index = index_for(self.topo)
        self.model = model_for(self.topo, self.index)
        self.preprocessor = Preprocessor(self.index, self.cycle_seconds)
        self.feed = direct_feed(self.net)

    def step_cycle(self) -> None:
        """Advance the emulator by one monitoring cycle."""
        with self.net.lock:
            for _ in range(self.net.steps_per_cycle()):
                self.net.step()

    def ingest(self) -> CleanBatch | None:
        """Collect, validate and apply one cycle, exactly as the engine does."""
        clean = self.preprocessor.process(self.feed.poll())
        if clean is not None:
            self.model.apply(clean)
        return clean

    def advance(self, cycles: int = 1) -> CleanBatch | None:
        clean = None
        for _ in range(cycles):
            self.step_cycle()
            clean = self.ingest() or clean
        return clean

    def link_id(self, a: str, b: str) -> int:
        for link_id, ref in self.index.links.items():
            if {ref.source, ref.dest} == {a, b}:
                return link_id
        raise KeyError(f"no link {a} <-> {b}")

    # ------------------------------------------------ event path (FR2)
    def apply_event(self, event: RawEvent) -> StatusChange | None:
        """One up/down notification, mapped and applied exactly as TwinEngine.apply_event does
        (digital_twin/runtime/engine.py), minus the database write and the dashboard publish."""
        new_status = "down" if event.type.endswith("_down") else "up"
        if event.type.startswith("link"):
            a, _, b = event.element.partition("|")
            link = self.index.link_between(a, b)
            if link is None:
                return None
            kind, element_id = "link", link.link_id
        else:
            device = self.index.devices.get(event.element)
            if device is None:
                return None
            kind, element_id = "device", device.device_id
        return self.model.set_status(kind, element_id, new_status)

    def drain_events(self) -> list[StatusChange]:
        """Read the feed's new events (/v1/events, through the production adapter) and apply each.

        The first call only sets the adapter's cursor to "now", as the engine's listener does.
        The engine long-polls this in its own thread, so in operation an event is applied within
        milliseconds; a harness that calls this after every emulator step reproduces that to
        within one step (STEP_SECONDS of network time)."""
        changes = []
        for event in self.feed.events(wait_seconds=0):
            change = self.apply_event(event)
            if change is not None:
                changes.append(change)
        return changes

    def step(self) -> None:
        """Advance the emulator by one step (STEP_SECONDS of network time)."""
        with self.net.lock:
            self.net.step()

    def close(self) -> None:
        self.feed.close()
