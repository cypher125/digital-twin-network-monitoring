"""Integration tests against PostgreSQL: the six tables, persistence, simulation jobs and roles.

Run with DATABASE_URL pointing at a PostgreSQL server (the local fallback or a Neon branch);
pytest-django creates and removes a separate test database.
"""
import json
import threading
from datetime import UTC, datetime, timedelta
from io import StringIO

import numpy as np
import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.accounts.roles import (
    JUNIOR,
    SENIOR,
    SYSTEM_USERNAME,
    ensure_roles,
    ensure_system_user,
    role_of,
)
from apps.twin.models import (
    MonitoringRecord,
    NetworkDevice,
    NetworkLink,
    Prediction,
    RunStatus,
    SimulationResult,
    SimulationScenario,
)
from apps.twin.topology_import import import_topology, read_topology_file
from data_collection.preprocessing import CleanBatch, DeviceReading, LinkReading
from digital_twin.network_model import StatusChange, TwinDemand
from digital_twin.runtime import persistence, simulation_jobs
from digital_twin.runtime.forecasting import link_static
from tests.conftest import CAMPUS

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
def campus_db():
    report = import_topology(read_topology_file(CAMPUS))
    assert report.ok, report.errors
    return report


def device(name):
    return NetworkDevice.objects.get(name=name)


def link(a, b):
    return NetworkLink.objects.get(source_device__name=a, dest_device__name=b)


# ------------------------------------------------------------- topology
def test_topology_import_creates_devices_links_and_configuration(campus_db):
    assert campus_db.devices_created == 34 and campus_db.links_created == 43
    gateway = device("ISP-A-GW")
    assert gateway.device_type == "wan_gateway"
    assert gateway.configuration["internet_egress"] is True
    assert gateway.configuration["zone"] == "CORE"
    assert link("ISP-B-GW", "EDGE-RTR-01").routing_cost == 10


def test_topology_import_is_idempotent(campus_db):
    again = import_topology(read_topology_file(CAMPUS))
    assert again.devices_created == 0 and again.devices_updated == 34
    assert NetworkLink.objects.count() == 43


@pytest.mark.parametrize("raw, message", [
    ({"devices": [{"name": "A", "type": "router"}, {"name": "A", "type": "router"}]}, "duplicate name"),
    ({"devices": [{"name": "A", "type": "toaster"}]}, "type must be one of"),
    ({"devices": [{"name": "A", "type": "router"}], "links": [["A", "B", 10]]}, "unknown device B"),
    ({"devices": [{"name": "A", "type": "router"}, {"name": "B", "type": "router"}],
      "links": [["A", "B", -5]]}, "positive number"),
    ({"devices": [{"name": "A", "type": "router", "ip": "999.1.1.1"}]}, "invalid IP"),
])
def test_topology_import_refuses_bad_files(raw, message):
    report = import_topology(raw)
    assert not report.ok and any(message in e for e in report.errors)
    assert NetworkDevice.objects.count() == 0      # nothing written


def test_dry_run_writes_nothing(campus_db):
    report = import_topology({"devices": [{"name": "NEW-SW", "type": "switch"}]}, dry_run=True)
    assert report.ok and report.devices_created == 1
    assert not NetworkDevice.objects.filter(name="NEW-SW").exists()


def test_import_skips_links_to_a_retired_device(campus_db):
    """The import sets no status, so a new link to a retired device would be in service: it is reported instead."""
    NetworkDevice.objects.filter(name="AP-HOSTEL-02").update(status="decommissioned")
    report = import_topology({"devices": [{"name": "AP-HOSTEL-02", "type": "access_point"},
                                          {"name": "ACC-HOSTEL-01", "type": "switch"}],
                              "links": [["ACC-HOSTEL-01", "AP-HOSTEL-02", 100]]})
    assert report.ok and report.links_created == 0 and report.links_updated == 0
    assert report.links_skipped == ["ACC-HOSTEL-01 <-> AP-HOSTEL-02: not imported, because AP-HOSTEL-02 is "
                                    "decommissioned"]
    assert not NetworkLink.objects.filter(source_device__name="ACC-HOSTEL-01", dest_device__name="AP-HOSTEL-02").exists()


def test_import_says_when_the_engine_needs_a_restart(campus_db):
    """Map positions are read from the store by the dashboard; everything else the engine loads at its start."""
    assert campus_db.restart_needed                                       # devices and links created
    raw = read_topology_file(CAMPUS)
    assert not import_topology(raw).restart_needed                       # the same file again
    raw["devices"][0]["position"] = [0, 0]
    assert not import_topology(raw).restart_needed                       # a device moved on the map
    raw["devices"][0]["location"] = "Server room 2"
    assert import_topology(raw).restart_needed


def test_command_line_import_tells_a_running_engine_and_lists_skipped_links(campus_db, tmp_path):
    """Like an import through the dashboard, setup.ps1's import bumps the count a running engine compares with."""
    start = persistence.topology_generation()
    out = StringIO()
    call_command("import_topology", str(CAMPUS), stdout=out)
    assert persistence.topology_generation() == start and "no engine restart is needed" in out.getvalue()
    NetworkDevice.objects.filter(name="AP-HOSTEL-02").update(status="decommissioned")
    raw = read_topology_file(CAMPUS)
    raw["links"][0][2] = 400                                              # the ISP-A uplink upgraded
    changed = tmp_path / "campus.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    call_command("import_topology", str(changed), "--dry-run", stdout=StringIO())
    assert persistence.topology_generation() == start                    # a check changes nothing
    out = StringIO()
    call_command("import_topology", str(changed), stdout=out)
    assert persistence.topology_generation() == start + 1
    assert "DIST-HOSTEL <-> AP-HOSTEL-02: not imported, because AP-HOSTEL-02 is decommissioned." in out.getvalue()
    assert "once it is restarted" in out.getvalue()


# ------------------------------------------------------------ constraints
def test_monitoring_record_is_device_or_link_never_both(campus_db):
    with pytest.raises(IntegrityError), transaction.atomic():
        MonitoringRecord.objects.create(device=device("CORE-SW-01"), link=link("FW-01", "CORE-SW-01"), timestamp=T0)
    with pytest.raises(IntegrityError), transaction.atomic():
        MonitoringRecord.objects.create(timestamp=T0)


def test_duplicate_readings_are_impossible(campus_db):
    MonitoringRecord.objects.create(link=link("FW-01", "CORE-SW-01"), timestamp=T0, utilisation_pct=10)
    with pytest.raises(IntegrityError), transaction.atomic():
        MonitoringRecord.objects.create(link=link("FW-01", "CORE-SW-01"), timestamp=T0, utilisation_pct=11)


def test_utilisation_must_be_a_percentage(campus_db):
    with pytest.raises(IntegrityError), transaction.atomic():
        MonitoringRecord.objects.create(link=link("FW-01", "CORE-SW-01"), timestamp=T0, utilisation_pct=140)


def test_history_cannot_be_deleted_by_accident(campus_db):
    from django.db.models import ProtectedError
    MonitoringRecord.objects.create(link=link("FW-01", "CORE-SW-01"), timestamp=T0, utilisation_pct=10)
    with pytest.raises(ProtectedError):
        link("FW-01", "CORE-SW-01").delete()


# ------------------------------------------------------------ persistence
def test_history_loads_aligned_in_chunks_with_gaps_kept(campus_db):
    """Training and the engine read history a day at a time; the result must equal one big read."""
    a, b = link("FW-01", "CORE-SW-01"), link("FW-01", "CORE-SW-02")
    rows = []
    for minute in range(0, 3 * 24 * 60, 30):                       # every 30 min for 3 days
        moment = T0 + timedelta(minutes=minute)
        rows.append(MonitoringRecord(link=a, timestamp=moment, utilisation_pct=minute % 100, error_count=1))
        if minute != 600:                                          # one missing reading on link b
            rows.append(MonitoringRecord(link=b, timestamp=moment, utilisation_pct=50, error_count=None))
    MonitoringRecord.objects.bulk_create(rows)
    ids = [a.link_id, b.link_id]
    times, util, errors = persistence.load_history(ids, 1800, T0, chunk=timedelta(hours=7))  # uneven chunks
    assert len(times) == 144 and times[0] == T0.timestamp() and times[-1] - times[-2] == 1800
    assert util[:, 0].tolist() == [float(m % 100) for m in range(0, 3 * 24 * 60, 30)]
    assert np.isnan(util[20, 1]) and np.count_nonzero(np.isnan(util[:, 1])) == 1
    assert np.all(errors[:, 0] == 1) and np.all(np.isnan(errors[:, 1]))
    later = persistence.load_history(ids, 1800, T0 + timedelta(days=2))[0]
    assert later[0] == (T0 + timedelta(days=2)).timestamp() and len(later) == 48


def batch_for(index, moment, util=40.0):
    links = {lk.link_id: LinkReading(lk.link_id, "up", util / 2, util, util, 0) for lk in index.links.values()}
    devices = {d.device_id: DeviceReading(d.device_id, "up", cpu_util=12.0) for d in index.devices.values()}
    return CleanBatch(moment, moment, moment, 60.0, links, devices, None)


def test_write_cycle_stores_one_row_per_link_and_device(campus_db):
    index, model = persistence.build_model(70, 90, 10000)
    clean = batch_for(index, T0)
    changes = model.apply(clean)
    rows = persistence.write_cycle(clean, changes)
    assert rows == 43 + 34 == MonitoringRecord.objects.count()
    assert NetworkDevice.objects.filter(status="up").count() == 34   # status changes written to D1
    assert persistence.write_cycle(clean, []) == rows                # the same cycle again ...
    assert MonitoringRecord.objects.count() == rows                  # ... adds nothing


def test_the_twin_never_brings_a_retired_element_back(campus_db):
    """An up/down reading for a retired link or device must not overwrite 'decommissioned'."""
    target = link("DIST-HOSTEL", "AP-HOSTEL-02")
    NetworkLink.objects.filter(pk=target.pk).update(status="decommissioned")
    persistence.write_status_changes([StatusChange("link", target.link_id, "unknown", "up"),
                                      StatusChange("device", device("FW-01").device_id, "unknown", "up")])
    target.refresh_from_db()
    assert target.status == "decommissioned" and device("FW-01").status == "up"


def test_links_to_a_retired_device_are_left_out_of_the_model(campus_db):
    """A link left in service to a retired device must not stop the engine from starting."""
    NetworkDevice.objects.filter(name="AP-HOSTEL-02").update(status="decommissioned")   # its link stays "unknown"
    index, model = persistence.build_model(70, 90, 10000)
    assert len(index.devices) == 33 and len(index.links) == 42 == len(model.link_ends)
    assert set(model.graph.nodes) == {d.device_id for d in index.devices.values()}   # no bare nodes
    model.structural_bottlenecks()
    assert len(link_static(model, sorted(model.link_ends))) == 42


def test_capacity_change_reaches_the_topology_store(campus_db):
    index, model = persistence.build_model(70, 90, 10000)
    target = link("ISP-B-GW", "EDGE-RTR-01")
    clean = batch_for(index, T0)
    clean.capacity_changes = {target.link_id: 400.0}
    persistence.write_cycle(clean, model.apply(clean))
    target.refresh_from_db()
    assert target.capacity_mbps == 400.0


def test_model_starts_warm_from_the_latest_readings(campus_db):
    index, model = persistence.build_model(70, 90, 10000)
    for minutes, util in ((0, 30.0), (1, 55.0)):
        clean = batch_for(index, T0 + timedelta(minutes=minutes), util)
        persistence.write_cycle(clean, model.apply(clean))
    _, fresh = persistence.build_model(70, 90, 10000)
    some_link = next(iter(fresh.link_ends))
    assert fresh.link(some_link)["utilisation_pct"] == 55.0
    assert persistence.latest_timestamp() == T0 + timedelta(minutes=1)


def test_retention_is_measured_in_network_time(campus_db):
    index, model = persistence.build_model(70, 90, 10000)
    for day in (0, 20):
        clean = batch_for(index, T0 + timedelta(days=day))
        persistence.write_cycle(clean, model.apply(clean))
    some = link("FW-01", "CORE-SW-01")
    Prediction.objects.create(link=some, generated_at=T0, horizon_minutes=5, predicted_utilisation=10,
                              confidence_score=0.9, is_warning=False)
    removed = persistence.prune(T0 + timedelta(days=20), monitoring_days=14, prediction_days=2)
    assert removed == 77 + 1
    assert MonitoringRecord.objects.filter(timestamp__lt=T0 + timedelta(days=6)).count() == 0


def test_runtime_status_round_trip():
    persistence.write_status({"state": "running", "state_version": 7})
    assert persistence.read_status()["state_version"] == 7


def test_topology_generation_counts_changes_from_zero():
    assert persistence.topology_generation() == 0
    persistence.bump_topology_generation()
    persistence.bump_topology_generation()
    assert persistence.topology_generation() == 2


# -------------------------------------------------------- simulation jobs
@pytest.fixture
def senior():
    ensure_roles()
    user = User.objects.create_user("senior1", password="a-long-password-123")
    user.groups.add(Group.objects.get(name=SENIOR))
    return user


def queue(user, scenario_type, parameters, request=None):
    scenario = SimulationScenario.objects.create(created_by=user, scenario_name="test", scenario_type=scenario_type,
                                                 parameters=parameters)
    return SimulationResult.objects.create(scenario=scenario, run_by=user, result_summary={"request": request or {}})


def test_queued_simulation_is_run_and_stored(campus_db, senior):
    index, model = persistence.build_model(70, 90, 10000)
    model.demands = [TwinDemand(device("AP-HOSTEL-01").device_id, None, "video", 60.0, 0.95)]
    target = link("DIST-HOSTEL", "AP-HOSTEL-01")
    job = queue(senior, "capacity_change", {"link_id": target.link_id, "capacity_mbps": 1000})
    assert simulation_jobs.run_pending(model, threading.RLock()) == 1
    job.refresh_from_db()
    assert job.status == RunStatus.COMPLETED and job.executed_at is not None
    assert job.predicted_utilisation[str(target.link_id)] == pytest.approx(5.7, rel=0.01)   # 57 down / 1000
    assert "summary" in job.result_summary and job.result_summary["runtime_ms"] >= 0


def test_invalid_simulation_fails_with_a_clear_message(campus_db, senior):
    _, model = persistence.build_model(70, 90, 10000)
    job = queue(senior, "link_failure", {"link_id": 99999})
    simulation_jobs.run_pending(model, threading.RLock())
    job.refresh_from_db()
    assert job.status == RunStatus.FAILED
    assert "not part of the network" in job.result_summary["error"]


def test_forecast_basis_needs_forecasts(campus_db, senior):
    _, model = persistence.build_model(70, 90, 10000)
    job = queue(senior, "traffic_increase", {"percent": 10}, request={"basis": "forecast", "horizon_minutes": 30})
    simulation_jobs.run_pending(model, threading.RLock(), forecast=lambda h: None)
    job.refresh_from_db()
    assert job.status == RunStatus.FAILED and "No forecasts" in job.result_summary["error"]


# ------------------------------------------------------------------ roles
def test_roles_and_system_account():
    senior_group, junior_group = ensure_roles()
    assert senior_group.permissions.filter(codename="add_simulationscenario").exists()
    assert not senior_group.permissions.filter(codename__startswith="delete_").exists()
    assert set(junior_group.permissions.values_list("codename", flat=True)) == {
        f"view_{m}" for m in ("networkdevice", "networklink", "monitoringrecord", "prediction",
                              "simulationscenario", "simulationresult")}
    system = ensure_system_user()
    assert system.username == SYSTEM_USERNAME and not system.is_active and not system.has_usable_password()


def test_role_of(senior):
    junior = User.objects.create_user("junior1", password="a-long-password-123")
    junior.groups.add(Group.objects.get(name=JUNIOR))
    assert role_of(senior) == "senior" and role_of(junior) == "junior"
