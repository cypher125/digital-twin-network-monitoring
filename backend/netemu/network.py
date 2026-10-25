"""State of the emulated network: routing, link loads, counters, failures and telemetry.

Time advances in fixed steps of STEP_SECONDS of network time. Every
`cycle_seconds` the emulator closes a cycle: it records ground truth (used only
by the evaluation harness) and aggregated flow records (exported as telemetry).
"""
from __future__ import annotations

import itertools
import logging
import threading
import zlib
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import networkx as nx
import numpy as np

from .topology import INTERNET, Topology
from .traffic import Surge, TrafficModel

log = logging.getLogger("netemu.network")

STEP_SECONDS = 10
COUNTER64 = 2 ** 64
COUNTER32 = 2 ** 32
CONVERGENCE_SECONDS = 20   # routing re-converges this long after a failure or repair
MAX_ECMP_PATHS = 8
SPIKE_OCTETS = 10 ** 13     # size of a bogus counter value (data-quality fault)
AVERAGE_PACKET_BYTES = 800  # used by flow sampling

# CPU model per device type: idle load (%) and extra load (%) per Gbps forwarded.
CPU_MODEL = {
    "router": (12.0, 25.0),
    "firewall": (18.0, 45.0),
    "switch": (6.0, 4.0),
    "server": (15.0, 30.0),
    "access_point": (10.0, 60.0),
    "wan_gateway": (8.0, 20.0),
}


@dataclass
class NetEvent:
    seq: int
    time: str
    type: str      # link_down, link_up, device_down, device_up
    element: str   # device name, or "A|B" for a link
    detail: str = ""


class EmulatedNetwork:
    def __init__(self, topo: Topology, start: datetime, cycle_seconds: int = 60, seed: int = 7,
                 history_cycles: int = 1440, origin: datetime | None = None):
        """`origin` is when the traffic calendar began (growth and day-numbered events count from it).
        It defaults to `start`; a resumed emulator passes the first run's origin, so growth carries on."""
        if start.tzinfo is None or (origin is not None and origin.tzinfo is None):
            raise ValueError("start and origin must be timezone-aware")
        self.topo = topo
        self.cycle_seconds = cycle_seconds
        self.t = start
        self.lock = threading.RLock()
        self.events_cond = threading.Condition(self.lock)
        self.rng = np.random.default_rng(seed + 1)
        self.traffic = TrafficModel(topo, origin or start, seed)
        self.demands = self.traffic.demands
        self.random_faults = topo.faults.enabled

        self.device_names = list(topo.devices)
        self.dev_index = {name: i for i, name in enumerate(self.device_names)}
        self.dev_type = [topo.devices[name].type for name in self.device_names]
        self.links = list(topo.links)
        self.link_index = {frozenset((lk.a, lk.b)): i for i, lk in enumerate(self.links)}
        n_links, n_dev, n_dem = len(self.links), len(self.device_names), len(self.demands)
        self.ends = np.array([[self.dev_index[lk.a], self.dev_index[lk.b]] for lk in self.links])
        self.capacity = np.array([lk.capacity_mbps for lk in self.links], dtype=float)
        self.cost = np.array([topo.link_cost(lk) for lk in self.links], dtype=float)
        self.link_admin_up = np.ones(n_links, dtype=bool)
        self.device_up = np.ones(n_dev, dtype=bool)
        self.boot_time = [start] * n_dev
        self.repairs: list[tuple[datetime, str, int]] = []
        self.routing_due: datetime | None = None
        self.pinned_paths: dict[int, list[str]] = {}
        self.qos_caps: list[tuple[str, float, int | None]] = []

        # Interface counters per link end: side 0 = device a, side 1 = device b.
        self.if_in = np.zeros((n_links, 2))
        self.if_out = np.zeros((n_links, 2))
        self.if_err = np.zeros((n_links, 2))
        self.if_index = np.zeros((n_links, 2), dtype=int)
        self.cpu = np.zeros(n_dev)
        self._assign_if_indexes()

        # Cycle accumulators.
        self.cycle_seq = 0
        self.cycle_start = start
        self._acc_ab = np.zeros(n_links)
        self._acc_ba = np.zeros(n_links)
        self._acc_cpu = np.zeros(n_dev)
        self._acc_steps = 0
        self._acc_flow = np.zeros((n_dem, 2))
        self.truth: deque = deque(maxlen=history_cycles)
        self.flows: deque = deque(maxlen=history_cycles)
        self.events: deque = deque(maxlen=5000)
        self.event_seq = 0

        self.f_ab = np.zeros((n_links, n_dem))
        self.f_ba = np.zeros((n_links, n_dem))
        self.routable = np.zeros(n_dem, dtype=bool)
        self.on_cycle: list = []  # callbacks run after every closed cycle (e.g. saving the clock)
        self._recompute_routing()
        # Like an SNMP poller on a fixed schedule, the feed serves the readings taken
        # at the most recent cycle boundary, so the twin's measurement windows line up
        # exactly with the ground-truth cycles.
        self._boundary = self._read_devices(cpu=self.cpu)

    # ------------------------------------------------- copying (evaluation forks)
    def __getstate__(self) -> dict:
        """Locks and callbacks are not copied, so a network can be forked with copy.deepcopy.

        Evaluation E4 forks the emulated network into identical branches (same traffic,
        same random state), applies a change to one, and compares them."""
        state = self.__dict__.copy()
        for key in ("lock", "events_cond", "on_cycle"):
            state.pop(key, None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self.lock = threading.RLock()
        self.events_cond = threading.Condition(self.lock)
        self.on_cycle = []

    # ---------------------------------------------------------------- setup
    def _assign_if_indexes(self) -> None:
        next_index = dict.fromkeys(self.device_names, 1)
        for i, link in enumerate(self.links):
            for side, name in enumerate((link.a, link.b)):
                self.if_index[i, side] = next_index[name]
                next_index[name] += 1

    def find_link(self, a: str, b: str) -> int:
        try:
            return self.link_index[frozenset((a, b))]
        except KeyError:
            raise KeyError(f"no link between {a} and {b}") from None

    # -------------------------------------------------------------- routing
    def operational(self) -> np.ndarray:
        return self.link_admin_up & self.device_up[self.ends[:, 0]] & self.device_up[self.ends[:, 1]]

    def _graph(self) -> nx.Graph:
        g = nx.Graph()
        for i, name in enumerate(self.device_names):
            if self.device_up[i]:
                g.add_node(name)
        operational = self.operational()
        for i, link in enumerate(self.links):
            if operational[i]:
                g.add_edge(link.a, link.b, cost=float(self.cost[i]), link=i)
        egress = [name for name in self.topo.egress_devices if name in g]
        if egress:
            g.add_node(INTERNET)
            for name in egress:
                g.add_edge(name, INTERNET, cost=0.0, link=None)
        return g

    @staticmethod
    def _split(index: int, k: int, imbalance: float) -> list[float]:
        """Shares of a demand over k equal-cost paths. Real per-flow hashing is uneven."""
        if k == 1:
            return [1.0]
        raw = [1.0 + imbalance * (2.0 * zlib.crc32(f"{index}:{i}".encode()) / 0xFFFFFFFF - 1.0)
               for i in range(k)]
        total = sum(raw)
        return [r / total for r in raw]

    @staticmethod
    def _path_ok(g: nx.Graph, path: list[str]) -> bool:
        return all(g.has_edge(u, v) for u, v in itertools.pairwise(path))

    def _recompute_routing(self) -> None:
        g = self._graph()
        n_links, n_dem = len(self.links), len(self.demands)
        f_ab = np.zeros((n_links, n_dem))
        f_ba = np.zeros((n_links, n_dem))
        routable = np.zeros(n_dem, dtype=bool)
        cache: dict[tuple[str, str], list[list[str]]] = {}
        imbalance = self.topo.reality_gap.ecmp_imbalance
        for d in self.demands:
            pinned = self.pinned_paths.get(d.index)
            if pinned and self._path_ok(g, pinned):
                paths = [pinned]
            else:
                key = (d.source, d.dest)
                if key not in cache:
                    paths_found: list[list[str]] = []
                    if d.source in g and d.dest in g:
                        try:
                            paths_found = list(itertools.islice(
                                nx.all_shortest_paths(g, d.source, d.dest, weight="cost"), MAX_ECMP_PATHS))
                        except nx.NetworkXNoPath:
                            paths_found = []
                    cache[key] = paths_found
                paths = cache[key]
            if not paths:
                continue
            routable[d.index] = True
            for path, share in zip(paths, self._split(d.index, len(paths), imbalance), strict=True):
                for u, v in itertools.pairwise(path):
                    link = g.edges[u, v]["link"]
                    if link is None:
                        continue
                    if self.links[link].a == u:
                        f_ab[link, d.index] += share
                    else:
                        f_ba[link, d.index] += share
        self.f_ab, self.f_ba, self.routable = f_ab, f_ba, routable
        self.routing_due = None

    def _schedule_routing(self, t: datetime) -> None:
        due = t + timedelta(seconds=CONVERGENCE_SECONDS)
        if self.routing_due is None or due < self.routing_due:
            self.routing_due = due

    # --------------------------------------------------------------- events
    def _emit(self, t: datetime, kind: str, element: str, detail: str = "") -> None:
        with self.events_cond:  # re-entrant: fine if the caller already holds the lock
            self.event_seq += 1
            self.events.append(NetEvent(self.event_seq, t.isoformat(), kind, element, detail))
            self.events_cond.notify_all()

    def events_after(self, seq: int) -> list[dict]:
        return [asdict(e) for e in self.events if e.seq > seq]

    def fail_link(self, index: int, t: datetime | None = None, minutes: float | None = None) -> None:
        t = t or self.t
        if not self.link_admin_up[index]:
            return
        was_operational = self.operational()[index]
        self.link_admin_up[index] = False
        link = self.links[index]
        if was_operational:
            self._emit(t, "link_down", f"{link.a}|{link.b}")
        if minutes is not None:
            self.repairs.append((t + timedelta(minutes=float(minutes)), "link", index))
        self._schedule_routing(t)

    def repair_link(self, index: int, t: datetime | None = None) -> None:
        t = t or self.t
        if self.link_admin_up[index]:
            return
        self.link_admin_up[index] = True
        self.repairs = [r for r in self.repairs if not (r[1] == "link" and r[2] == index)]
        if self.operational()[index]:
            link = self.links[index]
            self._emit(t, "link_up", f"{link.a}|{link.b}")
        self._schedule_routing(t)

    def fail_device(self, index: int, t: datetime | None = None, minutes: float | None = None) -> None:
        t = t or self.t
        if not self.device_up[index]:
            return
        before = self.operational()
        self.device_up[index] = False
        after = self.operational()
        name = self.device_names[index]
        self._emit(t, "device_down", name)
        for i in np.flatnonzero(before & ~after):
            link = self.links[i]
            self._emit(t, "link_down", f"{link.a}|{link.b}", f"neighbour {name} down")
        if minutes is not None:
            self.repairs.append((t + timedelta(minutes=float(minutes)), "device", index))
        self._schedule_routing(t)

    def repair_device(self, index: int, t: datetime | None = None) -> None:
        """Bring a device back. It reboots, so its interface counters restart from zero."""
        t = t or self.t
        if self.device_up[index]:
            return
        before = self.operational()
        self.device_up[index] = True
        self.boot_time[index] = t
        for side in (0, 1):
            mask = self.ends[:, side] == index
            self.if_in[mask, side] = 0.0
            self.if_out[mask, side] = 0.0
            self.if_err[mask, side] = 0.0
        self.repairs = [r for r in self.repairs if not (r[1] == "device" and r[2] == index)]
        name = self.device_names[index]
        self._emit(t, "device_up", name)
        for i in np.flatnonzero(~before & self.operational()):
            link = self.links[i]
            self._emit(t, "link_up", f"{link.a}|{link.b}")
        self._schedule_routing(t)

    def _faults(self, t: datetime, dt: float) -> None:
        for _due, kind, index in sorted(r for r in self.repairs if r[0] <= t):
            if kind == "link":
                self.repair_link(index, t)
            else:
                self.repair_device(index, t)
        if not self.random_faults:
            return
        fc = self.topo.faults
        p_link = dt / (fc.link_mtbf_hours * 3600.0)
        for i in np.flatnonzero(self.link_admin_up & (self.rng.random(len(self.links)) < p_link)):
            self.fail_link(int(i), t, minutes=self.rng.exponential(fc.link_mttr_minutes))
        p_dev = dt / (fc.device_mtbf_hours * 3600.0)
        for i in np.flatnonzero(self.device_up & (self.rng.random(len(self.device_names)) < p_dev)):
            self.fail_device(int(i), t, minutes=self.rng.exponential(fc.device_mttr_minutes))

    # ------------------------------------------------------------------ QoS
    def _apply_qos(self, rates: np.ndarray) -> np.ndarray:
        for cls, cap, link in self.qos_caps:
            mask = np.array([d.cls == cls for d in self.demands])
            if link is None:
                total = rates[mask].sum()
            else:
                share = self.f_ab[link] + self.f_ba[link]
                mask &= share > 0
                total = (rates[mask] * share[mask]).sum()
            if total > cap > 0:
                rates = np.where(mask, rates * cap / total, rates)
        return rates

    # ----------------------------------------------------------------- step
    def step(self) -> None:
        dt = float(STEP_SECONDS)
        t_next = self.t + timedelta(seconds=dt)
        self._faults(t_next, dt)
        if self.routing_due is not None and t_next >= self.routing_due:
            self._recompute_routing()

        rates = self._apply_qos(self.traffic.offered(t_next, dt))
        down = self.traffic.down_ratio
        fwd, rev = rates * (1.0 - down), rates * down
        overhead = 1.0 + self.topo.reality_gap.overhead_pct / 100.0
        load_ab = (self.f_ab @ fwd + self.f_ba @ rev) * overhead
        load_ba = (self.f_ba @ fwd + self.f_ab @ rev) * overhead
        operational = self.operational()
        carried_ab = np.where(operational, np.minimum(load_ab, self.capacity), 0.0)
        carried_ba = np.where(operational, np.minimum(load_ba, self.capacity), 0.0)

        # Share of each demand that is actually delivered: limited by its most congested link.
        ratio_ab = np.divide(carried_ab, load_ab, out=np.ones_like(load_ab), where=load_ab > 0)
        ratio_ba = np.divide(carried_ba, load_ba, out=np.ones_like(load_ba), where=load_ba > 0)
        used_ab, used_ba = self.f_ab > 0, self.f_ba > 0
        fwd_frac = np.minimum(np.where(used_ab, ratio_ab[:, None], 1.0).min(axis=0),
                              np.where(used_ba, ratio_ba[:, None], 1.0).min(axis=0))
        rev_frac = np.minimum(np.where(used_ab, ratio_ba[:, None], 1.0).min(axis=0),
                              np.where(used_ba, ratio_ab[:, None], 1.0).min(axis=0))
        octets_per_mbps = 1e6 / 8.0 * dt
        self._acc_flow[:, 0] += fwd * fwd_frac * self.routable * octets_per_mbps
        self._acc_flow[:, 1] += rev * rev_frac * self.routable * octets_per_mbps

        octets_ab, octets_ba = carried_ab * octets_per_mbps, carried_ba * octets_per_mbps
        self.if_out[:, 0] += octets_ab
        self.if_in[:, 0] += octets_ba
        self.if_out[:, 1] += octets_ba
        self.if_in[:, 1] += octets_ab

        util = np.maximum(carried_ab, carried_ba) / self.capacity
        lam = 0.0005 * dt + np.where(util > 0.85, 3.0 * ((util - 0.85) / 0.15) ** 2 * dt / 60.0, 0.0)
        self.if_err += self.rng.poisson(np.repeat(lam[:, None], 2, axis=1))

        through = np.zeros(len(self.device_names))
        both = carried_ab + carried_ba
        np.add.at(through, self.ends[:, 0], both)
        np.add.at(through, self.ends[:, 1], both)
        through /= 2.0  # each forwarded packet enters one interface and leaves another
        base = np.array([CPU_MODEL.get(t, (8.0, 10.0))[0] for t in self.dev_type])
        per_gbps = np.array([CPU_MODEL.get(t, (8.0, 10.0))[1] for t in self.dev_type])
        cpu = base + per_gbps * through / 1000.0 + self.rng.normal(0.0, 1.5, len(base))
        self.cpu = np.where(self.device_up, np.clip(cpu, 1.0, 100.0), 0.0)

        self._acc_ab += carried_ab
        self._acc_ba += carried_ba
        self._acc_cpu += self.cpu
        self._acc_steps += 1
        self.t = t_next
        if (self.t - self.cycle_start).total_seconds() >= self.cycle_seconds:
            self._close_cycle()

    def steps_per_cycle(self) -> int:
        return max(1, round(self.cycle_seconds / STEP_SECONDS))

    def _close_cycle(self) -> None:
        n = max(1, self._acc_steps)
        ab, ba = self._acc_ab / n, self._acc_ba / n
        util = np.maximum(ab, ba) / self.capacity * 100.0
        operational = self.operational()
        self.cycle_seq += 1
        start, end = self.cycle_start.isoformat(), self.t.isoformat()
        self.truth.append({
            "seq": self.cycle_seq,
            "start": start,
            "end": end,
            "links": [
                {"a": lk.a, "b": lk.b, "mbps_ab": round(float(ab[i]), 4), "mbps_ba": round(float(ba[i]), 4),
                 "utilisation_pct": round(float(util[i]), 4), "up": bool(operational[i])}
                for i, lk in enumerate(self.links)
            ],
            "devices": [
                {"name": name, "cpu": round(float(self._acc_cpu[i] / n), 3), "up": bool(self.device_up[i])}
                for i, name in enumerate(self.device_names)
            ],
        })
        records = []
        sampling = max(1, int(self.topo.reality_gap.flow_sampling))
        for d in self.demands:
            fwd, rev = self._sampled(self._acc_flow[d.index, 0], sampling), self._sampled(
                self._acc_flow[d.index, 1], sampling)
            if fwd + rev > 0:
                records.append({"src": d.source, "dst": d.dest, "cls": d.cls, "octets_fwd": fwd, "octets_rev": rev})
        self.flows.append({"seq": self.cycle_seq, "start": start, "end": end, "records": records})
        self._boundary = self._read_devices(cpu=self._acc_cpu / n)  # CPU: average over the cycle
        self._acc_ab[:] = 0.0
        self._acc_ba[:] = 0.0
        self._acc_cpu[:] = 0.0
        self._acc_flow[:] = 0.0
        self._acc_steps = 0
        self.cycle_start = self.t
        for callback in self.on_cycle:
            try:
                callback(self)
            except Exception:  # a failing observer (for example saving the clock) must not stop the network
                log.exception("cycle callback failed")

    # ------------------------------------------------------------- telemetry
    def _read_devices(self, cpu: np.ndarray) -> dict:
        """Read every device's counters and statistics at this instant (no data-quality faults)."""
        operational = self.operational()
        devices = []
        for i, name in enumerate(self.device_names):
            if not self.device_up[i]:
                devices.append({"name": name, "reachable": False})
                continue
            interfaces = []
            for side in (0, 1):
                for link in np.flatnonzero(self.ends[:, side] == i):
                    lk = self.links[link]
                    interfaces.append({
                        "ifIndex": int(self.if_index[link, side]),
                        "ifName": f"Gi0/{int(self.if_index[link, side])}",
                        "peer": lk.b if side == 0 else lk.a,
                        "ifSpeedMbps": float(self.capacity[link]),
                        "ifOperStatus": 1 if operational[link] else 2,
                        "ifHCInOctets": int(self.if_in[link, side]) % COUNTER64,
                        "ifHCOutOctets": int(self.if_out[link, side]) % COUNTER64,
                        "ifInErrors": int(self.if_err[link, side]) % COUNTER32,
                    })
            interfaces.sort(key=lambda e: e["ifIndex"])
            devices.append({
                "name": name,
                "reachable": True,
                "sysUpTime": int((self.t - self.boot_time[i]).total_seconds() * 100),  # timeticks
                "cpu": round(float(cpu[i]), 2),
                "interfaces": interfaces,
            })
        return {"timestamp": self.t.isoformat(), "cycle_seconds": self.cycle_seconds, "devices": devices}

    def snapshot(self) -> dict:
        """The readings from the latest cycle boundary, as a poller would receive them (read-only).

        Data-quality faults are applied per request: a timed-out interface is left
        out, and a glitch adds a bogus amount to one counter for this poll only.
        """
        dq = self.topo.data_quality
        devices = []
        for device in self._boundary["devices"]:
            if not device["reachable"]:
                devices.append(dict(device))
                continue
            interfaces = []
            for entry in device["interfaces"]:
                if dq.missing_sample_prob and self.rng.random() < dq.missing_sample_prob:
                    continue
                entry = dict(entry)
                if dq.spike_prob and self.rng.random() < dq.spike_prob:
                    entry["ifHCInOctets"] = (entry["ifHCInOctets"] + SPIKE_OCTETS) % COUNTER64
                interfaces.append(entry)
            devices.append({**device, "interfaces": interfaces})
        return {**self._boundary, "devices": devices}

    def _sampled(self, octets: float, sampling: int) -> int:
        """NetFlow-style 1:N packet sampling: count 1 in N packets and scale the result back up."""
        if sampling <= 1:
            return int(octets)
        packets = int(octets / AVERAGE_PACKET_BYTES)
        if packets <= 0:
            return 0
        return int(self.rng.binomial(packets, 1.0 / sampling)) * sampling * AVERAGE_PACKET_BYTES

    def flows_after(self, seq: int) -> list[dict]:
        """Flow records exported so far. With an export delay, the newest cycles are not available yet."""
        exported = self.cycle_seq - max(0, int(self.topo.reality_gap.flow_export_delay_cycles))
        return [f for f in self.flows if seq < f["seq"] <= exported]

    def truth_after(self, seq: int) -> list[dict]:
        return [c for c in self.truth if c["seq"] > seq]

    # ------------------------------------------- real changes (lab, for E4)
    def add_surge(self, zone: str, cls: str, multiplier: float, ramp_minutes: float,
                  hold_minutes: float, start_in_minutes: float = 0.0) -> Surge:
        surge = Surge(zone, cls, float(multiplier), self.t + timedelta(minutes=start_in_minutes),
                      timedelta(minutes=ramp_minutes), timedelta(minutes=hold_minutes))
        self.traffic.surges.append(surge)
        return surge

    def apply_change(self, change: dict) -> str:
        """Apply a configuration change to the emulated real network (lab use only)."""
        kind = change["type"]
        if kind == "capacity_change":
            index = self.find_link(*change["link"])
            self.capacity[index] = float(change["capacity_mbps"])
        elif kind == "routing_change":
            for item in change["link_costs"]:
                self.cost[self.find_link(*item["link"])] = float(item["cost"])
            self._recompute_routing()
        elif kind == "link_failure":
            self.fail_link(self.find_link(*change["link"]))
        elif kind == "device_failure":
            self.fail_device(self.dev_index[change["device"]])
        elif kind == "traffic_increase":
            mask = self.traffic.mask(change.get("zone", "*"), change.get("cls", "*"),
                                     change.get("source", "*"), change.get("dest", "*"))
            self.traffic.scale[mask] *= 1.0 + float(change["percent"]) / 100.0
        elif kind == "reroute_traffic":
            mask = self.traffic.mask(change.get("zone", "*"), change.get("cls", "*"),
                                     change["source"], change["dest"])
            for index in np.flatnonzero(mask):
                self.pinned_paths[int(index)] = list(change["path"])
            self._recompute_routing()
        elif kind == "access_control_rule":
            mask = self.traffic.mask(change.get("zone", "*"), change.get("cls", "*"),
                                     change.get("source", "*"), change.get("dest", "*"))
            self.traffic.blocked |= mask
        elif kind == "qos_policy":
            link = self.find_link(*change["link"]) if change.get("link") else None
            self.qos_caps.append((change["cls"], float(change["limit_mbps"]), link))
        else:
            raise ValueError(f"unknown change type {kind}")
        return kind

    def reset_changes(self) -> None:
        """Undo every lab change and restore the original configuration."""
        self.capacity = np.array([lk.capacity_mbps for lk in self.links], dtype=float)
        self.cost = np.array([self.topo.link_cost(lk) for lk in self.links], dtype=float)
        self.traffic.scale[:] = 1.0
        self.traffic.blocked[:] = False
        self.traffic.surges.clear()
        self.pinned_paths.clear()
        self.qos_caps.clear()
        for i in np.flatnonzero(~self.link_admin_up):
            self.repair_link(int(i))
        for i in np.flatnonzero(~self.device_up):
            self.repair_device(int(i))
        self._recompute_routing()
