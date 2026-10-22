"""Run a scenario on a detached copy of the network model (FR4, UC3, gap G3).

1. Copy the live model. The live model is never modified.
2. Route the current demands over the copy: the baseline.
3. Apply the change to a second copy and route again: the predicted state.
4. Compare: utilisation per link, bottlenecks created and relieved, devices cut
   off, traffic that can no longer be delivered, and a plain-language summary.

A calibration factor, the median of measured ÷ modelled utilisation over busy
links, absorbs systematic differences between the model and the network (for
example protocol overhead). It is applied to both baseline and change, so the
comparison is like for like.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

import networkx as nx

from digital_twin.network_model import (
    INTERNET,
    NetworkModel,
    RoutedLoads,
    TwinDemand,
    route_demands,
)

from .scenarios import get

MIN_CALIBRATION_SAMPLES = 5
STATUS_WORDS = {"green": "Normal", "yellow": "Warning", "red": "Critical"}   # the dashboard's words (D1)


@dataclass
class LinkOutcome:
    link_id: int
    label: str
    capacity_mbps: float
    observed_pct: float | None    # measured utilisation now
    before_pct: float             # modelled, without the change
    after_pct: float              # modelled, with the change
    delta_pct: float
    status_after: str
    overloaded: bool              # more traffic offered than the link can carry


@dataclass
class SimulationOutcome:
    scenario_type: str
    parameters: dict
    basis: str
    network_time: str | None
    thresholds: dict
    calibration_factor: float
    links: list[LinkOutcome]
    bottlenecks_before: list[int]
    bottlenecks_after: list[int]
    created: list[int]
    relieved: list[int]
    max_before: dict
    max_after: dict
    isolated_devices: list[int]
    undeliverable_mbps_before: float
    undeliverable_mbps_after: float
    model_fidelity_mae_pct: float | None
    notes: list[str] = field(default_factory=list)
    summary: str = ""

    def predicted_utilisation(self) -> dict[str, float]:
        """SimulationResult.predicted_utilisation: {link_id: %} after the change."""
        return {str(lk.link_id): round(lk.after_pct, 2) for lk in self.links}

    def bottleneck_links(self) -> list[dict]:
        """SimulationResult.bottleneck_links: links at or above the critical threshold after the change."""
        by_id = {lk.link_id: lk for lk in self.links}
        return [{"link_id": i, "label": by_id[i].label, "utilisation_pct": round(by_id[i].after_pct, 1)}
                for i in self.bottlenecks_after]

    def result_summary(self) -> dict:
        """SimulationResult.result_summary: everything needed to review or compare the run later."""
        data = asdict(self)
        data["links"] = [asdict(lk) for lk in self.links]
        return data


def _calibration(model: NetworkModel, routed: RoutedLoads) -> float:
    ratios = []
    for link_id in model.link_ends:
        edge = model.link(link_id)
        observed, modelled = edge["utilisation_pct"], routed.utilisation.get(link_id, 0.0)
        if observed is not None and edge["status"] != "down" and modelled >= 5.0:
            ratios.append(observed / modelled)
    if len(ratios) < MIN_CALIBRATION_SAMPLES:
        return 1.0
    return min(1.25, max(0.8, statistics.median(ratios)))


def forecast_demands(model: NetworkModel, demands: list[TwinDemand], routed: RoutedLoads,
                     predicted_pct: dict[int, float]) -> list[TwinDemand]:
    """Scale each demand by predicted ÷ current utilisation of the busiest link on its path.

    This turns per-link forecasts (prediction engine) into a forecast demand matrix
    (simulation engine). The approximation is recorded in the as-built notes and
    checked against the emulator in evaluation E4.
    """
    current = {}
    for link_id in model.link_ends:
        observed = model.link(link_id)["utilisation_pct"]
        current[link_id] = observed if observed is not None else routed.utilisation.get(link_id, 0.0)
    scaled = []
    for index, d in enumerate(demands):
        used = routed.link_paths.get(index)
        if not used:
            scaled.append(d)
            continue
        busiest = max(used, key=lambda link_id: current.get(link_id, 0.0))
        now, later = current.get(busiest, 0.0), predicted_pct.get(busiest)
        if later is None or now < 1.0:
            scaled.append(d)
            continue
        factor = min(5.0, max(0.2, later / now))
        scaled.append(TwinDemand(d.source_id, d.dest_id, d.cls, d.mbps * factor, d.down_ratio))
    return scaled


def _isolated(model: NetworkModel) -> list[int]:
    """Working devices that can no longer reach any internet gateway (or the core, if there is none)."""
    g = model.operational_graph()
    anchors = {n for n in model.egress_ids() if n in g}
    if not anchors:
        return []
    connected = set()
    for component in nx.connected_components(g):
        if component & anchors:
            connected |= component
    return sorted(n for n in g.nodes if n not in connected and n != INTERNET)


def _status_word(model: NetworkModel, pct: float) -> str:
    return STATUS_WORDS.get(model.health(pct), "")


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _pts(change: float) -> str:
    """A change in percentage points with a real minus sign (U+2212): '+10.1 pts', '−15.2 pts'."""
    return f"{round(change, 1) + 0.0:+.1f} pts".replace("-", "\u2212")


def run_scenario(model: NetworkModel, scenario_type: str, parameters: dict | None = None, *,
                 predicted_pct: dict[int, float] | None = None, basis: str = "current") -> SimulationOutcome:
    spec = get(scenario_type)
    params = spec.validate(dict(parameters or {}), model)
    critical = model.critical_pct

    base = model.copy()                       # G3: everything below works on copies
    current = route_demands(base, base.demands)
    calibration = _calibration(base, current)
    demands = list(base.demands)
    if predicted_pct:
        demands = forecast_demands(base, demands, current, predicted_pct)
        before = route_demands(base, demands)
    else:
        before = current

    changed = base.copy()
    change = spec.apply(changed, demands, params)
    after = route_demands(changed, change.demands, pinned=change.pinned)

    links: list[LinkOutcome] = []
    for link_id in changed.link_ends:
        edge = changed.link(link_id)
        b = before.utilisation.get(link_id, 0.0) * calibration
        a = after.utilisation.get(link_id, 0.0) * calibration if edge["status"] != "down" else 0.0
        observed = base.link(link_id)["utilisation_pct"] if link_id in base.link_ends else None
        links.append(LinkOutcome(link_id, changed.link_label(link_id), edge["capacity_mbps"], observed,
                                 round(b, 3), round(a, 3), round(a - b, 3), edge["status"], a > 100.0))

    b_before = sorted(lk.link_id for lk in links if lk.before_pct >= critical)
    b_after = sorted(lk.link_id for lk in links if lk.after_pct >= critical and lk.status_after != "down")
    created = sorted(set(b_after) - set(b_before))
    relieved = sorted(set(b_before) - set(b_after))
    top_before = max(links, key=lambda lk: lk.before_pct)
    top_after = max(links, key=lambda lk: lk.after_pct)

    fidelity = None
    if not predicted_pct:
        errors = [abs(lk.before_pct - lk.observed_pct) for lk in links
                  if lk.observed_pct is not None and lk.link_id in base.link_ends]
        fidelity = round(statistics.fmean(errors), 3) if errors else None

    outcome = SimulationOutcome(
        scenario_type=scenario_type,
        parameters=params,
        basis=basis,
        network_time=base.timestamp.isoformat() if base.timestamp else None,
        thresholds={"warning_pct": model.warning_pct, "critical_pct": critical},
        calibration_factor=round(calibration, 4),
        links=links,
        bottlenecks_before=b_before,
        bottlenecks_after=b_after,
        created=created,
        relieved=relieved,
        max_before={"link_id": top_before.link_id, "label": top_before.label, "pct": round(top_before.before_pct, 1)},
        max_after={"link_id": top_after.link_id, "label": top_after.label, "pct": round(top_after.after_pct, 1)},
        isolated_devices=_isolated(changed),
        undeliverable_mbps_before=round(before.undeliverable_mbps, 3),
        undeliverable_mbps_after=round(after.undeliverable_mbps, 3),
        model_fidelity_mae_pct=fidelity,
        notes=change.notes,
    )
    outcome.summary = summarise(changed, outcome)
    return outcome


def summarise(model: NetworkModel, o: SimulationOutcome) -> str:
    """A plain-language summary for administrators without data-science training (NFR3)."""
    by_id = {lk.link_id: lk for lk in o.links}
    parts = list(o.notes)
    after, before = o.max_after, o.max_before
    busiest = (f"The busiest link would be {after['label']} at {_pct(after['pct'])} "
               f"({_status_word(model, after['pct'])})")
    if before["link_id"] == after["link_id"]:
        parts.append(f"{busiest}, compared with {_pct(before['pct'])} before the change.")
    else:
        parts.append(f"{busiest}. Before the change the busiest was {before['label']} at {_pct(before['pct'])}.")
    if o.created:
        names = ", ".join(f"{by_id[i].label} ({_pct(by_id[i].after_pct)})" for i in o.created[:3])
        parts.append(f"New bottleneck{'s' if len(o.created) > 1 else ''}: {names}.")
    if o.relieved:
        names = ", ".join(by_id[i].label for i in o.relieved[:3])
        parts.append(f"Bottleneck{'s' if len(o.relieved) > 1 else ''} relieved: {names}.")
    if not o.created and not o.relieved:
        parts.append("No bottlenecks are created or relieved.")
    if o.isolated_devices:
        names = ", ".join(model.name_of(d) for d in o.isolated_devices[:5])
        parts.append(f"{len(o.isolated_devices)} device(s) would lose connectivity: {names}.")
    lost = o.undeliverable_mbps_after - o.undeliverable_mbps_before
    if lost > 0.05:
        parts.append(f"About {lost:.1f} Mbps of traffic could no longer be delivered.")
    movers = sorted((lk for lk in o.links if abs(lk.delta_pct) >= 5), key=lambda lk: -abs(lk.delta_pct))[:3]
    if movers:
        parts.append("Biggest changes: " + ", ".join(f"{lk.label} {_pts(lk.delta_pct)}" for lk in movers) + ".")
    return " ".join(parts)
