"""Shared fixtures. Tests may import both the emulator and the twin; the packages themselves may not."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_collection.preprocessing import DeviceRef, LinkRef, TopologyIndex
from digital_twin.network_model import NetworkModel
from netemu.topology import Topology, load_topology, parse_topology

PROJECT_DIR = Path(__file__).resolve().parents[2]
CAMPUS = PROJECT_DIR / "data" / "topologies" / "campus.yaml"
START = datetime.fromisoformat("2026-10-05T00:00:00+01:00")  # a Monday, West Africa Time


@pytest.fixture(scope="session")
def campus() -> Topology:
    return load_topology(CAMPUS)


SMALL = {
    "name": "small test network",
    "reference_bandwidth_mbps": 10000,
    "devices": [
        {"name": "GW", "type": "wan_gateway", "zone": "CORE", "internet_egress": True},
        {"name": "CORE1", "type": "switch", "zone": "CORE"},
        {"name": "CORE2", "type": "switch", "zone": "CORE"},
        {"name": "DIST", "type": "switch", "zone": "Z"},
        {"name": "ACC", "type": "switch", "zone": "Z"},
        {"name": "SRV", "type": "server", "zone": "DC"},
    ],
    "links": [
        ["GW", "CORE1", 1000],
        ["GW", "CORE2", 1000],
        ["CORE1", "DIST", 1000],
        ["CORE2", "DIST", 1000],
        ["DIST", "ACC", 100],
        ["CORE1", "SRV", 1000],
    ],
    "classes": {"web": {"per_user_mbps": 0.1, "dest": "internet", "down_ratio": 0.8},
                "app": {"per_user_mbps": 0.05, "dest": "SRV", "down_ratio": 0.5}},
    "zones": {"Z": {"population": 500, "profile": "flat", "access": {"ACC": 1.0}}},
    "profiles": {"flat": {"weekday": [[0, 1.0], [24, 1.0]], "weekend": [[0, 1.0], [24, 1.0]]}},
    "faults": {"enabled": False},
    "reality_gap": {"ecmp_imbalance": 0.0, "overhead_pct": 0.0, "noise_sigma": 0.0},
}


@pytest.fixture
def small() -> Topology:
    return parse_topology(SMALL)


def index_for(topo: Topology) -> TopologyIndex:
    """The twin's topology index for an emulator topology (devices and links numbered from 1)."""
    devices = {name: DeviceRef(i + 1, name, d.type, d.internet_egress)
               for i, (name, d) in enumerate(topo.devices.items())}
    links = {i + 1: LinkRef(i + 1, lk.a, lk.b, lk.capacity_mbps, lk.cost) for i, lk in enumerate(topo.links)}
    return TopologyIndex(devices, links)


def emulated_history(topo: Topology, start: datetime, days: float, seed: int = 7):
    """(History, emulator) for prediction tests: history from the emulator's ground truth (faults off).

    The emulator is returned too, so a test can carry on from where the history ends."""
    import numpy as np

    from digital_twin.prediction_engine import History, link_tier, static_features
    from netemu.network import EmulatedNetwork

    net = EmulatedNetwork(topo, start, seed=seed, history_cycles=int(days * 1440) + 10)
    net.random_faults = False
    for _ in range(int(days * 1440) * net.steps_per_cycle()):
        net.step()
    times = np.array([datetime.fromisoformat(c["end"]).timestamp() for c in net.truth])
    util = np.array([[lk["utilisation_pct"] for lk in c["links"]] for c in net.truth], dtype=np.float32)
    tiers = [link_tier((topo.devices[lk.a].role, topo.devices[lk.b].role),
                       (topo.devices[lk.a].type, topo.devices[lk.b].type)) for lk in topo.links]
    static = static_features(np.array([lk.capacity_mbps for lk in topo.links]), tiers)
    return History(times, util, np.zeros_like(util), static, list(range(1, len(topo.links) + 1)), 60), net


def model_for(topo: Topology) -> NetworkModel:
    """The same model the twin builds after `import_topology` (configuration holds role and zone)."""
    index = index_for(topo)
    devices = [{"device_id": ref.device_id, "name": ref.name, "device_type": ref.device_type,
                "status": "unknown",
                "configuration": {"internet_egress": ref.internet_egress,
                                  "zone": topo.devices[ref.name].zone, "role": topo.devices[ref.name].role}}
               for ref in index.devices.values()]
    links = [{"link_id": lk.link_id, "source_device_id": index.devices[lk.source].device_id,
              "dest_device_id": index.devices[lk.dest].device_id, "capacity_mbps": lk.capacity_mbps,
              "status": "unknown", "routing_cost": lk.routing_cost}
             for lk in index.links.values()]
    return NetworkModel(devices, links, warning_pct=70, critical_pct=90,
                        reference_bandwidth_mbps=topo.reference_bandwidth_mbps)
