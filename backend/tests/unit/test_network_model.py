"""The network model (process 3.0) and the twin's routing."""
import pytest

from data_collection.preprocessing import CleanBatch, DeviceReading, LinkReading
from digital_twin.network_model import TwinDemand, route_demands
from tests.conftest import model_for


@pytest.fixture
def model(small):
    return model_for(small)


def ids(model):
    names = {data["name"]: n for n, data in model.graph.nodes(data=True)}
    links = {model.link_label(link_id): link_id for link_id in model.link_ids()}
    return names, links


def test_graph_mirrors_topology(model):
    assert model.graph.number_of_nodes() == 6
    assert model.graph.number_of_edges() == 6
    names, _ = ids(model)
    assert model.device(names["GW"])["internet_egress"] is True


def test_apply_updates_state_and_reports_status_changes(model):
    from datetime import UTC, datetime
    names, links = ids(model)
    acc_link = links["DIST <-> ACC"]
    batch = CleanBatch(
        timestamp=datetime(2026, 10, 5, tzinfo=UTC), measured_at=datetime(2026, 10, 5, tzinfo=UTC),
        received_at=datetime(2026, 10, 5, tzinfo=UTC), interval_seconds=60,
        links={acc_link: LinkReading(acc_link, "up", 30.0, 60.0, 60.0, 0)},
        devices={names["ACC"]: DeviceReading(names["ACC"], "up", cpu_util=12.0)},
        demands=None,
    )
    changes = model.apply(batch)
    assert {(c.kind, c.new) for c in changes} == {("link", "up"), ("device", "up")}
    assert model.link(acc_link)["utilisation_pct"] == 60.0
    assert model.device(names["ACC"])["cpu_util"] == 12.0


@pytest.mark.parametrize("value, colour", [(10, "green"), (70, "yellow"), (89.9, "yellow"), (90, "red"), (None, "unknown")])
def test_health_colours_follow_thresholds(model, value, colour):
    assert model.health(value) == colour


def test_health_down_overrides(model):
    assert model.health(10, status="down") == "down"


def test_internet_demand_splits_equally_over_core(model):
    names, links = ids(model)
    demand = TwinDemand(names["ACC"], None, "web", 50.0, 0.8)
    loads = route_demands(model, [demand])
    assert loads.utilisation[links["DIST <-> ACC"]] == pytest.approx(40.0)  # 40 Mbps down on a 100 Mbps link
    assert loads.load_out[links["CORE1 <-> DIST"]] == pytest.approx(20.0)   # half of the downstream 40
    assert loads.load_out[links["CORE2 <-> DIST"]] == pytest.approx(20.0)


def test_failed_link_reroutes_and_isolation_is_reported(model):
    names, links = ids(model)
    model.set_status("link", links["CORE1 <-> DIST"], "down")
    loads = route_demands(model, [TwinDemand(names["ACC"], None, "web", 50.0, 0.8)])
    assert loads.load_out[links["CORE2 <-> DIST"]] == pytest.approx(40.0)
    model.set_status("link", links["DIST <-> ACC"], "down")
    loads = route_demands(model, [TwinDemand(names["ACC"], None, "web", 50.0, 0.8)])
    assert loads.undeliverable_mbps == pytest.approx(50.0)


def test_structural_bottlenecks_find_single_points_of_failure(model):
    names, links = ids(model)
    result = model.structural_bottlenecks()
    assert links["DIST <-> ACC"] in result["bridge_links"]
    assert links["CORE1 <-> SRV"] in result["bridge_links"]
    assert links["CORE1 <-> DIST"] not in result["bridge_links"]   # redundant path through CORE2
    assert names["DIST"] in result["articulation_devices"]


def test_copy_is_detached(model):
    names, links = ids(model)
    clone = model.copy()
    clone.set_status("link", links["DIST <-> ACC"], "down")
    assert model.link(links["DIST <-> ACC"])["status"] == "unknown"
