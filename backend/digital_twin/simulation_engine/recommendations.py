"""Recommendations: tested fixes for a link that is forecast to congest (plan section 7.7).

This is the "Optimization" half of the system's name (and the "insights and
recommendations" of section 3.2). Like Shi et al.'s digital twin, it tries
candidate configurations on the virtual model before suggesting one:

1. Build candidate fixes for the link: raise its routing cost, reroute the largest
   flow crossing it, limit its largest traffic class (QoS), upgrade its capacity.
2. Run each through the simulation engine, against the forecast load if given (what the
   administrator is shown), and again with the link pushed to full load (STRESS_PCT).
3. Drop any candidate that creates a new bottleneck, cuts off traffic, or (for an
   immediate fix) leaves the link at or above the critical threshold, or barely
   lowers it, in either run.

   The stress run was added after evaluation E4. At an alert the point forecast was
   20-44 points below the peak the surge then reached, so a fix that looked enough at the
   forecast load often was not. Worse, a fix that changed nothing was kept, because the
   forecast load alone was already below the threshold: for example, raising the routing
   cost of a link that has no alternative path. Tested at full load, a fix must actually
   take traffic off the link (at least 5 % of its load), and its new path must have room
   for it. The full load is approximate: the forecast basis scales a demand by the link that
   is busiest on its path, so a link that is not the busiest one on any path is not raised.
4. Rank immediate fixes by least disruption, then by resulting peak utilisation.
   A capacity upgrade always relieves a link, so it is not ranked against them:
   it is returned separately as planning advice.

Nothing is ever applied automatically; recommendations are shown to the administrator.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from digital_twin.network_model import NetworkModel, route_demands

from .runner import SimulationOutcome, run_scenario
from .scenarios import INTERNET_KEY, ScenarioError

CAPACITY_TIERS = (10, 100, 200, 300, 500, 1000, 2500, 10000, 40000, 100000)
DISRUPTION = {"routing_change": 1, "reroute_traffic": 2, "qos_policy": 3}   # lower = less disruptive
QOS_SHARE = 0.7          # a QoS candidate limits the class to 70 % of its current load on the link
STRESS_PCT = 100.0       # immediate fixes must also hold with the link at full load (E4)
MIN_RELIEF_SHARE = 0.05  # ... and take at least 5 % of the link's load off it there


@dataclass
class Recommendation:
    scenario_type: str
    parameters: dict
    title: str
    kind: str                     # "immediate" or "planning"
    outcome: SimulationOutcome
    target_after_pct: float

    def as_dict(self) -> dict:
        return {"scenario_type": self.scenario_type, "parameters": self.parameters, "title": self.title,
                "kind": self.kind, "target_after_pct": round(self.target_after_pct, 1),
                "max_after": self.outcome.max_after, "summary": self.outcome.summary}


def next_tier(capacity: float) -> float | None:
    return next((t for t in CAPACITY_TIERS if t > capacity * 1.01), None)


def candidates(model: NetworkModel, link_id: int) -> list[tuple[str, dict, str, str]]:
    """(scenario type, parameters, plain-language title, kind) for every candidate fix."""
    label = model.link_label(link_id)
    edge = model.link(link_id)
    routed = route_demands(model, model.demands)
    crossing = [(i, d) for i, d in enumerate(model.demands) if link_id in routed.link_paths.get(i, set())]
    out: list[tuple[str, dict, str, str]] = [(
        "routing_change", {"link_costs": [{"link_id": link_id, "cost": round(edge["cost"] * 10, 3)}]},
        f"Raise the routing cost of {label} so traffic prefers other paths", "immediate")]

    by_pair: dict[tuple[int, int | None], float] = defaultdict(float)
    by_class: dict[str, float] = defaultdict(float)
    for _, d in crossing:
        by_pair[(d.source_id, d.dest_id)] += d.mbps
        by_class[d.cls] += d.mbps
    if by_pair:
        (source, dest), _ = max(by_pair.items(), key=lambda item: item[1])
        out.append((
            "reroute_traffic",
            {"source_id": source, "dest": INTERNET_KEY if dest is None else dest, "avoid_link_ids": [link_id]},
            f"Move traffic from {model.name_of(source)} to {model.name_of(dest)} off {label}", "immediate"))
    if by_class:
        cls, load = max(by_class.items(), key=lambda item: item[1])
        limit = round(load * QOS_SHARE, 1)
        out.append(("qos_policy", {"cls": cls, "limit_mbps": limit, "link_id": link_id},
                    f"Limit '{cls}' traffic on {label} to {limit:g} Mbps", "immediate"))
    upgrade = next_tier(edge["capacity_mbps"])
    if upgrade:
        out.append(("capacity_change", {"link_id": link_id, "capacity_mbps": upgrade},
                    f"Plan an upgrade of {label} from {edge['capacity_mbps']:g} to {upgrade:g} Mbps", "planning"))
    return out


def _rejected(outcome: SimulationOutcome, link_id: int, kind: str, critical: float, stressed: bool) -> bool:
    target = next(lk for lk in outcome.links if lk.link_id == link_id)
    if outcome.created or outcome.isolated_devices:
        return True                       # fixes one link by breaking another
    if outcome.undeliverable_mbps_after > outcome.undeliverable_mbps_before + 0.05:
        return True                       # would drop traffic
    if kind == "immediate" and target.after_pct >= critical:
        return True                       # does not actually relieve the link
    if kind == "immediate" and stressed and target.after_pct > target.before_pct * (1 - MIN_RELIEF_SHARE):
        return True                       # takes (almost) nothing off the link: no fix at all
    return False


def recommend(model: NetworkModel, link_id: int, predicted_pct: dict[int, float] | None = None, *,
              basis: str = "current", max_immediate: int = 3) -> list[Recommendation]:
    now = model.link(link_id)["utilisation_pct"] or 0.0
    expected = (predicted_pct or {}).get(link_id, now)
    stressed_pct = {**(predicted_pct or {}), link_id: max(expected, STRESS_PCT)}
    kept: list[Recommendation] = []
    for scenario_type, params, title, kind in candidates(model, link_id):
        try:
            outcome = run_scenario(model, scenario_type, params, predicted_pct=predicted_pct, basis=basis)
            stress = run_scenario(model, scenario_type, params, predicted_pct=stressed_pct, basis=basis)
        except ScenarioError:
            continue                      # e.g. no other path exists for a reroute
        if _rejected(outcome, link_id, kind, model.critical_pct, stressed=False) or                 _rejected(stress, link_id, kind, model.critical_pct, stressed=True):
            continue
        target = next(lk for lk in outcome.links if lk.link_id == link_id)
        kept.append(Recommendation(scenario_type, params, title, kind, outcome, target.after_pct))
    immediate = sorted((r for r in kept if r.kind == "immediate"),
                       key=lambda r: (DISRUPTION[r.scenario_type], r.outcome.max_after["pct"]))[:max_immediate]
    return immediate + [r for r in kept if r.kind == "planning"]
