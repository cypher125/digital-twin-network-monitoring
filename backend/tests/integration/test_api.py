"""The REST API: authentication, the role matrix, the write rule, CSRF, and every endpoint's behaviour.

The permission tests walk the URL resolver, so no endpoint can be forgotten.
"""
import json
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.roles import JUNIOR, SENIOR, ensure_roles
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
from digital_twin.runtime import persistence
from tests.conftest import CAMPUS

pytestmark = pytest.mark.django_db
PASSWORD = "a-long-password-123"
API = "/api/v1/"
T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
PUBLIC = {"auth/csrf", "auth/login"}


@pytest.fixture(autouse=True)
def clear_api_cache():
    from apps.api.services import cache
    cache._data.clear()
    yield
    cache._data.clear()


@pytest.fixture
def campus():
    import_topology(read_topology_file(CAMPUS))
    persistence.write_status({"state": "running", "state_version": 1, "last_cycle": T0.isoformat(),
                              "last_received_at": datetime.now(UTC).isoformat(), "traffic_classes": ["web", "video"],
                              "source": {"mode": "live", "speed": 1.0, "cycle_seconds": 60}})
    links = list(NetworkLink.objects.all())
    for minutes in range(0, 120):
        moment = T0 - timedelta(minutes=minutes)
        MonitoringRecord.objects.bulk_create([MonitoringRecord(link=lk, timestamp=moment, utilisation_pct=40 + lk.link_id % 50,
                                                               traffic_in=10, traffic_out=20, error_count=0)
                                              for lk in links])
    Prediction.objects.bulk_create([Prediction(link=lk, generated_at=T0, horizon_minutes=h, predicted_utilisation=50,
                                               confidence_score=0.9, is_warning=False)
                                    for lk in links for h in (5, 10, 15, 30)])
    return links


def user_with(role: str, username: str) -> User:
    ensure_roles()
    user = User.objects.create_user(username, password=PASSWORD, is_staff=role == "senior")
    user.groups.add(Group.objects.get(name=SENIOR if role == "senior" else JUNIOR))
    return user


@pytest.fixture
def senior():
    return user_with("senior", "senior1")


@pytest.fixture
def junior():
    return user_with("junior", "junior1")


def logged_in(user: User) -> APIClient:
    client = APIClient()
    response = client.post(API + "auth/login", {"username": user.username, "password": PASSWORD}, format="json")
    assert response.status_code == 200, response.content
    return client


def api_routes() -> list[str]:
    """Every concrete API path (with a sample id for detail routes)."""
    out = []
    from apps.api.urls import router, urlpatterns
    for entry in urlpatterns:
        text = str(entry.pattern)
        if text and "<" not in text and text not in ("",):
            out.append(text)
    for prefix, _viewset, basename in router.registry:
        out += [prefix, f"{prefix}/1"]
        if basename in ("device", "link"):
            out.append(f"{prefix}/1/metrics")
        if basename == "link":
            out.append(f"{prefix}/1/forecast")
        if basename == "result":
            out.append(f"{prefix}/1/compare")
    return sorted(set(out))


# --------------------------------------------------------------- logging in
def test_every_endpoint_needs_a_login(campus):
    client = APIClient()
    for route in api_routes():
        if route in PUBLIC:
            continue
        response = client.get(API + route)
        assert response.status_code in (401, 403), f"{route} answered {response.status_code} without a login"


def test_login_is_csrf_protected(senior):
    client = APIClient(enforce_csrf_checks=True)
    refused = client.post(API + "auth/login", {"username": "senior1", "password": PASSWORD}, format="json")
    assert refused.status_code == 403                                   # no CSRF token
    token = client.get(API + "auth/csrf").json()["csrfToken"]
    accepted = client.post(API + "auth/login", {"username": "senior1", "password": PASSWORD}, format="json",
                           HTTP_X_CSRFTOKEN=token)
    assert accepted.status_code == 200
    assert accepted.json()["user"]["role"] == "senior"


def test_wrong_password_gets_a_clear_message(senior):
    response = APIClient().post(API + "auth/login", {"username": "senior1", "password": "nope"}, format="json")
    assert response.status_code == 400 and "Incorrect" in response.json()["detail"]


@override_settings(AXES_ENABLED=True)
def test_repeated_failures_lock_the_account(senior):
    client = APIClient()
    for _ in range(5):
        client.post(API + "auth/login", {"username": "senior1", "password": "wrong"}, format="json")
    locked = client.post(API + "auth/login", {"username": "senior1", "password": PASSWORD}, format="json")
    assert locked.status_code == 403 and "Too many failed attempts" in locked.json()["detail"]


def test_user_without_a_role_cannot_log_in():
    User.objects.create_user("nobody", password=PASSWORD)
    response = APIClient().post(API + "auth/login", {"username": "nobody", "password": PASSWORD}, format="json")
    assert response.status_code == 403


# ------------------------------------------------------------- role matrix
def test_junior_can_read_everything_but_change_nothing(campus, junior):
    client = logged_in(junior)
    for route in ["live", "topology", "alerts/active", "alerts/history", "scenario-types", "trends/links",
                  "trends/heatmap", "trends/capacity", "system/status", "settings", "devices", "links", "scenarios",
                  "results"]:
        assert client.get(API + route).status_code == 200, route
    link = campus[0]
    assert client.patch(API + f"links/{link.link_id}", {"capacity_mbps": 5}, format="json").status_code == 403
    assert client.post(API + "scenarios", {"scenario_name": "x", "scenario_type": "link_failure",
                                           "parameters": {"link_id": link.link_id}}, format="json").status_code == 403
    assert client.post(API + "topology/import", {"topology": {"devices": []}}, format="json").status_code == 403
    assert client.get(API + "users").status_code == 403


def test_senior_needs_recent_activity_to_make_changes(campus, senior):
    client = logged_in(senior)
    body = {"scenario_name": "ISP-B down", "scenario_type": "link_failure",
            "parameters": {"link_id": campus[1].link_id}}
    assert client.post(API + "scenarios", body, format="json").status_code == 201
    session = client.session
    session["last_activity"] = time.time() - 31 * 60                    # away for 31 minutes
    session.save()
    stale = client.post(API + "scenarios", body, format="json")
    assert stale.status_code == 403 and stale.json()["code"] == "reauthenticate"
    assert "confirm your password" in stale.json()["detail"]
    assert client.post(API + "auth/password", {"current_password": PASSWORD}, format="json").status_code == 200
    assert client.post(API + "scenarios", body, format="json").status_code == 201


def test_polls_do_not_count_as_activity(campus, senior):
    client = logged_in(senior)
    session = client.session
    session["last_activity"] = time.time() - 31 * 60
    session.save()
    client.get(API + "live", HTTP_X_POLL="1")                            # the dashboard polling
    stale = client.post(API + "scenarios", {"scenario_name": "x", "scenario_type": "link_failure",
                                            "parameters": {"link_id": campus[0].link_id}}, format="json")
    assert stale.status_code == 403 and stale.json()["code"] == "reauthenticate"


def test_reading_after_an_absence_does_not_unlock_changes(campus, senior):
    """Someone finding an unattended screen can look, but not click one page and then make changes."""
    client = logged_in(senior)
    assert client.get(API + "auth/me").json()["write_allowed"] is True
    session = client.session
    session["last_activity"] = time.time() - 31 * 60
    session.save()
    assert client.get(API + "topology").status_code == 200              # a page opened after 31 minutes away
    assert client.get(API + "auth/me").json()["write_allowed"] is False
    body = {"scenario_name": "x", "scenario_type": "link_failure", "parameters": {"link_id": campus[0].link_id}}
    stale = client.post(API + "scenarios", body, format="json")
    assert stale.status_code == 403 and stale.json()["code"] == "reauthenticate"
    assert client.post(API + "auth/password", {"current_password": PASSWORD}, format="json").status_code == 200
    assert client.get(API + "auth/me").json()["write_allowed"] is True
    assert client.post(API + "scenarios", body, format="json").status_code == 201


def test_junior_is_never_write_allowed(junior):
    assert logged_in(junior).get(API + "auth/me").json()["write_allowed"] is False


def test_password_checks_are_rate_limited(senior, monkeypatch):
    """django-axes guards the login form; auth/password needs its own limit against guessing."""
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"password": "3/hour"})
    cache.clear()
    client = logged_in(senior)
    codes = [client.post(API + "auth/password", {"current_password": "wrong"}, format="json").status_code
             for _ in range(4)]
    assert codes == [400, 400, 400, 429]
    cache.clear()


# ------------------------------------------------------------- audit trail
def test_sign_ins_changes_and_runs_are_audited(campus, senior, caplog):
    caplog.set_level("INFO", logger="dt.audit")
    APIClient().post(API + "auth/login", {"username": "senior1", "password": "wrong"}, format="json")
    client = logged_in(senior)
    scenario = client.post(API + "scenarios", {"scenario_name": "ISP-B down", "scenario_type": "link_failure",
                                               "parameters": {"link_id": campus[1].link_id}}, format="json").json()
    client.post(API + f"scenarios/{scenario['scenario_id']}/run", {}, format="json")
    client.patch(API + f"links/{campus[0].link_id}", {"capacity_mbps": 2000}, format="json")
    client.post(API + "auth/logout")
    lines = [r.getMessage() for r in caplog.records if r.name == "dt.audit"]
    actions = [line.split()[0] for line in lines]
    assert actions == ["login_failed", "login", "scenario_created", "simulation_requested", "link_updated", "logout"]
    assert all("user=senior1" in line for line in lines)
    assert not any("wrong" in line or PASSWORD in line for line in lines)   # passwords are never logged


# ------------------------------------------------------------- endpoints
def test_topology_payload(campus, junior):
    data = logged_in(junior).get(API + "topology").json()
    assert len(data["devices"]) == 34 and len(data["links"]) == 43
    link = data["links"][0]
    assert {"utilisation_pct", "health", "single_point_of_failure", "forecast", "warning"} <= set(link)
    assert any(lk["single_point_of_failure"] for lk in data["links"])   # access uplinks have no redundancy
    assert data["summary"]["links_total"] == 43 and data["thresholds"]["critical_pct"] == 90


def test_an_edit_shows_at_once_not_at_the_next_cycle(campus, senior):
    """Topology and scenario choices are cached per state version; an edit must still show straight away."""
    client = logged_in(senior)
    link = campus[0]
    client.get(API + "topology")
    client.get(API + "scenario-types")                                  # both cached for this state version
    assert client.patch(API + f"links/{link.link_id}", {"capacity_mbps": 2500}, format="json").status_code == 200
    shown = {lk["link_id"]: lk for lk in client.get(API + "topology").json()["links"]}
    assert shown[link.link_id]["capacity_mbps"] == 2500
    choices = {lk["link_id"]: lk for lk in client.get(API + "scenario-types").json()["choices"]["links"]}
    assert choices[link.link_id]["capacity_mbps"] == 2500


def test_a_device_with_links_in_service_cannot_be_retired(campus, senior):
    """Its links must be retired first, so the topology never has a link to a missing device."""
    client = logged_in(senior)
    ap = NetworkDevice.objects.get(name="AP-HOSTEL-02")
    uplink = NetworkLink.objects.get(source_device__name="DIST-HOSTEL", dest_device=ap)
    refused = client.patch(API + f"devices/{ap.device_id}", {"status": "decommissioned"}, format="json")
    assert refused.status_code == 400
    assert "1 link in service (DIST-HOSTEL <-> AP-HOSTEL-02)" in refused.json()["status"][0]
    assert client.patch(API + f"links/{uplink.link_id}", {"status": "decommissioned"}, format="json").status_code == 200
    assert client.patch(API + f"devices/{ap.device_id}", {"status": "decommissioned"}, format="json").status_code == 200
    back = client.patch(API + f"links/{uplink.link_id}", {"status": "up"}, format="json")   # its device is retired
    assert back.status_code == 400 and "AP-HOSTEL-02 is decommissioned" in back.json()["status"][0]
    topology = client.get(API + "topology").json()
    assert len(topology["devices"]) == 33 and len(topology["links"]) == 42
    assert ap.device_id not in {d["device_id"] for d in topology["devices"]}


def test_a_device_whose_links_lead_only_to_retired_devices_can_be_retired(campus, senior):
    """The check counts links as the dashboard shows them: a link whose other end was retired has left the network.

    (Retired before the links-first rule existed, or straight in the database: the admin site cannot edit devices.)"""
    NetworkDevice.objects.filter(name="DIST-HOSTEL").update(status="decommissioned")   # its links are left as they were
    client = logged_in(senior)
    ap = NetworkDevice.objects.get(name="AP-HOSTEL-02")
    shown = client.get(API + "topology").json()["links"]
    assert not [lk for lk in shown if ap.device_id in (lk["source_id"], lk["dest_id"])]   # the page offers to retire it
    assert client.patch(API + f"devices/{ap.device_id}", {"status": "decommissioned"}, format="json").status_code == 200


def test_a_link_left_in_service_to_a_retired_device_never_breaks_the_api(campus, junior):
    """For example a device retired before the links-first rule: the link is left out, not drawn to a missing node."""
    NetworkDevice.objects.filter(name="AP-HOSTEL-02").update(status="decommissioned")
    client = logged_in(junior)
    topology = client.get(API + "topology")
    assert topology.status_code == 200
    assert len(topology.json()["devices"]) == 33 and len(topology.json()["links"]) == 42
    assert client.get(API + "scenario-types").status_code == 200


def test_edits_and_imports_tell_the_engine_it_needs_a_restart(campus, senior):
    """The engine reports topology_changed when this shared count moves after it loaded the topology."""
    client = logged_in(senior)
    start = persistence.topology_generation()
    client.patch(API + f"links/{campus[0].link_id}", {"capacity_mbps": 2000}, format="json")
    assert persistence.topology_generation() == start + 1
    new_switch = {"devices": [{"name": "NEW-SW", "type": "switch"}]}
    client.post(API + "topology/import", {"topology": new_switch, "dry_run": True}, format="json")
    assert persistence.topology_generation() == start + 1                  # a dry run changes nothing
    assert client.post(API + "topology/import", {"topology": new_switch}, format="json").status_code == 200
    assert persistence.topology_generation() == start + 2


def test_moving_devices_on_the_map_needs_no_engine_restart(campus, senior):
    """Positions only feed the map, which reads them from the store; the engine never uses them."""
    client = logged_in(senior)
    client.get(API + "topology")                                            # cached before the import
    start = persistence.topology_generation()
    raw = read_topology_file(CAMPUS)
    for device in raw["devices"]:
        device["position"] = [device["position"][0] + 5, device["position"][1]]
    moved = client.post(API + "topology/import", {"topology": raw}, format="json")
    assert moved.status_code == 200 and moved.json()["restart_needed"] is False
    assert persistence.topology_generation() == start
    shown = {d["name"]: d["position"] for d in client.get(API + "topology").json()["devices"]}
    assert shown["FW-01"] == [425, 205]                                     # the map has them at once
    gateway = NetworkDevice.objects.get(name="ISP-A-GW")
    unchanged = client.patch(API + f"devices/{gateway.device_id}", {"location": gateway.location}, format="json")
    assert unchanged.status_code == 200 and persistence.topology_generation() == start   # a save that changes nothing
    raw["links"][0][2] = 400                                                # the ISP-A uplink upgraded
    upgraded = client.post(API + "topology/import", {"topology": raw}, format="json")
    assert upgraded.json()["restart_needed"] is True and persistence.topology_generation() == start + 1


def test_live_reports_state_version(campus, junior):
    data = logged_in(junior).get(API + "live").json()
    assert data["state_version"] == 1 and data["engine_state"] == "running" and data["stale"] is False
    assert data["poll_seconds"] == 1                                        # D28: the dashboard polls every second


def test_link_metrics_and_forecast(campus, junior):
    client = logged_in(junior)
    link = campus[0]
    metrics = client.get(API + f"links/{link.link_id}/metrics?hours=1").json()
    assert len(metrics["points"]) == 60
    bucketed = client.get(API + f"links/{link.link_id}/metrics?hours=12").json()
    assert 20 <= len(bucketed["points"]) <= 25                           # 5-minute buckets over 2 h of data
    forecast = client.get(API + f"links/{link.link_id}/forecast").json()
    assert [p["horizon_minutes"] for p in forecast["forecast"]] == [5, 10, 15, 30]


def test_scenario_lifecycle(campus, senior):
    client = logged_in(senior)
    target = NetworkLink.objects.get(source_device__name="DIST-HOSTEL", dest_device__name="AP-HOSTEL-01")
    bad = client.post(API + "scenarios", {"scenario_name": "x", "scenario_type": "capacity_change",
                                          "parameters": {"link_id": target.link_id}}, format="json")
    assert bad.status_code == 400 and "new capacity" in str(bad.json()["parameters"])
    unknown_class = client.post(API + "scenarios", {"scenario_name": "x", "scenario_type": "qos_policy",
                                                    "parameters": {"cls": "gaming", "limit_mbps": 5}}, format="json")
    assert unknown_class.status_code == 400 and "no traffic of class" in str(unknown_class.json())
    created = client.post(API + "scenarios", {"scenario_name": "Upgrade hostel AP", "scenario_type": "capacity_change",
                                              "parameters": {"link_id": target.link_id, "capacity_mbps": 1000}},
                          format="json")
    assert created.status_code == 201
    scenario_id = created.json()["scenario_id"]
    run = client.post(API + f"scenarios/{scenario_id}/run", {"basis": "current"}, format="json")
    assert run.status_code == 202 and run.json()["status"] == RunStatus.QUEUED
    assert client.patch(API + f"scenarios/{scenario_id}", {"scenario_name": "renamed"},
                        format="json").status_code == 409          # has results: cannot change
    copy = client.post(API + f"scenarios/{scenario_id}/copy")
    assert copy.status_code == 201 and copy.json()["runs"] == 0


def test_result_compare(campus, senior):
    client = logged_in(senior)
    scenario = SimulationScenario.objects.create(created_by=senior, scenario_name="s", scenario_type="link_failure",
                                                 parameters={"link_id": campus[0].link_id})
    result = SimulationResult.objects.create(scenario=scenario, status=RunStatus.COMPLETED, result_summary={
        "summary": "ok", "basis": "current", "created": [], "relieved": [],
        "links": [{"link_id": campus[0].link_id, "label": "a", "before_pct": 40.0, "after_pct": 0.0,
                   "observed_pct": 41.0, "status_after": "down", "overloaded": False}]})
    stored = client.get(API + f"results/{result.result_id}/compare").json()
    assert stored["links"][0]["change_pct"] == -40.0
    live = client.get(API + f"results/{result.result_id}/compare?against=live").json()
    assert live["against"] == "live" and live["links"][0]["baseline_pct"] is not None


def test_trends_capacity_and_export(campus, junior):
    client = logged_in(junior)
    summary = client.get(API + "trends/links?range=24h").json()
    assert len(summary["links"]) == 43 and summary["links"][0]["p95_pct"] is not None
    series = client.get(API + f"trends/links?range=24h&link={campus[0].link_id}").json()
    assert series["points"]
    assert client.get(API + "trends/links?link=abc").status_code == 400
    heatmap = client.get(API + "trends/heatmap").json()
    assert heatmap["cells"]
    network = client.get(API + "trends/network?hours=1").json()
    assert len(network["points"]) == 60 and network["points"][-1]["max_pct"] >= network["points"][-1]["avg_pct"]
    capacity = client.get(API + "trends/capacity").json()
    assert "links" in capacity
    export = client.get(API + "trends/export.csv?range=24h")
    assert export.status_code == 200 and export["Content-Type"].startswith("text/csv")


def test_capacity_planning_fits_complete_days_only(campus, junior):
    """Today's unfinished day (and a part-day at the start) would drag the fit: only full WAT days count."""
    link, wat = campus[0], ZoneInfo("Africa/Lagos")
    rows = []
    for day, pct in ((1, 50.0), (2, 55.0), (3, 60.0), (4, 65.0)):             # 1-4 October, every 30 minutes
        midnight = datetime(2026, 10, day, tzinfo=wat)
        rows += [MonitoringRecord(link=link, timestamp=midnight + timedelta(minutes=m), utilisation_pct=pct)
                 for m in range(0, 24 * 60, 30)]
    rows += [MonitoringRecord(link=link, timestamp=datetime(2026, 9, 30, 20, m, tzinfo=wat), utilisation_pct=99.0)
             for m in (0, 30)]                                                 # half an hour of a day: left out
    rows += [MonitoringRecord(link=link, timestamp=datetime(2026, 10, 5, 0, m, tzinfo=wat), utilisation_pct=5.0)
             for m in (0, 30)]                                                 # today, quiet night (T0 is 10:00 WAT)
    MonitoringRecord.objects.bulk_create(rows)
    capacity = logged_in(junior).get(API + "trends/capacity").json()
    assert [lk["link_id"] for lk in capacity["links"]] == [link.link_id]     # the others have only today's data
    row = capacity["links"][0]
    assert row["days_of_data"] == 4 and row["latest_day"] == "2026-10-04" and row["latest_daily_p95_pct"] == 65.0
    assert row["growth_pts_per_week"] == pytest.approx(35.0)                  # 5 points a day
    # counted from today (5 October, 70% on the line), not from the last full day: 90% on 9 October
    assert row["fitted_p95_now"] == pytest.approx(70.0)
    assert row["days_until_critical"] == 4.0 and row["projected_date"] == "2026-10-09"
    assert capacity["method"].startswith("Linear fit") and "14 days" not in capacity["method"]   # the page says it


def test_capacity_projection_leaves_out_a_crossing_decades_away():
    """A nearly flat line crosses 90% only after thousands of years, past the last date Python can hold."""
    from apps.api.views.trends import project
    days = [date(2026, 10, day) for day in (1, 2, 3, 4)]
    flat = project(days, [1.0, 1.00002, 1.00004, 1.00006], 90.0, today=date(2026, 10, 5))
    assert flat["growth_pts_per_week"] == pytest.approx(0.0, abs=0.001) and flat["days_until_critical"] is None
    rising = project(days, [50.0, 55.0, 60.0, 65.0], 90.0)                    # from the last day fitted
    assert rising["days_until_critical"] == 5.0


def test_network_trend_covers_up_to_14_days(campus, junior):
    """The Trends page's period (7 or 14 days) comes in hourly buckets; 14 days is the most."""
    client = logged_in(junior)
    week = client.get(API + "trends/network?hours=168").json()
    assert week["hours"] == 168 and week["bucket"] == "1 hour"
    assert len(week["points"]) == 3                       # two hours of readings, 07:01-09:00 UTC: three clock hours
    assert week["points"][-1]["max_pct"] >= week["points"][-1]["avg_pct"]
    assert client.get(API + "trends/network?hours=5000").json()["hours"] == 336
    assert client.get(API + "trends/network?hours=24").json()["bucket"] == "10 minutes"


def test_status_settings_and_schema(campus, senior):
    client = logged_in(senior)
    status = client.get(API + "system/status").json()
    assert status["database"]["size_bytes"] > 0 and status["engine"]["state"] == "running"
    rows = status["database"]["approximate_rows"]
    assert rows["network_device"] == 34 and rows["network_link"] == 43 and rows["simulation_scenario"] == 0
    assert {"network_device", "network_link", "simulation_scenario", "simulation_result"} <= set(
        status["database"]["exact_tables"])
    assert rows["monitoring_record"] == 43 * 120          # never analysed in a test database, so counted exactly
    configured = client.get(API + "settings").json()
    assert configured["critical_pct"] == 90 and configured["poll_seconds"] == 1
    assert client.get(API + "schema").status_code == 200
    assert client.get(API + "users").status_code == 200


def test_active_alerts_say_when_the_model_was_trained(campus, junior, settings, tmp_path):
    """The page shows the training time in WAT instead of the model's raw version name (NFR3)."""
    settings.TWIN = {**settings.TWIN, "MODEL_DIR": str(tmp_path)}
    version = "rf-full-20261018T205002239824Z"
    (tmp_path / version).mkdir()
    (tmp_path / version / "meta.json").write_text(json.dumps({"created_at": "2026-10-18T20:50:02+00:00"}),
                                                  encoding="utf-8")
    persistence.write_status({**persistence.read_status(),
                              "forecasting": {"active_model": version, "model_kind": "full", "active_alerts": []}})
    data = logged_in(junior).get(API + "alerts/active").json()
    assert data["model"] == version and data["model_trained_at"] == "2026-10-18T20:50:02+00:00"


def test_topology_import_dry_run(campus, senior):
    client = logged_in(senior)
    response = client.post(API + "topology/import",
                           {"topology": {"devices": [{"name": "NEW-SW", "type": "switch"}]}, "dry_run": True},
                           format="json")
    assert response.status_code == 200 and response.json()["devices_created"] == 1
    refused = client.post(API + "topology/import", {"topology": {"devices": [{"name": "X", "type": "nope"}]}},
                          format="json")
    assert refused.status_code == 400 and refused.json()["errors"]
