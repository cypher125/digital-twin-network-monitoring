"""The live virtual replica of the network.

Nodes are devices (keyed by device_id) and edges are links. Node attributes:
type, configuration and current state (status, CPU, traffic, errors). Edge
attributes: link_id, which end is the source, capacity, routing cost, and
current state (status, traffic in each direction, utilisation, errors).
The model also holds the current traffic demand matrix from flow telemetry.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime

import networkx as nx

from data_collection.preprocessing import CleanBatch

INTERNET = "INTERNET"  # virtual node behind the internet gateways
HEALTH_GREEN, HEALTH_YELLOW, HEALTH_RED, HEALTH_DOWN, HEALTH_UNKNOWN = (
    "green", "yellow", "red", "down", "unknown")


@dataclass(frozen=True)
class TwinDemand:
    source_id: int
    dest_id: int | None   # None means the internet
    cls: str
    mbps: float           # both directions together
    down_ratio: float     # share flowing destination -> source


@dataclass(frozen=True)
class StatusChange:
    kind: str             # "device" or "link"
    element_id: int
    old: str
    new: str


class NetworkModel:
    def __init__(self, devices: list[dict], links: list[dict], *, warning_pct: float,
                 critical_pct: float, reference_bandwidth_mbps: float):
        self.warning_pct = warning_pct
        self.critical_pct = critical_pct
        self.reference_bandwidth_mbps = reference_bandwidth_mbps
        self.graph = nx.Graph()
        self.timestamp: datetime | None = None
        self.demands: list[TwinDemand] = []
        self.known_classes: set[str] = set()   # traffic classes reported by the engine (API-side validation)
        for d in devices:
            config = d.get("configuration") or {}
            self.graph.add_node(
                d["device_id"],
                name=d["name"],
                device_type=d["device_type"],
                location=d.get("location", ""),
                configuration=config,
                internet_egress=bool(config.get("internet_egress", False)),
                status=d.get("status", "unknown"),
                cpu_util=None, traffic_in=None, traffic_out=None, error_count=None,
            )
        self.link_ends: dict[int, tuple[int, int]] = {}
        for lk in links:
            u, v = lk["source_device_id"], lk["dest_device_id"]
            capacity = float(lk["capacity_mbps"])
            cost = lk.get("routing_cost")
            self.graph.add_edge(
                u, v,
                link_id=lk["link_id"],
                source=u,
                capacity_mbps=capacity,
                explicit_cost=cost is not None,  # otherwise the cost follows the capacity (OSPF auto-cost)
                cost=float(cost) if cost is not None else reference_bandwidth_mbps / capacity,
                status=lk.get("status", "unknown"),
                traffic_out=None, traffic_in=None, utilisation_pct=None, error_count=None,
            )
            self.link_ends[lk["link_id"]] = (u, v)

    # ------------------------------------------------------------ access
    def link(self, link_id: int) -> dict:
        u, v = self.link_ends[link_id]
        return self.graph.edges[u, v]

    def device(self, device_id: int) -> dict:
        return self.graph.nodes[device_id]

    def link_ids(self) -> list[int]:
        return list(self.link_ends)

    def name_of(self, device_id: int | None) -> str:
        return INTERNET if device_id is None else self.graph.nodes[device_id]["name"]

    def link_label(self, link_id: int) -> str:
        u, v = self.link_ends[link_id]
        return f"{self.graph.nodes[u]['name']} <-> {self.graph.nodes[v]['name']}"

    def traffic_classes(self) -> set[str]:
        return {d.cls for d in self.demands} | self.known_classes

    def zones(self) -> set[str]:
        return {str(data["configuration"].get("zone", "")) for _, data in self.graph.nodes(data=True)} - {""}

    def egress_ids(self) -> list[int]:
        return [n for n, data in self.graph.nodes(data=True) if data["internet_egress"]]

    def health(self, value_pct: float | None, status: str = "up") -> str:
        """Colour coding of section 3.7, using the D1 thresholds."""
        if status == "down":
            return HEALTH_DOWN
        if value_pct is None:
            return HEALTH_UNKNOWN
        if value_pct >= self.critical_pct:
            return HEALTH_RED
        if value_pct >= self.warning_pct:
            return HEALTH_YELLOW
        return HEALTH_GREEN

    # ---------------------------------------------------- synchronisation
    def apply(self, batch: CleanBatch) -> list[StatusChange]:
        """Update the replica from one validated, normalised batch (process 3.0)."""
        changes: list[StatusChange] = []
        for device_id, reading in batch.devices.items():
            if device_id not in self.graph:
                continue
            node = self.graph.nodes[device_id]
            if reading.status != "unknown" and reading.status != node["status"]:
                changes.append(StatusChange("device", device_id, node["status"], reading.status))
                node["status"] = reading.status
            node["cpu_util"] = reading.cpu_util
            node["traffic_in"] = reading.traffic_in
            node["traffic_out"] = reading.traffic_out
            node["error_count"] = reading.error_count
        for link_id, capacity in batch.capacity_changes.items():
            if link_id in self.link_ends:
                edge = self.link(link_id)
                edge["capacity_mbps"] = capacity
                if not edge["explicit_cost"]:
                    edge["cost"] = self.reference_bandwidth_mbps / capacity
        for link_id, reading in batch.links.items():
            if link_id not in self.link_ends:
                continue
            edge = self.link(link_id)
            if reading.status != "unknown" and reading.status != edge["status"]:
                changes.append(StatusChange("link", link_id, edge["status"], reading.status))
                edge["status"] = reading.status
            if reading.utilisation_pct is not None:
                edge["traffic_out"] = reading.traffic_out
                edge["traffic_in"] = reading.traffic_in
                edge["utilisation_pct"] = reading.utilisation_pct
                edge["error_count"] = reading.error_count
        if batch.demands is not None:
            self.demands = [TwinDemand(d.source_id, d.dest_id, d.cls, d.mbps, d.down_ratio)
                            for d in batch.demands]
        self.timestamp = batch.timestamp
        return changes

    def set_status(self, kind: str, element_id: int, status: str) -> StatusChange | None:
        """Event-driven update (FR2): apply an up/down notification immediately."""
        attrs = self.graph.nodes[element_id] if kind == "device" else self.link(element_id)
        if attrs["status"] == status:
            return None
        change = StatusChange(kind, element_id, attrs["status"], status)
        attrs["status"] = status
        if kind == "link" and status == "down":
            attrs["traffic_out"] = attrs["traffic_in"] = attrs["utilisation_pct"] = 0.0
        return change

    # ------------------------------------------------------------ analysis
    def operational_graph(self) -> nx.Graph:
        """Devices and links that are currently up (unknown counts as up)."""
        g = nx.Graph()
        for n, data in self.graph.nodes(data=True):
            if data["status"] != "down":
                g.add_node(n)
        for u, v, data in self.graph.edges(data=True):
            if data["status"] != "down" and u in g and v in g:
                g.add_edge(u, v, cost=data["cost"], link_id=data["link_id"])
        return g

    def structural_bottlenecks(self) -> dict:
        """Single points of failure and most-used links (Table 3.4: bottleneck identification)."""
        g = self.operational_graph()
        bridges = [g.edges[u, v]["link_id"] for u, v in nx.bridges(g)] if g.number_of_edges() else []
        points = sorted(nx.articulation_points(g)) if g.number_of_nodes() else []
        betweenness = nx.edge_betweenness_centrality(g, weight="cost", normalized=True) if g.number_of_edges() else {}
        ranked = sorted(((score, g.edges[u, v]["link_id"]) for (u, v), score in betweenness.items()), reverse=True)
        return {
            "bridge_links": sorted(bridges),
            "articulation_devices": points,
            "most_used_links": [link_id for _score, link_id in ranked[:5]],
        }

    def copy(self) -> NetworkModel:
        """A detached copy for the simulation engine (G3). Changes to it never touch this model."""
        return copy.deepcopy(self)
