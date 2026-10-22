"""The twin's own routing model: how demand traffic flows over the virtual network.

Written independently of the emulator (import-linter forbids sharing code).
Each demand follows its shortest paths by routing cost, split EQUALLY across
equal-cost paths (the real network's hashing is uneven, so the two can differ,
which evaluation E4 measures).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import networkx as nx

from .model import INTERNET, NetworkModel, TwinDemand

MAX_PATHS = 8


@dataclass
class RoutedLoads:
    load_out: dict[int, float]        # link_id -> Mbps, source -> destination
    load_in: dict[int, float]         # link_id -> Mbps, destination -> source
    utilisation: dict[int, float]     # link_id -> offered load as % of capacity (may exceed 100)
    undeliverable_mbps: float = 0.0   # demand with no path at all
    unreachable: list[TwinDemand] = field(default_factory=list)
    paths: dict[int, list[list[int | str]]] = field(default_factory=dict)  # demand index -> paths
    link_paths: dict[int, set[int]] = field(default_factory=dict)          # demand index -> links used


def routing_graph(model: NetworkModel, overrides: dict[int, float] | None = None) -> nx.Graph:
    """The operational graph the router uses, plus the virtual INTERNET node behind the gateways."""
    g = model.operational_graph()
    if overrides:
        for link_id, cost in overrides.items():
            u, v = model.link_ends[link_id]
            if g.has_edge(u, v):
                g.edges[u, v]["cost"] = float(cost)
    egress = [n for n in model.egress_ids() if n in g]
    if egress:
        g.add_node(INTERNET)
        for n in egress:
            g.add_edge(n, INTERNET, cost=0.0, link_id=None)
    return g


def route_demands(model: NetworkModel, demands: list[TwinDemand] | None = None,
                  pinned: dict[int, list[int | str]] | None = None) -> RoutedLoads:
    """Route every demand over the model and return the load on each link.

    `pinned` maps a demand index to a forced path (used by the reroute_traffic
    scenario); a pinned path that is not fully operational is ignored.
    """
    demands = model.demands if demands is None else demands
    g = routing_graph(model)
    load_out = dict.fromkeys(model.link_ends, 0.0)
    load_in = dict.fromkeys(model.link_ends, 0.0)
    result = RoutedLoads(load_out, load_in, {})
    cache: dict[tuple, list[list]] = {}
    for index, d in enumerate(demands):
        src = d.source_id
        dst = INTERNET if d.dest_id is None else d.dest_id
        forced = (pinned or {}).get(index)
        if forced and all(g.has_edge(a, b) for a, b in itertools.pairwise(forced)):
            paths = [forced]
        else:
            key = (src, dst)
            if key not in cache:
                found: list[list] = []
                if src in g and dst in g:
                    try:
                        found = list(itertools.islice(nx.all_shortest_paths(g, src, dst, weight="cost"), MAX_PATHS))
                    except nx.NetworkXNoPath:
                        found = []
                cache[key] = found
            paths = cache[key]
        if not paths:
            result.undeliverable_mbps += d.mbps
            result.unreachable.append(d)
            continue
        result.paths[index] = paths
        used: set[int] = set()
        share = 1.0 / len(paths)
        forward = d.mbps * (1.0 - d.down_ratio) * share
        reverse = d.mbps * d.down_ratio * share
        for path in paths:
            for a, b in itertools.pairwise(path):
                link_id = g.edges[a, b]["link_id"]
                if link_id is None:
                    continue
                used.add(link_id)
                if model.link(link_id)["source"] == a:
                    load_out[link_id] += forward
                    load_in[link_id] += reverse
                else:
                    load_in[link_id] += forward
                    load_out[link_id] += reverse
        result.link_paths[index] = used
    for link_id in model.link_ends:
        capacity = model.link(link_id)["capacity_mbps"]
        result.utilisation[link_id] = max(load_out[link_id], load_in[link_id]) / capacity * 100.0
    return result
