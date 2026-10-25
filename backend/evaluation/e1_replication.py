"""E1 Replication fidelity (Abstract, gap G1): does the twin's state match the network?

What is measured
    How closely the digital twin's picture of the network (the state held in its network
    model) matches the real network, here the emulator's ground truth. Two things are compared
    for every link: its utilisation and its status (up or down). Device status is compared too.

How
    The emulator and the twin run in one process. The twin is the engine's own ingest path
    (evaluation/twin.py): the production telemetry adapter, preprocessing module and network
    model, fed through an in-memory transport that answers exactly as the emulator's HTTP feed
    does. The run mirrors the live engine (digital_twin/runtime/engine.py):
      * the network advances in 10-second steps; after every step the twin reads the new
        up/down notifications (/v1/events) and applies each one at once, as the engine's event
        listener does (FR2);
      * once a minute, 10 s after each cycle boundary (the engine's poll offset), the twin polls
        the counters (/v1/snapshot) and the flow records (/v1/flows), validates them and
        updates the model, as the engine's monitoring cycle does (processes 1.0-3.0).
    After each poll, the twin's utilisation of every link is compared with the emulator's
    ground truth for the same one-minute cycle. After every 10-second step, the twin's status of
    every link and device is compared with the emulator's actual state at that moment.

    The run starts on Monday 2 November 2026 at 00:00 WAT (after the training history, which
    ended on 28 October 2026), with emulator seed 2026 (training used seed 7). It is repeated
    at the three reality-gap presets: off (a sanity check), default (campus.yaml) and high.
    Everything else is the campus.yaml configuration: random link and device failures
    (MTBF 1500 h per link and 3000 h per device), data-quality faults (each interface sample
    is missing with probability 0.002 and carries a bogus counter value with probability
    0.0005 per poll), reboots that reset counters, and four random flash crowds a day.

    Random failures at those rates are rare: about one link failure every 35 hours and one
    device failure every 88 hours across the campus. So that status tracking and counter-reset
    handling are actually exercised, a fixed, pre-registered schedule of extra failures is
    injected as well, identical at every preset: every 2 hours (30 minutes in a quick run),
    alternately a link failure lasting 3-20 minutes and a device failure (a reboot) lasting
    2-10 minutes. The element and the duration are drawn from a separate random generator
    (seed 2026 + 99); the moment within the minute rotates through all six 10-second steps, so
    failures that arrive just before, at and after a poll are all covered. Changes from the
    schedule and from the emulator's own random faults are reported separately.

Definitions
    utilisation error   |twin - truth| in percentage points (pts), per link and cycle. Truth is
                        the emulator's average over the cycle of the busier direction, as a
                        share of capacity. "Twin" is the utilisation the preprocessing module
                        computes from that cycle's counters (a fresh reading). Link-cycles
                        without a fresh reading are not scored (see coverage). The first poll
                        is excluded: it only sets the counter baselines.
    displayed-state error  the same, using the value the model holds after the poll, which is
                        the last reading when no fresh one arrived (what the dashboard shows).
    coverage            share of link-cycles with a fresh twin reading.
    DQ-affected         a link-cycle where an interface of that link was missing or carried a
                        bogus value in this poll or the one before. Such a gap means the next
                        good reading is a rate over two minutes, not one.
    status agreement    per cycle: the twin's status after the poll equals the truth at the
                        cycle's end; per step: the twin's status equals the network's actual
                        state after each 10-second step ("unknown" counts as disagreement).
    synchronisation delay  for every ground-truth status change of a link or device: the time
                        from the change until the twin shows the new status and keeps showing
                        it until the next change. It is measured at the 10-second step, so 0 s
                        means the twin already agreed at the first check after the change. A
                        change is "reverted" when the twin showed the new status, lost it and
                        then regained it; "overwritten by poll" is the case where the event set
                        the new status and the following poll, whose counters were read at the
                        cycle boundary before the change, set the old one back; "missed" when
                        the twin never settled before the next change.
    demand model        for context only (it is what E4's simulations start from): every
                        5th cycle, the twin's flow-based demand matrix is routed over its model
                        and scaled by the simulation engine's calibration factor, and the
                        resulting utilisation is compared with the truth. This is where the
                        reality gap enters; the measured state above does not depend on it.
    processing time     wall-clock time of one poll: collect, validate and update the model,
                        in process (no network socket, no database write; E5 measures the whole
                        path to the screen).

Targets (plan section 11)
    Mean absolute utilisation error under 1 percentage point at the default preset; every
    status change shown by the twin within one cycle (60 s). p95 and maximum error are reported
    against the same 1-point line.

Limitations
    The "real network" is the emulator, so the ground truth is exact and the counters are
    consistent with it by construction; on real equipment, counter sampling jitter and polling
    delays would add error that this experiment cannot show. The reality-gap presets change how
    traffic is routed and how flows are sampled; they do not change the counters, so they barely
    affect the measured state and matter for the demand model and for E4. Random faults and
    data-quality faults come from the emulator's own random stream, which flow sampling also
    draws from, so their exact timing differs between presets (the injected schedule does not).
    Status delays have a resolution of one 10-second step; the wall-clock delay of the event
    path is part of E5. In this harness a failure in the 10-second step that ends at the poll is
    always applied before the poll; in live operation the event and the poll race, so the
    overwritten-by-poll case may occur less often there. One topology (34 devices, 43 links), one seed, one week by default (the
    plan's minimum is 24 hours).

    python -m evaluation.e1_replication [--quick] [--days 7] [--presets off,default,high]
    python -m evaluation.e1_replication --selftest
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone

import numpy as np

from data_collection.preprocessing import QualityReport
from digital_twin.network_model import route_demands
from digital_twin.simulation_engine.runner import _calibration
from netemu.network import STEP_SECONDS, EmulatedNetwork
from netemu.topology import DataQualityConfig, Topology, load_topology, with_reality_gap

from .common import BACKEND, INK_2, ROOT, SERIES, Results, chart, legend, threshold_lines
from .twin import Twin

CAMPUS = ROOT / "data" / "topologies" / "campus.yaml"
PRESETS = ("off", "default", "high")
WAT = timezone(timedelta(hours=1), "WAT")
START = datetime(2026, 11, 2, 0, 0, tzinfo=WAT)    # a Monday, after the training history
SEED = 2026                                        # the training history used the emulator's default, 7
FAULT_SEED = SEED + 99
CYCLE_SECONDS = 60
TARGET_PTS = 1.0
WARMUP_POLLS = 1                                   # the first poll only sets the counter baselines
STATUS_CODE = {"up": 1, "down": 0, "unknown": -1}
DELAY_BINS = (0, 10, 20, 30, 40, 50, 60)           # seconds; the last bar is "more than 60 s"
LINK_FAULT_MINUTES = (3.0, 20.0)
DEVICE_FAULT_MINUTES = (2.0, 10.0)
HISTORY_CYCLES = 30                                # emulator truth and flow records kept in memory


# ------------------------------------------------------------ production settings, read not copied
def engine_poll_offset_seconds() -> float:
    """EngineSettings.poll_offset_seconds, read from engine.py without importing Django."""
    source = (BACKEND / "digital_twin" / "runtime" / "engine.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "EngineSettings":
            for item in node.body:
                if (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                        and item.target.id == "poll_offset_seconds" and item.value is not None):
                    return float(ast.literal_eval(item.value))
    raise RuntimeError("EngineSettings.poll_offset_seconds not found in engine.py")


def production_link_tier():
    """prediction_engine.features.link_tier, loaded on its own (the package would load scikit-learn)."""
    name = "_e1_prediction_features"
    if name not in sys.modules:
        path = BACKEND / "digital_twin" / "prediction_engine" / "features.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module          # dataclasses look the module up while it loads
        spec.loader.exec_module(module)
    return sys.modules[name].link_tier


# ------------------------------------------------------------------ scoring (unit-tested)
def error_stats(errors: np.ndarray) -> dict:
    """Mean, percentiles and maximum of absolute errors (NaN ignored), in percentage points."""
    e = np.asarray(errors, dtype=float)
    e = e[~np.isnan(e)]
    if e.size == 0:
        return {"n": 0, "mae": None, "p50": None, "p95": None, "p99": None, "max": None, "share_under_1pt": None}
    return {"n": int(e.size), "mae": float(e.mean()), "p50": float(np.percentile(e, 50)),
            "p95": float(np.percentile(e, 95)), "p99": float(np.percentile(e, 99)), "max": float(e.max()),
            "share_under_1pt": float(np.mean(e < TARGET_PTS))}


def settle(truth: np.ndarray, twin: np.ndarray, change: int, end: int) -> dict:
    """How the twin followed one ground-truth change at step `change` (valid until step `end`).

    truth: bool per step (True = up); twin: status code per step (1 up, 0 down, -1 unknown).
    first: steps until the twin first showed the new status; stable: steps until it showed it
    and kept it until `end`; missed: it never settled before `end`."""
    target = 1 if truth[change] else 0
    agree = twin[change:end] == target
    if not agree.any():
        return {"first": None, "stable": None, "reverted": False, "missed": True}
    first = int(np.argmax(agree))
    wrong = np.flatnonzero(~agree)
    stable = int(wrong[-1] + 1) if wrong.size else 0
    if stable >= end - change:
        return {"first": first, "stable": None, "reverted": True, "missed": True}
    return {"first": first, "stable": stable, "reverted": stable > first, "missed": False}


def delay_histogram(delays_s: list[float]) -> list[int]:
    """Counts per DELAY_BINS value, plus a final count of delays above the last bin."""
    counts = [0] * (len(DELAY_BINS) + 1)
    for d in delays_s:
        for i, edge in enumerate(DELAY_BINS):
            if d <= edge:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return counts


@dataclass(frozen=True)
class InjectedFault:
    step: int        # the element fails at the end of this 10-second step
    kind: str        # "link" or "device"
    index: int       # emulator link or device index
    minutes: float   # time until the emulator repairs it


def fault_schedule(n_links: int, n_devices: int, total_steps: int, every_minutes: float,
                   steps_per_cycle: int, seed: int = FAULT_SEED) -> list[InjectedFault]:
    """Pre-registered extra failures: alternately a link and a device, one every `every_minutes`.

    The k-th link (and k-th device) failure lands on step k mod steps_per_cycle of its minute, so
    every position relative to the poll is covered equally."""
    if every_minutes <= 0:
        return []
    rng = np.random.default_rng(seed)
    every = max(1, round(every_minutes * 60 / STEP_SECONDS))
    faults = []
    for k, base in enumerate(range(every // 2, total_steps, every)):
        phase = (k // 2) % steps_per_cycle
        step = base - base % steps_per_cycle + phase
        if step >= total_steps:
            break
        if k % 2 == 0:
            faults.append(InjectedFault(step, "link", int(rng.integers(n_links)),
                                        float(rng.uniform(*LINK_FAULT_MINUTES))))
        else:
            faults.append(InjectedFault(step, "device", int(rng.integers(n_devices)),
                                        float(rng.uniform(*DEVICE_FAULT_MINUTES))))
    return faults


# ------------------------------------------------------------------ instrumentation
class SnapshotProbe:
    """Counts the data-quality faults the emulator puts into each served snapshot.

    Wraps the emulator's snapshot() (the feed's /v1/snapshot handler calls it once per poll) and
    compares what is served with the boundary readings it came from. Read-only."""

    def __init__(self, net: EmulatedNetwork):
        self.net = net
        self.original = net.snapshot
        self.link_of = {(net.device_names[int(net.ends[i, side])], int(net.if_index[i, side])): i
                        for i in range(len(net.links)) for side in (0, 1)}
        self.missing = 0
        self.spikes = 0
        self.affected: set[int] = set()   # link indices touched in the latest snapshot
        self.seconds = 0.0                # time spent here, taken off the measured processing time
        net.snapshot = self.snapshot

    def snapshot(self) -> dict:
        served = self.original()
        began = time.perf_counter()
        self.missing = self.spikes = 0
        self.affected = set()
        for clean, out in zip(self.net._boundary["devices"], served["devices"], strict=True):
            if not clean.get("reachable"):
                continue
            sent = {e["ifIndex"]: e for e in out["interfaces"]}
            for entry in clean["interfaces"]:
                got = sent.get(entry["ifIndex"])
                if got is None:
                    self.missing += 1
                elif got["ifHCInOctets"] != entry["ifHCInOctets"]:
                    self.spikes += 1
                else:
                    continue
                self.affected.add(self.link_of[(clean["name"], entry["ifIndex"])])
        self.seconds += time.perf_counter() - began
        return served


# ------------------------------------------------------------------ one run
@dataclass
class Run:
    preset: str
    link_names: list[str]
    device_names: list[str]
    tiers: list[str]
    capacity: np.ndarray
    times: list[datetime]          # end of each polled cycle
    truth: np.ndarray              # (polls, links) utilisation %
    truth_up: np.ndarray           # (polls, links)
    fresh: np.ndarray              # (polls, links) fresh twin reading or NaN
    shown: np.ndarray              # (polls, links) value held by the model after the poll, or NaN
    twin_up: np.ndarray            # (polls, links) status code after the poll
    dev_truth_up: np.ndarray       # (polls, devices)
    dev_twin: np.ndarray           # (polls, devices)
    dq_affected: np.ndarray        # (polls, links) bool
    status_cycle: np.ndarray       # (polls, links) bool: the link changed status during the cycle
    modelled: np.ndarray           # (polls, links) demand-model utilisation or NaN
    cycle_rows: list[dict]
    changes: list[dict]
    step_link_truth: np.ndarray    # (steps, links) bool
    step_link_twin: np.ndarray     # (steps, links) int8
    step_dev_truth: np.ndarray     # (steps, devices) bool
    step_dev_twin: np.ndarray      # (steps, devices) int8
    step_link_overwritten: np.ndarray  # (steps, links) bool: an event had set the true status, the poll undid it
    step_dev_overwritten: np.ndarray   # (steps, devices) bool
    first_step: int                # first step at which the twin has polled once
    injected: dict
    quality: dict
    ingest_ms: np.ndarray
    wall_seconds: float


def run_preset(base: Topology, preset: str, cycles: int, fault_every: float, model_every: int,
               seed: int = SEED, poll_offset: float | None = None, progress: bool = True) -> Run:
    topo = with_reality_gap(base, preset)
    began = time.perf_counter()
    # The harness reads each cycle's truth as it closes and the feed only needs the last few cycles of
    # flow records (export delay <= 2), so a short history keeps memory flat on this 300 MB-free laptop.
    net = EmulatedNetwork(topo, START, cycle_seconds=CYCLE_SECONDS, seed=seed, history_cycles=HISTORY_CYCLES)
    twin = Twin(topo, net, cycle_seconds=CYCLE_SECONDS)
    probe = SnapshotProbe(net)
    twin.drain_events()                     # as the engine's listener: only events from now on
    link_ids = list(twin.index.links)       # 1..43 in file order = emulator link index + 1
    device_ids = [twin.index.devices[name].device_id for name in net.device_names]
    n_links, n_dev = len(link_ids), len(device_ids)
    tier_of = production_link_tier()
    tiers = [tier_of((topo.devices[lk.a].role, topo.devices[lk.b].role),
                     (topo.devices[lk.a].type, topo.devices[lk.b].type)) for lk in net.links]

    spc = net.steps_per_cycle()
    offset = round((engine_poll_offset_seconds() if poll_offset is None else poll_offset) / STEP_SECONDS)
    if not 0 <= offset < spc:
        raise ValueError("the poll offset must fall inside the cycle")
    total_steps = cycles * spc + offset     # the last cycle's poll happens `offset` steps after it closes
    schedule = fault_schedule(n_links, n_dev, total_steps, fault_every, spc)
    due: dict[int, list[InjectedFault]] = defaultdict(list)
    for fault in schedule:
        due[fault.step].append(fault)

    shape = (cycles, n_links)
    truth, fresh, shown, modelled = (np.full(shape, np.nan) for _ in range(4))
    truth_up = np.zeros(shape, dtype=bool)
    twin_up = np.full(shape, -1, dtype=np.int8)
    dq_affected = np.zeros(shape, dtype=bool)
    status_cycle = np.zeros(shape, dtype=bool)
    dev_truth_up = np.zeros((cycles, n_dev), dtype=bool)
    dev_twin = np.full((cycles, n_dev), -1, dtype=np.int8)
    step_link_truth = np.zeros((total_steps, n_links), dtype=bool)
    step_link_twin = np.full((total_steps, n_links), -1, dtype=np.int8)
    step_dev_truth = np.zeros((total_steps, n_dev), dtype=bool)
    step_dev_twin = np.full((total_steps, n_dev), -1, dtype=np.int8)
    step_link_over = np.zeros((total_steps, n_links), dtype=bool)
    step_dev_over = np.zeros((total_steps, n_dev), dtype=bool)
    ingest_ms = np.full(cycles, np.nan)
    times: list[datetime] = []
    cycle_rows: list[dict] = []
    changes: list[dict] = []
    quality_totals = dict.fromkeys((f.name for f in fields(QualityReport)), 0)
    injected = {"scheduled": len(schedule), "applied": 0, "skipped_already_down": 0,
                "served_missing": 0, "served_spikes": 0, "reboots": 0}

    link_prev = net.operational().copy()
    admin_prev = net.link_admin_up.copy()
    dev_prev = net.device_up.copy()
    changed_in_cycle = np.zeros(n_links, dtype=bool)
    closed_changes = np.zeros(n_links, dtype=bool)
    injected_down: set[tuple[str, int]] = set()   # elements currently down because of the schedule
    previous_affected: set[int] = set()
    poll = 0
    first_step = total_steps
    step_time = timedelta(seconds=STEP_SECONDS)

    for step in range(total_steps):
        for fault in due.get(step, []):     # fails at the end of this step, as the emulator's own faults do
            with net.lock:
                if fault.kind == "link":
                    if not net.link_admin_up[fault.index]:
                        injected["skipped_already_down"] += 1
                        continue
                    net.fail_link(fault.index, t=net.t + step_time, minutes=fault.minutes)
                else:
                    if not net.device_up[fault.index]:
                        injected["skipped_already_down"] += 1
                        continue
                    net.fail_device(fault.index, t=net.t + step_time, minutes=fault.minutes)
            injected["applied"] += 1
            injected_down.add((fault.kind, fault.index))
        seq_before = net.cycle_seq
        twin.step()
        twin.drain_events()                 # the engine's event listener (FR2)

        # ground-truth status changes after this step
        link_now, admin_now, dev_now = net.operational().copy(), net.link_admin_up.copy(), net.device_up.copy()
        moment = net.t
        device_origin: dict[int, str] = {}
        for d in np.flatnonzero(dev_now != dev_prev):
            key = ("device", int(d))
            device_origin[int(d)] = "injected" if key in injected_down else "random"
            if dev_now[d]:
                injected_down.discard(key)
                injected["reboots"] += 1
            changes.append({"kind": "device", "index": int(d), "element": net.device_names[d], "step": step,
                            "time": moment, "new": "up" if dev_now[d] else "down", "cause": "device",
                            "origin": device_origin[int(d)]})
        for i in np.flatnonzero(link_now != link_prev):
            if admin_now[i] != admin_prev[i]:
                cause = "link"
                origin = "injected" if ("link", int(i)) in injected_down else "random"
                if link_now[i]:
                    injected_down.discard(("link", int(i)))
            else:                           # a device at one end went down or came back
                cause = "device"
                ends = [device_origin[int(e)] for e in net.ends[i] if int(e) in device_origin]
                origin = "injected" if "injected" in ends else "random"
            lk = net.links[i]
            changes.append({"kind": "link", "index": int(i), "element": f"{lk.a} <-> {lk.b}", "step": step,
                            "time": moment, "new": "up" if link_now[i] else "down", "cause": cause,
                            "origin": origin})
            changed_in_cycle[i] = True
        link_prev, admin_prev, dev_prev = link_now, admin_now, dev_now
        if net.cycle_seq != seq_before:     # a cycle closed at the end of this step (its last 10 s included)
            closed_changes = changed_in_cycle.copy()
            changed_in_cycle[:] = False

        # the engine's monitoring cycle, `offset` steps after the boundary
        polled = (step + 1 - offset) % spc == 0 and step + 1 > offset
        if polled:
            pre_link = np.array([STATUS_CODE[twin.model.link(link_id)["status"]] for link_id in link_ids])
            pre_dev = np.array([STATUS_CODE[twin.model.device(device_id)["status"]] for device_id in device_ids])
            probe.seconds = 0.0
            t0 = time.perf_counter()
            clean = twin.ingest()
            elapsed = time.perf_counter() - t0 - probe.seconds
            cycle = net.truth[-1]
            if clean is None or cycle["seq"] != poll + 1 or datetime.fromisoformat(cycle["end"]) != clean.measured_at:
                raise RuntimeError(f"poll {poll} is not aligned with ground-truth cycle {cycle['seq']}")
            ingest_ms[poll] = elapsed * 1000.0
            times.append(datetime.fromisoformat(cycle["end"]))
            for i, (entry, link_id) in enumerate(zip(cycle["links"], link_ids, strict=True)):
                truth[poll, i] = entry["utilisation_pct"]
                truth_up[poll, i] = entry["up"]
                reading = clean.links.get(link_id)
                if reading is not None and reading.utilisation_pct is not None:
                    fresh[poll, i] = reading.utilisation_pct
                edge = twin.model.link(link_id)
                shown[poll, i] = np.nan if edge["utilisation_pct"] is None else edge["utilisation_pct"]
                twin_up[poll, i] = STATUS_CODE[edge["status"]]
            for d, (entry, device_id) in enumerate(zip(cycle["devices"], device_ids, strict=True)):
                dev_truth_up[poll, d] = entry["up"]
                dev_twin[poll, d] = STATUS_CODE[twin.model.device(device_id)["status"]]
            affected = probe.affected | previous_affected
            dq_affected[poll, list(affected)] = True
            status_cycle[poll] = closed_changes
            previous_affected = probe.affected
            quality = clean.quality.as_dict()
            if poll >= WARMUP_POLLS:
                injected["served_missing"] += probe.missing
                injected["served_spikes"] += probe.spikes
                for key, value in quality.items():
                    quality_totals[key] += value
            if model_every and poll >= WARMUP_POLLS and poll % model_every == 0 and twin.model.demands:
                routed = route_demands(twin.model)
                factor = _calibration(twin.model, routed)
                modelled[poll] = [routed.utilisation.get(link_id, 0.0) * factor for link_id in link_ids]
            errors = np.abs(fresh[poll] - truth[poll])
            cycle_rows.append({
                "preset": preset, "seq": cycle["seq"], "cycle_end": cycle["end"],
                "ingest_ms": round(ingest_ms[poll], 3),
                "links_with_reading": int(np.sum(~np.isnan(fresh[poll]))),
                "mae_pts": float(np.nanmean(errors)) if np.any(~np.isnan(errors)) else None,
                "max_error_pts": float(np.nanmax(errors)) if np.any(~np.isnan(errors)) else None,
                "served_missing": probe.missing, "served_spikes": probe.spikes,
                "status_changes_in_cycle": int(closed_changes.sum()), **quality})
            if first_step == total_steps:
                first_step = step
            poll += 1
            if progress and poll % 720 == 0:
                print(f"  {preset}: {poll}/{cycles} cycles ({poll / 60:.0f} h of network time), "
                      f"{time.perf_counter() - began:.0f} s", flush=True)

        step_link_truth[step] = link_now
        step_dev_truth[step] = dev_now
        step_link_twin[step] = [STATUS_CODE[twin.model.link(link_id)["status"]] for link_id in link_ids]
        step_dev_twin[step] = [STATUS_CODE[twin.model.device(device_id)["status"]] for device_id in device_ids]
        if polled:   # the poll reads the boundary snapshot, which can be older than an event just applied
            link_code, dev_code = link_now.astype(np.int8), dev_now.astype(np.int8)
            step_link_over[step] = (pre_link == link_code) & (step_link_twin[step] != link_code)
            step_dev_over[step] = (pre_dev == dev_code) & (step_dev_twin[step] != dev_code)

    twin.close()
    return Run(preset, [f"{lk.a} <-> {lk.b}" for lk in net.links], list(net.device_names), tiers,
               np.array([lk.capacity_mbps for lk in net.links]), times, truth, truth_up, fresh, shown, twin_up,
               dev_truth_up, dev_twin, dq_affected, status_cycle, modelled, cycle_rows, changes,
               step_link_truth, step_link_twin, step_dev_truth, step_dev_twin, step_link_over, step_dev_over,
               first_step, injected,
               quality_totals, ingest_ms, time.perf_counter() - began)


# ------------------------------------------------------------------ analysis of one run
def follow_changes(run: Run) -> list[dict]:
    """Synchronisation delay of every ground-truth status change (after the twin's first poll)."""
    by_element: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for change in run.changes:
        if change["step"] >= run.first_step:
            by_element[(change["kind"], change["index"])].append(change)
    total = run.step_link_truth.shape[0]
    rows = []
    for (kind, index), items in by_element.items():
        truth = run.step_link_truth[:, index] if kind == "link" else run.step_dev_truth[:, index]
        twin = run.step_link_twin[:, index] if kind == "link" else run.step_dev_twin[:, index]
        over = run.step_link_overwritten[:, index] if kind == "link" else run.step_dev_overwritten[:, index]
        for n, change in enumerate(items):
            end = items[n + 1]["step"] if n + 1 < len(items) else total
            result = settle(truth, twin, change["step"], end)
            undone = over[change["step"]:end]
            if undone.any():                # the event had already shown it, then a poll undid it
                result["reverted"] = True
                first = int(np.argmax(undone))
                result["first"] = first if result["first"] is None else min(first, result["first"])
            rows.append({
                "preset": run.preset, "kind": kind, "element": change["element"],
                "time": change["time"].astimezone(WAT).isoformat(), "new_status": change["new"],
                "cause": change["cause"], "origin": change["origin"],
                "lasted_s": (end - change["step"]) * STEP_SECONDS if end < total else None,
                "first_agree_s": None if result["first"] is None else result["first"] * STEP_SECONDS,
                "sync_delay_s": None if result["stable"] is None else result["stable"] * STEP_SECONDS,
                "reverted": result["reverted"], "missed": result["missed"],
                "overwritten_by_poll": bool(undone.any()),
                "phase_s": int(((change["time"] - START).total_seconds()) % CYCLE_SECONDS)})
    rows.sort(key=lambda r: (r["time"], r["kind"], r["element"]))
    return rows


def summarise(run: Run, followed: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    scored = slice(WARMUP_POLLS, None)
    err = np.abs(run.fresh - run.truth)[scored]
    shown_err = np.abs(run.shown - run.truth)[scored]
    dq = run.dq_affected[scored]
    sc = run.status_cycle[scored]
    clean = ~dq & ~sc
    has = ~np.isnan(run.fresh[scored])
    model_err = np.abs(run.modelled - run.truth)[scored]

    link_rows, tier_rows = [], []
    for i, name in enumerate(run.link_names):
        stats = error_stats(err[:, i])
        link_rows.append({"preset": run.preset, "link_id": i + 1, "link": name, "tier": run.tiers[i],
                          "capacity_mbps": run.capacity[i], "truth_mean_pct": float(np.mean(run.truth[scored, i])),
                          "truth_max_pct": float(np.max(run.truth[scored, i])),
                          "coverage_pct": 100.0 * float(np.mean(has[:, i])), "mae_pts": stats["mae"],
                          "p95_pts": stats["p95"], "max_pts": stats["max"],
                          "dq_affected_cycles": int(dq[:, i].sum()),
                          "model_mae_pts": error_stats(model_err[:, i])["mae"]})
    for tier in sorted(set(run.tiers)):
        cols = [i for i, t in enumerate(run.tiers) if t == tier]
        stats = error_stats(err[:, cols])
        tier_rows.append({"preset": run.preset, "tier": tier, "links": len(cols), "link_cycles": stats["n"],
                          "coverage_pct": 100.0 * float(np.mean(has[:, cols])), "mae_pts": stats["mae"],
                          "p50_pts": stats["p50"], "p95_pts": stats["p95"], "max_pts": stats["max"],
                          "model_mae_pts": error_stats(model_err[:, cols])["mae"]})

    cycle_agree = float(np.mean(run.twin_up[scored] == run.truth_up[scored].astype(np.int8)))
    dev_cycle_agree = float(np.mean(run.dev_twin[scored] == run.dev_truth_up[scored].astype(np.int8)))
    steps = slice(run.first_step, None)
    step_agree = float(np.mean(run.step_link_twin[steps] == run.step_link_truth[steps].astype(np.int8)))
    dev_step_agree = float(np.mean(run.step_dev_twin[steps] == run.step_dev_truth[steps].astype(np.int8)))
    delays = [r["sync_delay_s"] for r in followed if r["sync_delay_s"] is not None]
    missed = sum(r["missed"] for r in followed)
    within = sum(1 for d in delays if d <= CYCLE_SECONDS)

    def status_block(rows: list[dict]) -> dict:
        ds = [r["sync_delay_s"] for r in rows if r["sync_delay_s"] is not None]
        return {"changes": len(rows), "missed": sum(r["missed"] for r in rows),
                "reverted": sum(r["reverted"] for r in rows),
                "overwritten_by_poll": sum(r["overwritten_by_poll"] for r in rows),
                "within_one_cycle": sum(1 for d in ds if d <= CYCLE_SECONDS),
                "delay_median_s": float(np.median(ds)) if ds else None,
                "delay_max_s": float(max(ds)) if ds else None}

    ingest = run.ingest_ms[scored]
    summary = {
        "cycles_scored": int(err.shape[0]),
        "link_cycles": int(err.size),
        "coverage_pct": 100.0 * float(np.mean(has)),
        "utilisation_error_pts": error_stats(err),
        "utilisation_error_clean_pts": error_stats(np.where(clean, err, np.nan)),
        "utilisation_error_dq_affected_pts": error_stats(np.where(dq, err, np.nan)),
        "utilisation_error_status_change_cycles_pts": error_stats(np.where(sc, err, np.nan)),
        "displayed_state_error_pts": error_stats(shown_err),
        "demand_model_error_pts": error_stats(model_err),
        "status": {
            "link_cycle_agreement_pct": 100.0 * cycle_agree,
            "device_cycle_agreement_pct": 100.0 * dev_cycle_agree,
            "link_step_agreement_pct": 100.0 * step_agree,
            "device_step_agreement_pct": 100.0 * dev_step_agree,
            "changes": len(followed),
            "within_one_cycle": within,
            "within_one_cycle_pct": 100.0 * within / len(followed) if followed else None,
            "missed": missed,
            "reverted": sum(r["reverted"] for r in followed),
            "overwritten_by_poll": sum(r["overwritten_by_poll"] for r in followed),
            "delay_median_s": float(np.median(delays)) if delays else None,
            "delay_p95_s": float(np.percentile(delays, 95)) if delays else None,
            "delay_max_s": float(max(delays)) if delays else None,
            "delay_max_cycles": float(max(delays)) / CYCLE_SECONDS if delays else None,
            "links": status_block([r for r in followed if r["kind"] == "link"]),
            "devices": status_block([r for r in followed if r["kind"] == "device"]),
            "injected": status_block([r for r in followed if r["origin"] == "injected"]),
            "random": status_block([r for r in followed if r["origin"] == "random"]),
        },
        "tiers": {r["tier"]: {k: r[k] for k in ("links", "coverage_pct", "mae_pts", "p95_pts", "max_pts",
                                                 "model_mae_pts")} for r in tier_rows},
        "data_quality_reported": run.quality,
        "data_quality_injected": run.injected,
        "processing_ms": {"p50": float(np.nanpercentile(ingest, 50)), "p95": float(np.nanpercentile(ingest, 95)),
                          "max": float(np.nanmax(ingest)), "mean": float(np.nanmean(ingest))},
        "wall_seconds": round(run.wall_seconds, 1),
    }
    return summary, link_rows, tier_rows


def worst_cases(run: Run, top: int = 15) -> list[dict]:
    """The largest utilisation errors, with what was going on at the time."""
    err = np.abs(run.fresh - run.truth)
    err[:WARMUP_POLLS] = np.nan
    flat = np.where(np.isnan(err), -1.0, err).ravel()
    rows = []
    for index in np.argsort(flat)[::-1][:top]:
        if flat[index] < 0:
            break
        poll, link = divmod(int(index), err.shape[1])
        rows.append({"preset": run.preset, "cycle_end": run.times[poll].astimezone(WAT).isoformat(),
                     "link": run.link_names[link], "tier": run.tiers[link], "truth_pct": run.truth[poll, link],
                     "twin_pct": run.fresh[poll, link], "error_pts": err[poll, link],
                     "previous_truth_pct": run.truth[poll - 1, link] if poll else None,
                     "dq_affected": bool(run.dq_affected[poll, link]),
                     "status_change_in_cycle": bool(run.status_cycle[poll, link])})
    return rows


# ------------------------------------------------------------------ charts
def chart_error_distribution(results: Results, summaries: dict) -> None:
    stats = [("p50", "Median"), ("p95", "95th percentile"), ("p99", "99th percentile"), ("max", "Maximum")]
    presets = list(summaries)
    figure, axes = chart(7.0, 3.4)
    width = 0.8 / len(presets)
    x = np.arange(len(stats))
    top = max(max(summaries[p]["utilisation_error_pts"][k] or 0.0 for k, _ in stats) for p in presets)
    for j, preset in enumerate(presets):
        values = [summaries[preset]["utilisation_error_pts"][k] or 0.0 for k, _ in stats]
        positions = x + (j - (len(presets) - 1) / 2) * width
        axes.bar(positions, values, width=width * 0.92, color=SERIES[j], label=f"Reality gap: {preset}", zorder=2)
        for pos, value in zip(positions, values, strict=True):
            axes.text(pos, value + top * 0.015, bar_label(value), ha="center", va="bottom", fontsize=7, color=INK_2)
    axes.axhline(TARGET_PTS, color=INK_2, linestyle=(0, (4, 3)), linewidth=1.1, label="1-point target", zorder=1)
    axes.set_xticks(x, [label for _, label in stats])
    axes.set_ylabel("Absolute utilisation error (percentage points)")
    axes.set_ylim(0, max(top, TARGET_PTS) * 1.15)
    legend(axes)
    results.save_chart(figure, "e1_error_distribution.png")


def chart_busy_link(results: Results, run: Run, link: int, polls: int) -> list[dict]:
    hours = np.array([(t - START).total_seconds() / 3600.0 for t in run.times[:polls]])
    truth, twin = run.truth[:polls, link], run.fresh[:polls, link]
    rows = [{"cycle_end": t.astimezone(WAT).isoformat(), "hours_since_start": h, "truth_pct": a,
             "twin_pct": None if np.isnan(b) else b, "twin_displayed_pct": run.shown[k, link],
             "abs_error_pts": None if np.isnan(b) else abs(b - a)}
            for k, (t, h, a, b) in enumerate(zip(run.times[:polls], hours, truth, twin, strict=True))]
    figure, axes = chart(7.5, 3.4)
    axes.plot(hours, truth, color=SERIES[0], linewidth=3.2, label="Ground truth (emulator)", zorder=2)
    axes.plot(hours, twin, color=SERIES[1], linewidth=1.1, label="Twin (from counters)", zorder=3)
    if np.nanmax(truth) >= 55.0:
        threshold_lines(axes)
        axes.set_ylim(0, 100)
    else:
        axes.set_ylim(0, max(5.0, float(np.nanmax(truth)) * 1.15))
    span = hours[-1] if len(hours) else 1.0
    step = 3 if span > 12 else (1 if span > 3 else 0.5)
    ticks = np.arange(0, span + 1e-9, step)
    axes.set_xticks(ticks, [f"{int(h) % 24:02d}:{int(round((h % 1) * 60)):02d}" for h in ticks])
    axes.set_xlim(0, span)
    axes.set_xlabel(f"Time of day (WAT), {START.strftime('%A %d %B %Y').replace(' 0', ' ')}")
    axes.set_ylabel(f"Utilisation of {run.link_names[link]} (%)")
    legend(axes)
    results.save_chart(figure, "e1_busy_link_day.png")
    return rows


def chart_sync_delay(results: Results, delays: dict[str, list[float]]) -> list[dict]:
    labels = [f"{b} s" for b in DELAY_BINS] + [f"> {DELAY_BINS[-1]} s"]
    counts = {preset: delay_histogram(values) for preset, values in delays.items()}
    figure, axes = chart(7.0, 3.2)
    width = 0.8 / max(1, len(counts))
    x = np.arange(len(labels))
    for j, (preset, values) in enumerate(counts.items()):
        axes.bar(x + (j - (len(counts) - 1) / 2) * width, values, width=width * 0.92, color=SERIES[j],
                 label=f"Reality gap: {preset}", zorder=2)
    axes.set_xticks(x, labels)
    axes.set_xlabel("Time until the twin shows the new status (network time, 10-second resolution)")
    axes.set_ylabel("Status changes (count)")
    axes.yaxis.get_major_locator().set_params(integer=True)
    legend(axes)
    results.save_chart(figure, "e1_status_delay.png")
    return [{"preset": p, "delay_bin": label, "changes": c} for p, values in counts.items()
            for label, c in zip(labels, values, strict=True)]


def chart_measured_vs_model(results: Results, summaries: dict) -> list[dict]:
    presets = list(summaries)
    rows = [{"preset": p, "measured_state_mae_pts": summaries[p]["utilisation_error_pts"]["mae"],
             "measured_state_p95_pts": summaries[p]["utilisation_error_pts"]["p95"],
             "demand_model_mae_pts": summaries[p]["demand_model_error_pts"]["mae"],
             "demand_model_p95_pts": summaries[p]["demand_model_error_pts"]["p95"],
             "demand_model_link_samples": summaries[p]["demand_model_error_pts"]["n"]} for p in presets]
    figure, axes = chart(6.0, 3.2)
    x = np.arange(len(presets))
    series = [("measured_state_mae_pts", "Measured state (counters)"),
              ("demand_model_mae_pts", "Demand model (flows routed over the twin)")]
    top = max((r[k] or 0.0) for r in rows for k, _ in series)
    for j, (key, label) in enumerate(series):
        values = [r[key] or 0.0 for r in rows]
        positions = x + (j - 0.5) * 0.38
        axes.bar(positions, values, width=0.35, color=SERIES[j], label=label, zorder=2)
        for pos, value in zip(positions, values, strict=True):
            axes.text(pos, value + top * 0.015, bar_label(value), ha="center", va="bottom", fontsize=7.5,
                      color=INK_2)
    axes.set_xticks(x, [f"Reality gap: {p}" for p in presets])
    axes.set_ylabel("Mean absolute error (percentage points)")
    axes.set_ylim(0, max(top, 0.1) * 1.18)
    legend(axes, ncol=2)
    results.save_chart(figure, "e1_measured_vs_model.png")
    return rows


# ------------------------------------------------------------------ main
def bar_label(value: float) -> str:
    if value == 0:
        return "0"
    return "<0.01" if value < 0.005 else f"{value:.2f}"


def _r(value, digits: int = 4):
    if isinstance(value, dict):
        return {k: _r(v, digits) for k, v in value.items()}
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, digits)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="E1 replication fidelity (gap G1).")
    parser.add_argument("--quick", action="store_true", help="2 hours of network time per preset, for a dry run")
    parser.add_argument("--days", type=float, default=7.0, help="network time per preset (the plan's minimum is 1)")
    parser.add_argument("--hours", type=float, default=None, help="network time per preset, overrides --days")
    parser.add_argument("--presets", default=",".join(PRESETS))
    parser.add_argument("--fault-every-minutes", type=float, default=None,
                        help="injected failure schedule (default 120, quick 30; 0 = none)")
    parser.add_argument("--model-every", type=int, default=5, help="cycles between demand-model checks")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return

    hours = args.hours if args.hours is not None else (2.0 if args.quick else args.days * 24.0)
    cycles = int(round(hours * 3600 / CYCLE_SECONDS))
    fault_every = args.fault_every_minutes if args.fault_every_minutes is not None else (30.0 if args.quick else 120.0)
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    base = load_topology(CAMPUS)
    poll_offset = engine_poll_offset_seconds()
    results = Results("E1", "Replication fidelity (G1)", config={
        "quick": args.quick, "start": START.isoformat(), "hours_per_preset": hours, "cycles_per_preset": cycles,
        "cycle_seconds": CYCLE_SECONDS, "step_seconds": STEP_SECONDS, "poll_offset_seconds": poll_offset,
        "presets": presets, "seed": SEED, "fault_seed": FAULT_SEED, "injected_fault_every_minutes": fault_every,
        "injected_link_fault_minutes": LINK_FAULT_MINUTES, "injected_device_fault_minutes": DEVICE_FAULT_MINUTES,
        "random_faults": asdict(base.faults), "data_quality": asdict(base.data_quality),
        "reality_gap": {p: asdict(with_reality_gap(base, p).reality_gap) for p in presets},
        "random_surges_per_day": base.random_surges.per_day if base.random_surges.enabled else 0,
        "demand_model_every_cycles": args.model_every, "warmup_polls_excluded": WARMUP_POLLS,
        "topology": str(CAMPUS.relative_to(ROOT)), "devices": len(base.devices), "links": len(base.links),
        "target": "MAE < 1 percentage point at the default preset; every status change within one cycle"})
    print(f"E1: {hours:g} h of network time per preset, presets {presets}, injected failure every "
          f"{fault_every:g} min", flush=True)

    summaries, all_links, all_tiers, all_changes, all_cycles, all_worst = {}, [], [], [], [], []
    delays: dict[str, list[float]] = {}
    busy_rows: list[dict] = []
    for preset in presets:
        run = run_preset(base, preset, cycles, fault_every, args.model_every, poll_offset=poll_offset)
        followed = follow_changes(run)
        summary, link_rows, tier_rows = summarise(run, followed)
        summaries[preset] = summary
        all_links += link_rows
        all_tiers += tier_rows
        all_changes += followed
        all_cycles += run.cycle_rows
        all_worst += worst_cases(run)
        delays[preset] = [r["sync_delay_s"] for r in followed if r["sync_delay_s"] is not None]
        e = summary["utilisation_error_pts"]
        print(f"  {preset}: MAE {e['mae']:.4f} pts, p95 {e['p95']:.4f}, max {e['max']:.3f}; coverage "
              f"{summary['coverage_pct']:.2f} %; status changes {summary['status']['changes']}, within one cycle "
              f"{summary['status']['within_one_cycle']}; {summary['wall_seconds']:.0f} s", flush=True)
        if preset == "default" or (not busy_rows and preset == presets[-1]):
            day = min(len(run.times), 24 * 60)
            busiest = int(np.argmax(np.mean(run.truth[WARMUP_POLLS:day], axis=0)))
            busy_rows = chart_busy_link(results, run, busiest, day)
            summaries[preset]["busy_link"] = {"link": run.link_names[busiest], "tier": run.tiers[busiest],
                                              "capacity_mbps": float(run.capacity[busiest]),
                                              "error": error_stats(np.abs(run.fresh - run.truth)[WARMUP_POLLS:day,
                                                                                                  busiest])}
        del run

    results.write_csv("link_errors.csv", all_links)
    results.write_csv("tier_errors.csv", all_tiers)
    results.write_csv("status_changes.csv", all_changes, [
        "preset", "kind", "element", "time", "new_status", "cause", "origin", "phase_s", "lasted_s",
        "first_agree_s", "sync_delay_s", "reverted", "overwritten_by_poll", "missed"])
    results.write_csv("cycles.csv", all_cycles)
    results.write_csv("worst_errors.csv", all_worst)
    results.write_csv("busy_link_day.csv", busy_rows)
    distribution = [{"preset": p, "subset": subset, **{k: summaries[p][key][k] for k in
                                                         ("n", "mae", "p50", "p95", "p99", "max", "share_under_1pt")}}
                    for p in presets for subset, key in (
                        ("all", "utilisation_error_pts"), ("clean", "utilisation_error_clean_pts"),
                        ("dq_affected", "utilisation_error_dq_affected_pts"),
                        ("status_change_cycle", "utilisation_error_status_change_cycles_pts"),
                        ("displayed_state", "displayed_state_error_pts"),
                        ("demand_model", "demand_model_error_pts"))]
    results.write_csv("error_distribution.csv", distribution)
    chart_error_distribution(results, summaries)
    results.write_csv("status_delay.csv", chart_sync_delay(results, delays))
    results.write_csv("measured_vs_model.csv", chart_measured_vs_model(results, summaries))

    reference = summaries.get("default") or summaries[presets[-1]]
    reference_name = "default" if "default" in summaries else presets[-1]
    status_ok = {p: s["status"]["missed"] == 0 and s["status"]["within_one_cycle"] == s["status"]["changes"]
                 for p, s in summaries.items()}
    results.summary = _r({
        "target_error": {
            "rule": "mean absolute utilisation error < 1 percentage point at the default reality-gap preset",
            "preset": reference_name, "mae_pts": reference["utilisation_error_pts"]["mae"],
            "met": reference["utilisation_error_pts"]["mae"] < TARGET_PTS,
            "p95_under_1pt": reference["utilisation_error_pts"]["p95"] < TARGET_PTS,
            "max_under_1pt": reference["utilisation_error_pts"]["max"] < TARGET_PTS},
        "target_status": {
            "rule": "every ground-truth status change shown by the twin within one cycle (60 s) and kept",
            "preset": reference_name, "changes": reference["status"]["changes"],
            "met": status_ok[reference_name] and reference["status"]["changes"] > 0,
            "met_per_preset": status_ok},
        "presets": summaries,
    })
    path = results.finish()
    print(f"wrote {path}")


# ------------------------------------------------------------------ self-check
def _selftest() -> None:
    # error statistics ignore missing values
    s = error_stats(np.array([0.0, 1.0, 2.0, np.nan]))
    assert s["n"] == 3 and abs(s["mae"] - 1.0) < 1e-12 and s["max"] == 2.0 and abs(s["share_under_1pt"] - 1 / 3) < 1e-12
    assert error_stats(np.array([np.nan]))["mae"] is None

    # synchronisation: truth goes down at step 2 and up at step 6
    truth = np.array([1, 1, 0, 0, 0, 0, 1, 1], dtype=bool)
    twin = np.array([1, 1, 0, 1, 0, 0, 0, 1], dtype=np.int8)        # flaps once, then lags one step
    down, up = settle(truth, twin, 2, 6), settle(truth, twin, 6, 8)
    assert down == {"first": 0, "stable": 2, "reverted": True, "missed": False}, down
    assert up == {"first": 1, "stable": 1, "reverted": False, "missed": False}, up
    assert settle(truth, np.array([1] * 8, dtype=np.int8), 2, 6)["missed"]
    assert settle(truth, np.array([1, 1, 0, 0, 0, 0, 1, 0], dtype=np.int8), 6, 8)["missed"]   # lost it at the end
    assert delay_histogram([0, 0, 10, 60, 61]) == [2, 1, 0, 0, 0, 0, 1, 1]

    # the fault schedule alternates links and devices and covers every step of the minute
    plan = fault_schedule(43, 34, 6 * 60 * 24, 60.0, 6)
    assert len(plan) == 24 and [f.kind for f in plan[:4]] == ["link", "device", "link", "device"]
    assert {f.step % 6 for f in plan if f.kind == "link"} == set(range(6))
    assert {f.step % 6 for f in plan if f.kind == "device"} == set(range(6))
    assert plan == fault_schedule(43, 34, 6 * 60 * 24, 60.0, 6)                    # reproducible
    assert all(LINK_FAULT_MINUTES[0] <= f.minutes <= LINK_FAULT_MINUTES[1] for f in plan if f.kind == "link")
    assert fault_schedule(43, 34, 1000, 0, 6) == []

    # production settings are found
    assert engine_poll_offset_seconds() == 10.0
    tier = production_link_tier()
    assert tier(("wan", "edge"), ("wan_gateway", "router")) == "wan"

    # integration: no faults, no data-quality faults, no reality gap -> the twin matches the truth exactly,
    # and the poll lines up with the ground-truth cycle it measures
    base = load_topology(CAMPUS)
    quiet = replace(base, faults=replace(base.faults, enabled=False), data_quality=DataQualityConfig())
    run = run_preset(quiet, "off", 8, 0, 0, progress=False)
    err = np.abs(run.fresh - run.truth)[WARMUP_POLLS:]
    assert not np.isnan(err).any(), "every link should have a fresh reading"
    assert float(err.max()) < 1e-3, f"max error {err.max()}"
    assert (run.twin_up[WARMUP_POLLS:] == 1).all() and not run.changes

    # integration: an injected link failure is shown at once, through the event path
    run = run_preset(quiet, "off", 12, 3.0, 0, progress=False)
    followed = follow_changes(run)
    assert followed, "the schedule should have produced status changes"
    assert all(r["sync_delay_s"] is not None and r["sync_delay_s"] <= CYCLE_SECONDS for r in followed), followed
    # the first injected failure lands on the poll step (10 s after the boundary): the event shows it, the
    # poll of the older boundary snapshot undoes it, and the next poll restores it one cycle later
    at_poll = [r for r in followed if r["phase_s"] == 10]
    assert at_poll and all(r["overwritten_by_poll"] and r["first_agree_s"] == 0 and r["sync_delay_s"] == 60
                           for r in at_poll), at_poll
    assert not any(r["overwritten_by_poll"] for r in followed if r["phase_s"] != 10), followed
    print("e1_replication selftest passed")


if __name__ == "__main__":
    main()
