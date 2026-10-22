"""Dry run of evaluation E4: does the twin's what-if prediction match what really happens?

The twin simulates a change; the same change is then applied to the emulator (the
"real network") through the lab interface, and the predicted link utilisation is
compared with the measured one. The emulator and the twin share no code, and the
emulator has a deliberate reality gap (uneven multipath hashing, 3 % overhead, noise).
"""
import threading

import httpx
import numpy as np
import pytest

from data_collection.network_adapter import TelemetryHttpAdapter
from data_collection.preprocessing import Preprocessor
from digital_twin.simulation_engine import run_scenario
from netemu.network import EmulatedNetwork
from netemu.server import Runtime, serve
from tests.conftest import START, index_for, model_for

TOKEN = "test-token"


@pytest.fixture
def world(campus):
    net = EmulatedNetwork(campus, START.replace(hour=10))   # Monday 10:00, a busy hour
    net.random_faults = False
    runtime = Runtime(net, mode="stepped")
    server = serve(runtime, "127.0.0.1", 0, TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    lab = httpx.Client(base_url=url, headers={"X-Lab-Token": TOKEN}, timeout=60)
    adapter = TelemetryHttpAdapter(url)
    pre = Preprocessor(index_for(campus), 60)
    model = model_for(campus)

    def ingest(cycles: int = 1):
        for _ in range(cycles):
            lab.post("/lab/step", json={"cycles": 1}).raise_for_status()
            clean = pre.process(adapter.poll())
            if clean:
                model.apply(clean)

    ingest(4)
    yield net, model, lab, ingest
    adapter.close()
    lab.close()
    server.shutdown()
    server.server_close()


def compare(model, outcome, ingest, net):
    ingest(3)  # let routing converge and measure a full cycle after the change
    predicted, measured = [], []
    for lk in outcome.links:
        observed = model.link(lk.link_id)["utilisation_pct"]
        if observed is None or lk.status_after == "down":
            continue
        predicted.append(min(lk.after_pct, 100.0))   # a real link cannot carry more than 100 %
        measured.append(observed)
    predicted, measured = np.array(predicted), np.array(measured)
    busy = measured >= 5
    return np.abs(predicted - measured), busy


SCENARIOS = [
    ("link_failure", lambda names, links: {"link_id": links["ISP-B-GW <-> EDGE-RTR-01"]},
     lambda: {"type": "link_failure", "link": ["ISP-B-GW", "EDGE-RTR-01"]}),
    ("capacity_change", lambda names, links: {"link_id": links["ISP-B-GW <-> EDGE-RTR-01"], "capacity_mbps": 400},
     lambda: {"type": "capacity_change", "link": ["ISP-B-GW", "EDGE-RTR-01"], "capacity_mbps": 400}),
    ("traffic_increase", lambda names, links: {"percent": 40, "source_zone": "HOSTEL"},
     lambda: {"type": "traffic_increase", "zone": "HOSTEL", "percent": 40}),
    ("routing_change", lambda names, links: {"link_costs": [{"link_id": links["ISP-B-GW <-> EDGE-RTR-01"], "cost": 50}]},
     lambda: {"type": "routing_change", "link_costs": [{"link": ["ISP-B-GW", "EDGE-RTR-01"], "cost": 50}]}),
    ("access_control_rule", lambda names, links: {"cls": "video"},
     lambda: {"type": "access_control_rule", "cls": "video"}),
]


@pytest.mark.parametrize("key, twin_params, real_change", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_prediction_matches_reality(world, key, twin_params, real_change):
    net, model, lab, ingest = world
    names = {data["name"]: n for n, data in model.graph.nodes(data=True)}
    links = {model.link_label(i): i for i in model.link_ids()}
    outcome = run_scenario(model, key, twin_params(names, links))
    lab.post("/lab/change", json=real_change()).raise_for_status()
    errors, busy = compare(model, outcome, ingest, net)
    print(f"{key}: mean abs error {errors.mean():.2f} pp, busy links {errors[busy].mean():.2f} pp, "
          f"max {errors.max():.2f} pp, calibration {outcome.calibration_factor}")
    assert errors.mean() < 1.5
    assert errors[busy].mean() < 3.0
    assert errors.max() < 10.0
