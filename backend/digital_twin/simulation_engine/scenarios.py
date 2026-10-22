"""Scenario types: what an administrator can try on the virtual network (FR4, plan D21).

Each type has a plain-language description, a list of form fields (used by the
dashboard to build its guided form), validation that returns clear messages,
and an `apply` that changes a DETACHED copy of the model and/or its demands.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import networkx as nx

from digital_twin.network_model import NetworkModel, TwinDemand, route_demands, routing_graph

INTERNET_KEY = "internet"


class ScenarioError(ValueError):
    """The scenario parameters are not valid for this network (shown to the user)."""


@dataclass
class Change:
    demands: list[TwinDemand]
    pinned: dict[int, list] = field(default_factory=dict)   # demand index -> forced path
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioType:
    key: str
    label: str
    description: str
    fields: list[dict]
    validate: Callable[[dict, NetworkModel], dict]
    apply: Callable[[NetworkModel, list[TwinDemand], dict], Change]
    tier: str = "must"

    def describe(self) -> dict:
        return {"key": self.key, "label": self.label, "description": self.description,
                "fields": self.fields, "tier": self.tier}


# ----------------------------------------------------------------- helpers
def _number(params: dict, name: str, *, minimum: float | None = None, maximum: float | None = None,
            required: bool = True, label: str | None = None) -> float | None:
    label = label or name.replace("_", " ")
    value = params.get(name)
    if value in (None, ""):
        if required:
            raise ScenarioError(f"Please enter the {label}.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ScenarioError(f"The {label} must be a number.") from None
    if minimum is not None and number < minimum:
        raise ScenarioError(f"The {label} must be at least {minimum:g}.")
    if maximum is not None and number > maximum:
        raise ScenarioError(f"The {label} must be at most {maximum:g}.")
    return number


def _link(params: dict, model: NetworkModel, name: str = "link_id") -> int:
    try:
        link_id = int(params[name])
    except (KeyError, TypeError, ValueError):
        raise ScenarioError("Please choose a link.") from None
    if link_id not in model.link_ends:
        raise ScenarioError(f"Link {link_id} is not part of the network.")
    return link_id


def _device(params: dict, model: NetworkModel, name: str = "device_id", *, allow_internet: bool = False,
            required: bool = True) -> int | None:
    value = params.get(name)
    if value in (None, ""):
        if required:
            raise ScenarioError("Please choose a device.")
        return None
    if allow_internet and str(value).lower() == INTERNET_KEY:
        return None
    try:
        device_id = int(value)
    except (TypeError, ValueError):
        raise ScenarioError("Please choose a device.") from None
    if device_id not in model.graph:
        raise ScenarioError(f"Device {device_id} is not part of the network.")
    return device_id


def _classes(model: NetworkModel) -> set[str]:
    return model.traffic_classes()


def _zones(model: NetworkModel) -> set[str]:
    return model.zones()


def _zone_of(model: NetworkModel, device_id: int) -> str:
    return str(model.device(device_id)["configuration"].get("zone", ""))


def _matches(model: NetworkModel, d: TwinDemand, params: dict) -> bool:
    """Does a demand match the source / destination / class filters in params?"""
    if params.get("cls") and d.cls != params["cls"]:
        return False
    if params.get("source_zone") and _zone_of(model, d.source_id) != params["source_zone"]:
        return False
    if params.get("source_id") is not None and d.source_id != params["source_id"]:
        return False
    if "dest" in params:
        if params["dest"] == INTERNET_KEY and d.dest_id is not None:
            return False
        if isinstance(params["dest"], int) and d.dest_id != params["dest"]:
            return False
    return True


def _filters(params: dict, model: NetworkModel, *, require_one: bool = False) -> dict:
    out: dict = {}
    cls = params.get("cls") or None
    if cls:
        if cls not in _classes(model):
            raise ScenarioError(f"There is no traffic of class '{cls}' in the network right now.")
        out["cls"] = cls
    zone = params.get("source_zone") or None
    if zone:
        if zone not in _zones(model):
            raise ScenarioError(f"Unknown zone '{zone}'.")
        out["source_zone"] = zone
    source = _device(params, model, "source_id", required=False)
    if source is not None:
        out["source_id"] = source
    if params.get("dest") not in (None, ""):
        dest = _device(params, model, "dest", allow_internet=True)
        out["dest"] = INTERNET_KEY if dest is None else dest
    if require_one and not out:
        raise ScenarioError("Please choose which traffic the rule applies to (class, source or destination).")
    return out


def _flows(count: int) -> str:
    """'1 traffic flow', '12 traffic flows'."""
    return f"{count} traffic flow{'' if count == 1 else 's'}"


def _scale(demands: list[TwinDemand], index: int, factor: float) -> None:
    d = demands[index]
    demands[index] = TwinDemand(d.source_id, d.dest_id, d.cls, d.mbps * factor, d.down_ratio)


# --------------------------------------------------------- scenario types
def _v_traffic(params, model):
    out = {"percent": _number(params, "percent", minimum=-90, maximum=500, label="percentage change")}
    out.update(_filters(params, model))
    return out


def _a_traffic(model, demands, params):
    demands = list(demands)
    factor = 1 + params["percent"] / 100
    matched = [i for i, d in enumerate(demands) if _matches(model, d, params)]
    for i in matched:
        _scale(demands, i, factor)
    # a real minus sign (U+2212), as in the summary's "−15.2 pts"; + 0.0 turns -0 into 0
    percent = f"{params['percent'] + 0.0:+g}".replace("-", "−")
    return Change(demands, notes=[f"{_flows(len(matched))} changed by {percent}%."])


def _v_link_failure(params, model):
    return {"link_id": _link(params, model)}


def _a_link_failure(model, demands, params):
    model.set_status("link", params["link_id"], "down")
    return Change(list(demands), notes=[f"{model.link_label(params['link_id'])} taken out of service."])


def _v_device_failure(params, model):
    return {"device_id": _device(params, model)}


def _a_device_failure(model, demands, params):
    model.set_status("device", params["device_id"], "down")
    for u, v in model.graph.edges(params["device_id"]):
        model.graph.edges[u, v]["status"] = "down"
    return Change(list(demands), notes=[f"{model.name_of(params['device_id'])} taken out of service."])


def _v_routing(params, model):
    items = params.get("link_costs") or []
    if not items:
        raise ScenarioError("Please give a new routing cost for at least one link.")
    costs = []
    for item in items:
        costs.append({"link_id": _link(item, model),
                      "cost": _number(item, "cost", minimum=0.001, maximum=1e6, label="routing cost")})
    return {"link_costs": costs}


def _a_routing(model, demands, params):
    for item in params["link_costs"]:
        model.link(item["link_id"])["cost"] = item["cost"]
    labels = ", ".join(f"{model.link_label(i['link_id'])} -> {i['cost']:g}" for i in params["link_costs"])
    return Change(list(demands), notes=[f"Routing costs changed: {labels}."])


def _v_reroute(params, model):
    out = _filters(params, model)
    if "source_id" not in out or "dest" not in out:
        raise ScenarioError("Please choose the source device and the destination of the traffic to move.")
    avoid = [_link({"link_id": x}, model) for x in params.get("avoid_link_ids") or []]
    if not avoid:
        raise ScenarioError("Please choose at least one link the traffic should avoid.")
    out["avoid_link_ids"] = avoid
    return out


def _a_reroute(model, demands, params):
    g = routing_graph(model)  # the same graph the router uses
    for link_id in params["avoid_link_ids"]:
        u, v = model.link_ends[link_id]
        if g.has_edge(u, v):
            g.remove_edge(u, v)
    dest = "INTERNET" if params["dest"] == INTERNET_KEY else params["dest"]
    try:
        path = nx.shortest_path(g, params["source_id"], dest, weight="cost")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        raise ScenarioError("There is no other path for this traffic that avoids the chosen links.") from None
    pinned = {i: path for i, d in enumerate(demands) if _matches(model, d, params)}
    names = " -> ".join(model.name_of(None if n == "INTERNET" else n) for n in path)
    return Change(list(demands), pinned, notes=[f"{_flows(len(pinned))} moved onto {names}."])


def _v_capacity(params, model):
    return {"link_id": _link(params, model),
            "capacity_mbps": _number(params, "capacity_mbps", minimum=1, maximum=400000, label="new capacity (Mbps)")}


def _a_capacity(model, demands, params):
    edge = model.link(params["link_id"])
    old = edge["capacity_mbps"]
    edge["capacity_mbps"] = params["capacity_mbps"]
    return Change(list(demands), notes=[
        f"{model.link_label(params['link_id'])} capacity {old:g} -> {params['capacity_mbps']:g} Mbps."])


def _v_acl(params, model):
    out = _filters(params, model, require_one=True)
    out["action"] = "deny"
    return out


def _a_acl(model, demands, params):
    kept = [d if not _matches(model, d, params) else TwinDemand(d.source_id, d.dest_id, d.cls, 0.0, d.down_ratio)
            for d in demands]
    blocked = sum(d.mbps for d in demands if _matches(model, d, params))
    return Change(kept, notes=[f"Access rule blocks {blocked:.1f} Mbps of matching traffic."])


def _v_qos(params, model):
    out = _filters(params, model)
    if "cls" not in out:
        raise ScenarioError("Please choose the traffic class to limit.")
    out["limit_mbps"] = _number(params, "limit_mbps", minimum=0.1, maximum=400000, label="limit (Mbps)")
    if params.get("link_id") not in (None, ""):
        out["link_id"] = _link(params, model)
    return out


def _a_qos(model, demands, params):
    demands = list(demands)
    matched = [i for i, d in enumerate(demands) if _matches(model, d, params)]
    if "link_id" in params:
        routed = route_demands(model, demands)
        on_link = [i for i in matched if params["link_id"] in routed.link_paths.get(i, set())]
        total = sum(demands[i].mbps for i in on_link)
        scope, targets = model.link_label(params["link_id"]), on_link
    else:
        total = sum(demands[i].mbps for i in matched)
        scope, targets = "the whole network", matched
    if total > params["limit_mbps"] > 0:
        factor = params["limit_mbps"] / total
        for i in targets:
            _scale(demands, i, factor)
        note = f"'{params['cls']}' traffic on {scope} limited from {total:.1f} to {params['limit_mbps']:g} Mbps."
    else:
        note = f"'{params['cls']}' traffic on {scope} ({total:.1f} Mbps) is already within the limit."
    return Change(demands, notes=[note])


def _v_add_link(params, model):
    a = _device(params, model, "source_id")
    b = _device(params, model, "dest_id")
    if a == b:
        raise ScenarioError("A link must connect two different devices.")
    if model.graph.has_edge(a, b):
        raise ScenarioError("These devices are already connected.")
    return {"source_id": a, "dest_id": b,
            "capacity_mbps": _number(params, "capacity_mbps", minimum=1, maximum=400000, label="capacity (Mbps)")}


def _a_add_link(model, demands, params):
    link_id = -1 - len(model.link_ends)  # temporary id, only inside this copy
    capacity = params["capacity_mbps"]
    model.graph.add_edge(params["source_id"], params["dest_id"], link_id=link_id, source=params["source_id"],
                         capacity_mbps=capacity, cost=model.reference_bandwidth_mbps / capacity, status="up",
                         traffic_out=None, traffic_in=None, utilisation_pct=None, error_count=None)
    model.link_ends[link_id] = (params["source_id"], params["dest_id"])
    return Change(list(demands), notes=[f"New {capacity:g} Mbps link {model.link_label(link_id)} added."])


FILTER_FIELDS = [
    {"name": "cls", "label": "Traffic class", "type": "class", "required": False},
    {"name": "source_zone", "label": "From zone", "type": "zone", "required": False},
    {"name": "source_id", "label": "From device", "type": "device", "required": False},
    {"name": "dest", "label": "To (device or internet)", "type": "destination", "required": False},
]

REGISTRY: dict[str, ScenarioType] = {s.key: s for s in [
    ScenarioType("traffic_increase", "Traffic increase",
                 "What happens if traffic grows (or falls)? For example, more students online during exams.",
                 [{"name": "percent", "label": "Change (%)", "type": "number", "min": -90, "max": 500, "required": True},
                  *FILTER_FIELDS], _v_traffic, _a_traffic),
    ScenarioType("link_failure", "Link failure", "What happens if this cable or connection goes down?",
                 [{"name": "link_id", "label": "Link", "type": "link", "required": True}],
                 _v_link_failure, _a_link_failure),
    ScenarioType("device_failure", "Device failure", "What happens if this switch, router or server fails?",
                 [{"name": "device_id", "label": "Device", "type": "device", "required": True}],
                 _v_device_failure, _a_device_failure),
    ScenarioType("routing_change", "Routing change",
                 "Change the routing cost of links to steer traffic onto different paths (like an OSPF cost change).",
                 [{"name": "link_costs", "label": "New link costs", "type": "link_costs", "required": True}],
                 _v_routing, _a_routing),
    ScenarioType("reroute_traffic", "Reroute traffic",
                 "Move some traffic from one path to another by telling it which links to avoid.",
                 [{"name": "source_id", "label": "From device", "type": "device", "required": True},
                  {"name": "dest", "label": "To (device or internet)", "type": "destination", "required": True},
                  {"name": "cls", "label": "Traffic class", "type": "class", "required": False},
                  {"name": "avoid_link_ids", "label": "Links to avoid", "type": "links", "required": True}],
                 _v_reroute, _a_reroute),
    ScenarioType("capacity_change", "Capacity change", "What if this link were upgraded (or downgraded)?",
                 [{"name": "link_id", "label": "Link", "type": "link", "required": True},
                  {"name": "capacity_mbps", "label": "New capacity (Mbps)", "type": "number", "min": 1, "required": True}],
                 _v_capacity, _a_capacity),
    ScenarioType("access_control_rule", "Access control rule",
                 "Block some traffic with a firewall or access-control rule and see the effect.",
                 FILTER_FIELDS, _v_acl, _a_acl),
    ScenarioType("qos_policy", "QoS policy",
                 "Limit a traffic class (for example video) to a maximum rate, on one link or everywhere.",
                 [{"name": "cls", "label": "Traffic class", "type": "class", "required": True},
                  {"name": "limit_mbps", "label": "Limit (Mbps)", "type": "number", "min": 0.1, "required": True},
                  {"name": "link_id", "label": "On link (empty = everywhere)", "type": "link", "required": False},
                  {"name": "source_zone", "label": "From zone", "type": "zone", "required": False}],
                 _v_qos, _a_qos),
    ScenarioType("add_link", "Add a link", "What if a new connection were installed between two devices?",
                 [{"name": "source_id", "label": "From device", "type": "device", "required": True},
                  {"name": "dest_id", "label": "To device", "type": "device", "required": True},
                  {"name": "capacity_mbps", "label": "Capacity (Mbps)", "type": "number", "min": 1, "required": True}],
                 _v_add_link, _a_add_link, tier="could"),
]}


def get(key: str) -> ScenarioType:
    try:
        return REGISTRY[key]
    except KeyError:
        raise ScenarioError(f"Unknown scenario type '{key}'.") from None
