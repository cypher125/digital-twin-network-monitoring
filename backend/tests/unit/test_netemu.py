"""The network emulator: topology loading, traffic, routing, counters, failures and lab changes."""
from datetime import datetime, timedelta

import numpy as np
import pytest

from netemu.network import STEP_SECONDS, EmulatedNetwork
from netemu.topology import INTERNET, TopologyError, parse_topology
from tests.conftest import SMALL, START


def run_cycles(net: EmulatedNetwork, cycles: int) -> None:
    for _ in range(cycles * net.steps_per_cycle()):
        net.step()


def test_campus_topology_loads(campus):
    assert len(campus.devices) == 34
    assert len(campus.links) == 43
    assert set(campus.egress_devices) == {"ISP-A-GW", "ISP-B-GW"}


@pytest.mark.parametrize("mutate, message", [
    (lambda raw: raw["links"].append(["GW", "CORE1", 10]), "duplicate link"),
    (lambda raw: raw["links"].append(["GW", "NOPE", 10]), "unknown device"),
    (lambda raw: raw["zones"]["Z"]["access"].update({"ACC": 0.5}), "add up to 1"),
])
def test_invalid_topology_is_rejected(mutate, message):
    import copy
    raw = copy.deepcopy(SMALL)
    mutate(raw)
    with pytest.raises(TopologyError, match=message):
        parse_topology(raw)


def test_daytime_traffic_exceeds_night_traffic(campus):
    from netemu.traffic import TrafficModel
    model = TrafficModel(campus, START)
    weekday_morning = model.offered(START.replace(hour=10), 10).sum()
    weekday_night = model.offered(START.replace(hour=3), 10).sum()
    assert weekday_morning > 3 * weekday_night > 0


def test_ecmp_split_covers_each_routable_demand_once(small):
    net = EmulatedNetwork(small, START)
    for d in net.demands:
        assert net.routable[d.index]
    # every internet demand from ACC crosses the single access link exactly once in total
    acc_link = net.find_link("DIST", "ACC")
    shares = net.f_ab[acc_link] + net.f_ba[acc_link]
    assert np.allclose(shares, 1.0)
    # and is split over both core switches
    via_core1 = net.f_ab[net.find_link("CORE1", "DIST")] + net.f_ba[net.find_link("CORE1", "DIST")]
    via_core2 = net.f_ab[net.find_link("CORE2", "DIST")] + net.f_ba[net.find_link("CORE2", "DIST")]
    internet = [d.index for d in net.demands if d.dest == INTERNET]
    assert np.allclose(via_core1[internet] + via_core2[internet], 1.0)
    assert np.allclose(via_core1[internet], 0.5)


def test_counters_grow_and_cycles_close_on_schedule(small):
    net = EmulatedNetwork(small, START)
    before = net.if_out.copy()
    run_cycles(net, 3)
    assert net.cycle_seq == 3
    assert (net.if_out >= before).all()
    assert net.t == START + timedelta(seconds=3 * 60)
    snapshot = net.snapshot()
    assert snapshot["timestamp"] == net.truth[-1]["end"]  # readings taken at the cycle boundary


def test_truth_matches_counter_rates(small):
    net = EmulatedNetwork(small, START)
    run_cycles(net, 1)
    first = net.snapshot()
    run_cycles(net, 1)
    second = net.snapshot()
    truth = net.truth[-1]
    acc = net.find_link("DIST", "ACC")
    side_a = lambda snap: next(i for d in snap["devices"] if d["name"] == "DIST"  # noqa: E731
                               for i in d["interfaces"] if i["peer"] == "ACC")
    out_mbps = (side_a(second)["ifHCOutOctets"] - side_a(first)["ifHCOutOctets"]) * 8 / 60 / 1e6
    assert out_mbps == pytest.approx(truth["links"][acc]["mbps_ab"], rel=1e-6)


def test_link_failure_reroutes_after_convergence(small):
    net = EmulatedNetwork(small, START)
    link = net.find_link("CORE1", "DIST")
    net.fail_link(link)
    assert net.events[-1].type == "link_down"
    # until routing converges, traffic on the failed link is lost
    assert (net.f_ab[link] + net.f_ba[link]).sum() > 0
    for _ in range(int(30 / STEP_SECONDS)):
        net.step()
    assert (net.f_ab[link] + net.f_ba[link]).sum() == 0
    net.repair_link(link)
    assert net.events[-1].type == "link_up"


def test_device_reboot_resets_its_counters(small):
    net = EmulatedNetwork(small, START)
    run_cycles(net, 2)
    dist = net.dev_index["DIST"]
    net.fail_device(dist)
    assert [e.type for e in net.events][-1] == "link_down"
    net.repair_device(dist)
    side = 1 if net.ends[net.find_link("CORE1", "DIST"), 1] == dist else 0
    assert net.if_out[net.find_link("CORE1", "DIST"), side] == 0.0
    run_cycles(net, 1)
    reading = next(d for d in net.snapshot()["devices"] if d["name"] == "DIST")
    assert reading["sysUpTime"] < 61 * 100


def test_lab_changes_affect_the_real_network(small):
    net = EmulatedNetwork(small, START)
    acc = net.find_link("DIST", "ACC")
    run_cycles(net, 1)
    base = net.truth[-1]["links"][acc]["utilisation_pct"]
    net.apply_change({"type": "capacity_change", "link": ["DIST", "ACC"], "capacity_mbps": 1000})
    run_cycles(net, 1)
    upgraded = net.truth[-1]["links"][acc]["utilisation_pct"]
    assert upgraded == pytest.approx(base / 10, rel=0.05)
    net.apply_change({"type": "access_control_rule", "cls": "web"})
    run_cycles(net, 1)
    blocked = net.truth[-1]["links"][acc]["utilisation_pct"]
    assert blocked < upgraded
    net.reset_changes()
    run_cycles(net, 1)
    assert net.truth[-1]["links"][acc]["utilisation_pct"] == pytest.approx(base, rel=0.05)


def test_routing_change_moves_traffic(small):
    net = EmulatedNetwork(small, START)
    core1_dist = net.find_link("CORE1", "DIST")
    net.apply_change({"type": "routing_change", "link_costs": [{"link": ["CORE1", "DIST"], "cost": 1000}]})
    internet = [d.index for d in net.demands if d.dest == INTERNET]
    assert (net.f_ab[core1_dist, internet] + net.f_ba[core1_dist, internet]).sum() == 0


def test_flow_records_account_for_link_traffic(small):
    net = EmulatedNetwork(small, START)
    run_cycles(net, 1)
    cycle = net.flows[-1]
    octets = sum(r["octets_fwd"] + r["octets_rev"] for r in cycle["records"])
    acc = net.find_link("DIST", "ACC")
    truth = net.truth[-1]["links"][acc]
    # every demand crosses the access link, so flows add up to its traffic (no overhead in SMALL)
    assert octets * 8 / 60 / 1e6 == pytest.approx(truth["mbps_ab"] + truth["mbps_ba"], rel=1e-3)


def test_fork_gives_identical_independent_branches(small):
    """E4's paired runs: a forked network evolves identically until one branch is changed."""
    import copy
    net = EmulatedNetwork(small, START)
    run_cycles(net, 2)
    fork = copy.deepcopy(net)
    run_cycles(net, 3)
    run_cycles(fork, 3)
    assert net.truth[-1] == fork.truth[-1]                 # same traffic, same random draws
    fork.apply_change({"type": "capacity_change", "link": ["DIST", "ACC"], "capacity_mbps": 1000})
    run_cycles(net, 1)
    run_cycles(fork, 1)
    acc = net.find_link("DIST", "ACC")
    assert fork.truth[-1]["links"][acc]["utilisation_pct"] < net.truth[-1]["links"][acc]["utilisation_pct"]
    assert net.capacity[acc] == 100                         # the original is untouched


def test_start_must_have_a_time_zone(small):
    with pytest.raises(ValueError):
        EmulatedNetwork(small, datetime(2026, 10, 5))


def test_a_locked_clock_file_never_stops_the_network(small, tmp_path, monkeypatch, caplog):
    """On Windows a reader or a virus scanner can hold the clock file open for a moment (D26)."""
    import json
    import os

    from netemu.__main__ import clock_saver

    state = tmp_path / "clock.json"
    net = EmulatedNetwork(small, START)
    net.on_cycle.append(clock_saver(state))
    real_replace, calls = os.replace, {"n": 0}

    def flaky(src, dst):                       # locked twice, then free
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    run_cycles(net, 1)
    assert json.loads(state.read_text(encoding="utf-8"))["cycle_seq"] == net.cycle_seq

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(PermissionError(5, "Access is denied")))
    run_cycles(net, 1)                         # still locked: this save is skipped, the network goes on
    assert "could not save the network clock" in caplog.text
    assert json.loads(state.read_text(encoding="utf-8"))["cycle_seq"] == net.cycle_seq - 1
