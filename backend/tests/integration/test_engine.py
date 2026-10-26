"""The Digital Twin Engine end to end: emulator feed -> adapter -> preprocessing -> model -> database.

An emulator runs in this process behind its real HTTP feed, on a stepped clock, so the
twin reads it exactly as in operation, through the same adapter. Tests may import both
the emulator and the twin (the packages themselves may not).
"""
import threading
from datetime import UTC, datetime, timedelta

import pytest

from apps.twin.models import MonitoringRecord, NetworkLink, SimulationResult
from apps.twin.topology_import import import_topology, read_topology_file
from data_collection.network_adapter.telemetry_http import TelemetryHttpAdapter
from digital_twin.prediction_engine.alerts import Episode
from digital_twin.runtime import persistence
from digital_twin.runtime.engine import EngineSettings, TwinEngine
from netemu.network import EmulatedNetwork
from netemu.server import Runtime, serve
from netemu.topology import load_topology
from tests.conftest import CAMPUS

pytestmark = pytest.mark.django_db
MONDAY_9_WAT = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


@pytest.fixture
def emulator():
    net = EmulatedNetwork(load_topology(CAMPUS), MONDAY_9_WAT, cycle_seconds=60, seed=7)
    runtime = Runtime(net, mode="stepped")
    server = serve(runtime, "127.0.0.1", 0, "test-lab-token")
    thread = threading.Thread(target=server.serve_forever, name="test-emulator", daemon=True)
    thread.start()
    yield runtime, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def engine(emulator, tmp_path):
    report = import_topology(read_topology_file(CAMPUS))
    assert report.ok, report.errors
    runtime, url = emulator
    twin = TwinEngine(TelemetryHttpAdapter(url), EngineSettings(
        cycle_seconds=60, warning_pct=70, critical_pct=90, reference_bandwidth_mbps=10000,
        monitoring_retention_days=14, prediction_retention_days=2, model_dir=str(tmp_path)))
    twin.load()
    return runtime, twin


def test_each_cycle_is_stored_once_and_published(engine):
    runtime, twin = engine
    runtime.step_cycles(1)
    assert twin.run_cycle() is True
    # a link's utilisation is the difference between two counter readings, so the first
    # cycle after a start stores the devices only
    assert MonitoringRecord.objects.filter(link__isnull=False).count() == 0
    assert MonitoringRecord.objects.filter(device__isnull=False).count() == 34
    assert twin.state_version == 1 and twin.cycles == 1 and twin.cycles_missed == 0
    assert twin.run_cycle() is False                                              # no new boundary yet
    runtime.step_cycles(1)
    assert twin.run_cycle() is True and twin.state_version == 2
    assert MonitoringRecord.objects.filter(link__isnull=False).count() == 43       # every link, from now on
    timings = twin.status()["timings"]
    assert timings["total_ms"] > 0 and {"collect_ms", "store_ms", "predict_ms"} <= set(timings)


def test_the_published_network_time_is_never_behind_the_stored_cycle(engine):
    """The source clock is read before waiting for a cycle; the header must not lag the data it shows."""
    runtime, twin = engine
    twin.seconds_until_next_poll()                       # reads the source time, as before every wait
    read_before = datetime.fromisoformat(twin.source["time"])
    runtime.step_cycles(1)
    assert twin.run_cycle() is True
    published = datetime.fromisoformat(twin.status()["source"]["time"])
    assert published == twin.last_cycle.timestamp and published > read_before
    assert twin.status()["source"]["mode"] == "stepped"  # the rest of the source description is kept


def test_status_says_when_the_topology_changed_since_the_start(engine):
    """API edits reach the engine at its next start (no live reload), so its status says when one is needed."""
    _, twin = engine
    assert twin.status()["topology_changed"] is False
    persistence.bump_topology_generation()               # what the API does after an edit or an import
    assert twin.status()["topology_changed"] is True
    twin.load()                                          # a restart reads the new topology
    assert twin.status()["topology_changed"] is False


def test_a_late_poll_counts_and_reports_the_cycles_it_missed(engine, caplog):
    runtime, twin = engine
    runtime.step_cycles(1)
    twin.run_cycle()
    runtime.step_cycles(3)                       # the engine was too slow: two boundaries went by unread
    assert twin.run_cycle() is True
    assert twin.cycles_missed == 2 and twin.status()["cycles_missed"] == 2
    assert "missed 2 cycle(s)" in caplog.text
    stored = sorted(set(MonitoringRecord.objects.values_list("timestamp", flat=True)))
    assert stored[1] - stored[0] == timedelta(minutes=3)


def test_fixes_for_a_new_alert_are_worked_out_off_the_cycle(engine):
    runtime, twin = engine
    runtime.step_cycles(1)
    twin.run_cycle()
    link = NetworkLink.objects.get(source_device__name="DIST-HOSTEL", dest_device__name="AP-HOSTEL-01")
    now = twin.last_cycle.timestamp
    episode = Episode(link.link_id, now, now, now + timedelta(minutes=15), 15, 0.9, 95.0, False)
    twin.recommendation_queue.put_nowait((twin.model.copy(), episode, None))
    assert twin.status()["recommendations_pending"] == 1
    version = twin.state_version
    assert twin.recommend_next(timeout=1.0) is True
    assert twin.state_version == version + 1                  # the alert view refreshes with its fixes
    assert twin.status()["recommendations_pending"] == 0
    stored = SimulationResult.objects.filter(scenario__parameters__trigger__link_id=link.link_id).count()
    assert stored == twin.recommendations_made
    assert twin.recommend_next(timeout=0.01) is False          # nothing waiting


def test_retention_runs_after_the_cycle_is_published(engine, monkeypatch):
    """Found by E5: the hourly retention delete ran inside the cycle, so every 60th cycle reached
    the dashboard 4-10 s late. Now the cycle is published first and the delete comes after it."""
    from dataclasses import replace

    runtime, twin = engine
    twin.config = replace(twin.config, prune_every_cycles=1)
    seen = []
    monkeypatch.setattr(persistence, "prune", lambda *args, **kwargs: seen.append(persistence.read_status()))
    runtime.step_cycles(1)
    assert twin.run_cycle() is True and seen == []                 # nothing deleted inside the cycle
    twin.publish_status()                                          # as run_forever does, then:
    twin.housekeeping()
    assert len(seen) == 1 and seen[0]["state_version"] == twin.state_version   # already on the dashboard
