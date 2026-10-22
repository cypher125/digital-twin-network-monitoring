"""End to end without the database: emulator -> HTTP feed -> adapter -> preprocessing -> network model.

An early version of evaluation E1: the twin's link utilisation should match the
emulator's ground truth for the same cycles.
"""
import threading
from datetime import datetime

import httpx
import numpy as np
import pytest

from data_collection.network_adapter import TelemetryHttpAdapter
from data_collection.preprocessing import Preprocessor
from netemu.network import EmulatedNetwork
from netemu.server import Runtime, serve
from tests.conftest import START, index_for, model_for

TOKEN = "test-token"


@pytest.fixture
def feed(campus):
    net = EmulatedNetwork(campus, START.replace(hour=9))
    net.random_faults = False
    runtime = Runtime(net, mode="stepped")
    server = serve(runtime, "127.0.0.1", 0, TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield net, url
    server.shutdown()
    server.server_close()


def step(url: str, cycles: int = 1) -> None:
    response = httpx.post(f"{url}/lab/step", json={"cycles": cycles}, headers={"X-Lab-Token": TOKEN})
    response.raise_for_status()


def test_lab_needs_the_token(feed):
    _, url = feed
    assert httpx.post(f"{url}/lab/step", json={"cycles": 1}).status_code == 403
    assert httpx.post(f"{url}/v1/snapshot").status_code == 405  # the feed itself is read-only


def test_twin_replicates_emulator_state(feed, campus):
    net, url = feed
    adapter = TelemetryHttpAdapter(url)
    index = index_for(campus)
    pre = Preprocessor(index, 60)
    model = model_for(campus)
    errors = []
    step(url)
    model.apply(pre.process(adapter.poll()))         # first poll: baseline counters only
    for _ in range(20):
        step(url)
        clean = pre.process(adapter.poll())
        model.apply(clean)
        truth = net.truth[-1]
        # the twin's cycle is exactly the emulator's ground-truth cycle
        assert datetime.fromisoformat(truth["end"]) == clean.timestamp
        for i in range(len(net.links)):
            reading = model.link(i + 1)["utilisation_pct"]
            if reading is not None and clean.links[i + 1].utilisation_pct is not None:
                errors.append(abs(reading - truth["links"][i]["utilisation_pct"]))
    adapter.close()
    errors = np.array(errors)
    assert len(errors) > 20 * 40                       # nearly every link, every cycle
    assert errors.mean() < 0.05                        # percentage points
    assert np.percentile(errors, 99) < 0.5
    assert model.demands, "flow telemetry should give the twin a demand matrix"


def test_events_arrive_through_the_feed(feed):
    net, url = feed
    adapter = TelemetryHttpAdapter(url)
    assert adapter.events(wait_seconds=0) == []
    httpx.post(f"{url}/lab/fail", json={"link": ["DIST-LIB", "CORE-SW-01"]},
               headers={"X-Lab-Token": TOKEN}).raise_for_status()
    events = adapter.events(wait_seconds=2)
    assert [(e.type, e.element) for e in events] == [("link_down", "DIST-LIB|CORE-SW-01")]
    adapter.close()
