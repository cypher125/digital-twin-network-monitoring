"""The preprocessing module (process 2.0): counters to rates, validation and data-quality handling."""
from datetime import UTC, datetime, timedelta

import pytest

from data_collection.network_adapter import DeviceSample, FlowSample, InterfaceSample, RawBatch
from data_collection.preprocessing import (
    ClockWentBackwards,
    DeviceRef,
    LinkRef,
    Preprocessor,
    TopologyIndex,
    align_to_cycle,
)
from data_collection.preprocessing.preprocessor import COUNTER64, counter_delta

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
def topology() -> TopologyIndex:
    devices = {"A": DeviceRef(1, "A", "switch"), "B": DeviceRef(2, "B", "switch")}
    return TopologyIndex(devices, {10: LinkRef(10, "A", "B", 100.0)})


def batch(at, a_out, a_in, *, b_reachable=True, uptime=1_000_000, spike=False, flows=None, a_up=True):
    """A on its interface to B sends a_out octets and receives a_in octets (cumulative)."""
    a = DeviceSample("A", True, uptime, 20.0, (
        InterfaceSample("A", 1, "B", a_in + (10 ** 13 if spike else 0), a_out, 0, a_up, 100.0),))
    b = (DeviceSample("B", True, uptime, 10.0, (InterfaceSample("B", 1, "A", a_out, a_in, 0, a_up, 100.0),))
         if b_reachable else DeviceSample("B", False))
    return RawBatch("test", at, at, [a, b], flows or [], 60.0 if flows else 0.0)


def mbps_to_octets(mbps: float, seconds: float = 60) -> int:
    return int(mbps * 1e6 / 8 * seconds)


def test_counter_delta_handles_wrap_and_reset():
    assert counter_delta(100, 150, COUNTER64) == 50
    assert counter_delta(COUNTER64 - 10, 5, COUNTER64) == 15     # wrapped around
    assert counter_delta(10 ** 9, 10, COUNTER64) is None          # reset (device rebooted)


def test_rates_and_utilisation(topology):
    p = Preprocessor(topology, 60)
    first = p.process(batch(T0, 0, 0))
    assert first.links[10].utilisation_pct is None                # no previous counters yet
    second = p.process(batch(T0 + timedelta(minutes=1), mbps_to_octets(40), mbps_to_octets(70)))
    reading = second.links[10]
    assert reading.traffic_out == pytest.approx(40, rel=1e-6)    # A -> B
    assert reading.traffic_in == pytest.approx(70, rel=1e-6)
    assert reading.utilisation_pct == pytest.approx(70, rel=1e-6)  # the busier direction
    assert reading.status == "up"
    assert second.devices[1].cpu_util == 20.0


def test_spike_is_rejected_and_baseline_kept(topology):
    p = Preprocessor(topology, 60)
    p.process(batch(T0, 0, 0))
    spiked = p.process(batch(T0 + timedelta(minutes=1), mbps_to_octets(10), mbps_to_octets(10), spike=True))
    assert spiked.quality.spikes_rejected == 1
    # the B side still gives the link a reading
    assert spiked.links[10].utilisation_pct == pytest.approx(10, rel=1e-6)
    later = p.process(batch(T0 + timedelta(minutes=2), mbps_to_octets(30, 120), mbps_to_octets(30, 120)))
    # measured from the last good A reading, across both minutes
    assert later.links[10].utilisation_pct == pytest.approx(30, rel=1e-6)


def test_reboot_drops_the_interval(topology):
    p = Preprocessor(topology, 60)
    p.process(batch(T0, mbps_to_octets(50, 600), mbps_to_octets(50, 600), uptime=1_000_000))
    rebooted = p.process(batch(T0 + timedelta(minutes=1), mbps_to_octets(5), mbps_to_octets(5), uptime=3000))
    assert rebooted.quality.counter_resets >= 1
    assert rebooted.links[10].utilisation_pct is None


def test_clock_going_backwards_is_refused(topology):
    p = Preprocessor(topology, 60, last_timestamp=T0 + timedelta(minutes=5))
    with pytest.raises(ClockWentBackwards):
        p.process(batch(T0, 0, 0))


def test_same_cycle_twice_is_ignored(topology):
    p = Preprocessor(topology, 60)
    p.process(batch(T0 + timedelta(seconds=5), 0, 0))
    assert p.process(batch(T0 + timedelta(seconds=40), 1000, 1000)) is None


def test_unreachable_device_marks_link_down(topology):
    p = Preprocessor(topology, 60)
    p.process(batch(T0, 0, 0))
    clean = p.process(batch(T0 + timedelta(minutes=1), 0, 0, b_reachable=False))
    assert clean.devices[2].status == "down"
    assert clean.links[10].status == "down"


def test_flows_become_demands(topology):
    p = Preprocessor(topology, 60)
    flows = [FlowSample("A", "B", "web", mbps_to_octets(2), mbps_to_octets(8)),
             FlowSample("A", "INTERNET", "web", mbps_to_octets(1), 0),
             FlowSample("Z", "B", "web", 10, 10)]
    clean = p.process(batch(T0, 0, 0, flows=flows))
    assert clean.quality.flows_rejected == 1
    demand = next(d for d in clean.demands if d.dest_id == 2)
    assert demand.mbps == pytest.approx(10, rel=1e-6)
    assert demand.down_ratio == pytest.approx(0.8)
    assert any(d.dest_id is None for d in clean.demands)


def test_align_to_cycle():
    assert align_to_cycle(T0 + timedelta(seconds=59), 60) == T0


def test_capacity_change_reported_by_devices_is_adopted(topology):
    """The link was upgraded: both ends now report 1000 Mbps instead of the stored 100 Mbps."""
    def upgraded(at, out_octets, in_octets):
        a = DeviceSample("A", True, 1_000_000, 20.0, (InterfaceSample("A", 1, "B", in_octets, out_octets, 0, True, 1000.0),))
        b = DeviceSample("B", True, 1_000_000, 10.0, (InterfaceSample("B", 1, "A", out_octets, in_octets, 0, True, 1000.0),))
        return RawBatch("test", at, at, [a, b])

    p = Preprocessor(topology, 60)
    p.process(upgraded(T0, 0, 0))
    clean = p.process(upgraded(T0 + timedelta(minutes=1), mbps_to_octets(200), mbps_to_octets(50)))
    assert clean.capacity_changes == {}                       # adopted on the first poll already
    assert topology.links[10].capacity_mbps == 1000.0
    assert clean.links[10].utilisation_pct == pytest.approx(20.0, rel=1e-6)   # 200 of 1000, not of 100


def test_capacity_change_is_reported_once(topology):
    p = Preprocessor(topology, 60)
    first = p.process(batch(T0, 0, 0))
    assert first.capacity_changes == {} and first.quality.capacity_changes == 0
    a = DeviceSample("A", True, 1_000_000, 20.0, (InterfaceSample("A", 1, "B", 0, 0, 0, True, 1000.0),))
    changed = p.process(RawBatch("test", T0 + timedelta(minutes=1), T0, [a]))
    assert changed.capacity_changes == {10: 1000.0}
    assert changed.quality.capacity_changes == 1
