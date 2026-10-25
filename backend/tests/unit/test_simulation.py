"""The simulation engine (process 5.0): every scenario type against hand-calculated results.

Small network (tests/conftest.py SMALL): ACC -100 Mbps- DIST, DIST dual-homed to CORE1/CORE2,
both cores to the internet gateway GW, server SRV on CORE1. Demands:
  web: ACC -> internet, 50 Mbps, 80 % downstream
  app: ACC -> SRV, 20 Mbps, 50 % downstream
So the DIST-ACC link carries 40 + 10 = 50 Mbps towards ACC: 50 % of 100 Mbps.
"""
import copy
import json

import pytest

from digital_twin.network_model import TwinDemand
from digital_twin.simulation_engine import REGISTRY, ScenarioError, run_scenario
from tests.conftest import model_for


@pytest.fixture
def setup(small):
    model = model_for(small)
    names = {data["name"]: n for n, data in model.graph.nodes(data=True)}
    links = {model.link_label(i): i for i in model.link_ids()}
    for i in model.link_ids():
        model.link(i)["status"] = "up"
    for n in model.graph.nodes:
        model.device(n)["status"] = "up"
    model.demands = [TwinDemand(names["ACC"], None, "web", 50.0, 0.8),
                     TwinDemand(names["ACC"], names["SRV"], "app", 20.0, 0.5)]
    return model, names, links


def by_link(outcome):
    return {lk.label: lk for lk in outcome.links}


def test_registry_covers_every_scenario_type():
    assert set(REGISTRY) == {"traffic_increase", "link_failure", "device_failure", "routing_change",
                             "reroute_traffic", "capacity_change", "access_control_rule", "qos_policy", "add_link"}
    assert all(REGISTRY[k].describe()["fields"] or k == "access_control_rule" for k in REGISTRY)


def test_baseline_matches_hand_calculation(setup):
    model, _, links = setup
    out = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 100})
    assert by_link(out)["DIST <-> ACC"].before_pct == pytest.approx(50.0)
    assert by_link(out)["CORE1 <-> DIST"].before_pct == pytest.approx(2.0 + 1.0)  # 20 web + 10 app down / 1000


def test_capacity_upgrade_relieves_load(setup):
    model, _, links = setup
    out = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 1000})
    assert by_link(out)["DIST <-> ACC"].after_pct == pytest.approx(5.0)


def test_traffic_increase_creates_a_bottleneck(setup):
    model, _, links = setup
    out = run_scenario(model, "traffic_increase", {"percent": 100, "cls": "web"})
    acc = by_link(out)["DIST <-> ACC"]
    assert acc.after_pct == pytest.approx(90.0)          # 80 web + 10 app
    assert links["DIST <-> ACC"] in out.created
    assert "New bottleneck" in out.summary


def test_summary_uses_the_dashboard_words_and_number_formats(setup):
    """Normal / Warning / Critical rather than colours, '50.0%' and '+40.0 pts' with a real minus sign."""
    model, _, links = setup
    minus = chr(0x2212)
    upgrade = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 1000})
    assert ("The busiest link would be DIST <-> ACC at 5.0% (Normal), compared with 50.0% before the change."
            in upgrade.summary)
    assert f"Biggest changes: DIST <-> ACC {minus}45.0 pts." in upgrade.summary
    busier = run_scenario(model, "traffic_increase", {"percent": 100, "cls": "web"})
    assert "at 90.0% (Critical), compared with 50.0% before the change." in busier.summary
    assert "New bottleneck: DIST <-> ACC (90.0%)." in busier.summary and "DIST <-> ACC +40.0 pts" in busier.summary


def test_summary_names_the_link_that_was_busiest_before_when_it_moves(setup):
    """The busiest link after a change is set against the link that was busiest before, by name."""
    model, _, links = setup
    out = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 10000})
    assert ("The busiest link would be CORE1 <-> DIST at 3.0% (Normal). "
            "Before the change the busiest was DIST <-> ACC at 50.0%.") in out.summary


def test_link_failure_reroutes_over_the_other_core(setup):
    model, _, links = setup
    out = run_scenario(model, "link_failure", {"link_id": links["CORE1 <-> DIST"]})
    after = by_link(out)
    assert after["CORE1 <-> DIST"].after_pct == 0.0
    assert after["CORE1 <-> DIST"].status_after == "down"
    assert after["CORE2 <-> DIST"].after_pct == pytest.approx(5.0)   # all 40 web + 10 app down
    assert out.isolated_devices == []


def test_device_failure_isolates_the_access_switch(setup):
    model, names, _ = setup
    out = run_scenario(model, "device_failure", {"device_id": names["DIST"]})
    assert out.isolated_devices == [names["ACC"]]
    assert out.undeliverable_mbps_after == pytest.approx(70.0)
    assert "lose connectivity" in out.summary


def test_routing_change_moves_traffic(setup):
    model, _, links = setup
    out = run_scenario(model, "routing_change",
                       {"link_costs": [{"link_id": links["CORE1 <-> DIST"], "cost": 1000}]})
    after = by_link(out)
    assert after["CORE1 <-> DIST"].after_pct == 0.0
    assert after["CORE2 <-> DIST"].after_pct == pytest.approx(5.0)


def test_reroute_traffic_avoids_the_chosen_link(setup):
    model, names, links = setup
    out = run_scenario(model, "reroute_traffic", {"source_id": names["ACC"], "dest": "internet",
                                                  "avoid_link_ids": [links["CORE1 <-> DIST"]]})
    after = by_link(out)
    assert after["CORE2 <-> DIST"].after_pct == pytest.approx(4.0 + 0.0)  # web only: 40 down
    assert after["CORE1 <-> DIST"].after_pct == pytest.approx(1.0)        # app still uses CORE1


def test_access_control_rule_blocks_matching_traffic(setup):
    model, _, _ = setup
    out = run_scenario(model, "access_control_rule", {"cls": "web"})
    assert by_link(out)["DIST <-> ACC"].after_pct == pytest.approx(10.0)


def test_qos_policy_caps_a_class(setup):
    model, _, _ = setup
    out = run_scenario(model, "qos_policy", {"cls": "web", "limit_mbps": 25})
    assert by_link(out)["DIST <-> ACC"].after_pct == pytest.approx(30.0)   # 20 web down + 10 app down


def test_qos_policy_on_one_link(setup):
    model, _, links = setup
    out = run_scenario(model, "qos_policy", {"cls": "web", "limit_mbps": 25, "link_id": links["DIST <-> ACC"]})
    assert by_link(out)["DIST <-> ACC"].after_pct == pytest.approx(30.0)


def test_add_link_carries_traffic(setup):
    model, names, _ = setup
    out = run_scenario(model, "add_link", {"source_id": names["CORE2"], "dest_id": names["SRV"],
                                           "capacity_mbps": 1000})
    new = next(lk for lk in out.links if lk.link_id < 0)
    assert new.after_pct > 0


def test_live_model_is_never_modified(setup):
    model, names, links = setup
    before_graph = copy.deepcopy(dict(model.graph.edges.items())), copy.deepcopy(dict(model.graph.nodes.items()))
    before_demands = list(model.demands)
    for key, params in [("link_failure", {"link_id": links["DIST <-> ACC"]}),
                        ("device_failure", {"device_id": names["CORE1"]}),
                        ("capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 10}),
                        ("access_control_rule", {"cls": "web"}),
                        ("traffic_increase", {"percent": 300}),
                        ("add_link", {"source_id": names["CORE2"], "dest_id": names["SRV"], "capacity_mbps": 1000})]:
        run_scenario(model, key, params)
    assert (dict(model.graph.edges.items()), dict(model.graph.nodes.items())) == before_graph
    assert model.demands == before_demands
    assert all(i > 0 for i in model.link_ids())


@pytest.mark.parametrize("key, params, message", [
    ("link_failure", {}, "choose a link"),
    ("link_failure", {"link_id": 999}, "not part of the network"),
    ("traffic_increase", {"percent": 1000}, "at most 500"),
    ("traffic_increase", {"percent": "lots"}, "must be a number"),
    ("qos_policy", {"limit_mbps": 5}, "traffic class"),
    ("access_control_rule", {}, "which traffic"),
    ("reroute_traffic", {"source_id": 1, "dest": "internet"}, "at least one link"),
    ("add_link", {"source_id": 1, "dest_id": 1, "capacity_mbps": 10}, "two different devices"),
    ("no_such_type", {}, "Unknown scenario type"),
])
def test_invalid_parameters_give_clear_messages(setup, key, params, message):
    model, _, _ = setup
    with pytest.raises(ScenarioError, match=message):
        run_scenario(model, key, params)


def test_calibration_absorbs_systematic_model_error(setup):
    model, _, links = setup
    # measured utilisation 10 % higher than modelled on every busy link (e.g. protocol overhead)
    model.link(links["DIST <-> ACC"])["utilisation_pct"] = 55.0
    for label in ["CORE1 <-> DIST", "CORE2 <-> DIST", "GW <-> CORE1", "GW <-> CORE2", "CORE1 <-> SRV"]:
        model.link(links[label])["utilisation_pct"] = 10.0  # below 5 % modelled: not used for calibration
    out = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 100})
    assert out.calibration_factor == 1.0   # fewer than five busy links: no calibration
    assert out.model_fidelity_mae_pct is not None


def test_forecast_basis_scales_demands(setup):
    model, _, links = setup
    model.link(links["DIST <-> ACC"])["utilisation_pct"] = 50.0
    out = run_scenario(model, "capacity_change", {"link_id": links["DIST <-> ACC"], "capacity_mbps": 100},
                       predicted_pct={links["DIST <-> ACC"]: 100.0}, basis="forecast +30 min")
    assert by_link(out)["DIST <-> ACC"].before_pct == pytest.approx(100.0)
    assert out.basis == "forecast +30 min"


def test_recommendations_for_a_link_with_no_alternative_path(setup):
    """DIST-ACC is a single point of failure: no routing fix can help, so QoS is the immediate fix
    and an upgrade is planning advice."""
    from digital_twin.simulation_engine import recommend
    model, _, links = setup
    target = links["DIST <-> ACC"]
    model.link(target)["utilisation_pct"] = 50.0
    recs = recommend(model, target, predicted_pct={target: 95.0}, basis="forecast +15 min")
    kinds = [(r.scenario_type, r.kind) for r in recs]
    assert ("routing_change", "immediate") not in kinds       # traffic has nowhere else to go
    assert ("qos_policy", "immediate") in kinds
    assert kinds[-1] == ("capacity_change", "planning")       # upgrades listed last, separately
    qos = next(r for r in recs if r.scenario_type == "qos_policy")
    assert qos.target_after_pct < 90


def test_a_fix_that_takes_nothing_off_the_link_is_never_recommended(setup):
    """Found by E4: raising the routing cost of a link with no alternative path moves no traffic,
    yet it was recommended first because the forecast load (85 %) was already below 90 %.
    Every immediate fix is now also tested with the link at full load."""
    from digital_twin.simulation_engine import recommend
    from digital_twin.simulation_engine.recommendations import STRESS_PCT
    model, _, links = setup
    target = links["DIST <-> ACC"]                  # the only path to ACC
    model.link(target)["utilisation_pct"] = 50.0
    recs = recommend(model, target, predicted_pct={target: 85.0}, basis="forecast +30 min")
    assert "routing_change" not in {r.scenario_type for r in recs}
    for r in recs:
        assert r.outcome.basis == "forecast +30 min"           # what is shown stays the forecast run
        if r.kind == "immediate":
            stressed = run_scenario(model, r.scenario_type, r.parameters,
                                    predicted_pct={target: STRESS_PCT}, basis="stress")
            assert next(lk for lk in stressed.links if lk.link_id == target).after_pct < 90


def test_recommendations_prefer_least_disruptive_fix(setup):
    from digital_twin.simulation_engine import recommend
    model, _, links = setup
    target = links["CORE1 <-> DIST"]          # has an alternative path through CORE2
    model.link(target)["utilisation_pct"] = 3.0
    recs = recommend(model, target, predicted_pct={target: 95.0})
    immediate = [r for r in recs if r.kind == "immediate"]
    assert immediate and immediate[0].scenario_type == "routing_change"
    assert all(not r.outcome.created for r in recs)


def test_result_fits_the_simulation_result_table(setup):
    model, _, links = setup
    out = run_scenario(model, "traffic_increase", {"percent": 100, "cls": "web"})
    json.dumps(out.result_summary())
    assert out.predicted_utilisation()[str(links["DIST <-> ACC"])] == pytest.approx(90.0)
    assert out.bottleneck_links()[0]["link_id"] == links["DIST <-> ACC"]
