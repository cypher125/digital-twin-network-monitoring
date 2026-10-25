"""E4 Safe, accurate change testing (gap G3, UC3) and recommendations.

What is measured
    Whether a change tried on the digital twin (a what-if simulation, UC3) predicts what the same
    change really does to the network, whether trying it leaves the real network and the live twin
    untouched (gap G3: the simulation works on a detached copy and has no write path), and whether
    the fixes the twin recommends for a congested link actually relieve it. The "real network" is
    the emulator (netemu). The twin's routing and traffic model and the emulator were written
    separately and share no code (an import-linter contract forbids either importing the other), so
    this compares two independent models. It is verification against a reference model, not proof
    of accuracy on real equipment.

Part A: what-if accuracy (paired runs)
    Moments. Twelve moments of network time, fixed in advance, spread over a week after the
    training history and over the day: Mon 2 Nov 2026 10:00 and 21:30, Tue 08:30 and 13:00, Wed
    15:30 and 19:30, Thu 11:00 and 23:00, Fri 02:00 and 16:30, Sat 12:00 and Sun 20:30 (all WAT).
    They cover the morning ramp, the busy teaching hours with CBT exams, the hostel evening peak,
    the night backup window and both weekend days. Each moment has its own emulated world
    (campus.yaml, 34 devices, 43 links), started 15 minutes before the moment with seed 2426 + k
    (k = 0..11; the training history used seed 7) and flash crowds drawn with seed 4400 + k
    (training: 11). In those 15 minutes the twin's own ingest path (evaluation/twin.py: the
    production telemetry adapter, preprocessing module and network model, one poll per one-minute
    cycle) builds its picture of the network, including the demand matrix it estimates from the
    flow records. Random link and device failures are switched off (they are E1's and E6's subject
    and would otherwise make the two branches differ by chance); data-quality faults stay on, so
    the twin's readings have their normal gaps and glitches.

    Changes. At the moment t, one change of each scenario type the emulator's lab interface can
    apply is tested: traffic increase, link failure, device failure, routing change, reroute
    traffic, capacity change, access-control rule and QoS policy (8 of the twin's 9 types; "add a
    link" has no lab equivalent and is listed as not testable). The parameters come from a fixed
    table (SCENARIOS below, one entry per moment and type), written before any result was seen:
    the links, devices, zones, traffic classes and sizes vary from moment to moment, mixing
    changes that should create bottlenecks (an ISP uplink failing at a busy hour, a downgrade)
    with ones that should relieve or barely matter. So every type has 12 instances (quick run: 2).

    Paired branches. At t, after the twin has ingested the cycle that ends at t, the world is
    forked with copy.deepcopy into identical branches: same traffic state, same random demand
    stream. The change branch receives the real change through EmulatedNetwork.apply_change (the
    same call as POST /lab/change); the base branch receives nothing. Both branches then run 3
    one-minute cycles, so that routing has converged (the emulator re-converges 20 s after a
    failure) and a whole cycle after convergence is measured. The twin predicts the changed state
    with run_scenario(model, type, parameters) on its live model, basis "current", from the state
    it held at t. The lab change is the twin's change translated from ids to names, as an
    administrator would carry out the change they had just tested; for reroute traffic it pins the
    exact path the twin chose. The comparison is at matched network time: the twin's prediction
    against the change branch's ground truth for the third cycle after the change (t+2 to t+3 min).

    Repeated at the three reality-gap presets (with_reality_gap): off (no multipath imbalance, no
    protocol overhead, every flow packet counted, no export delay: a sanity check), default
    (campus.yaml: 10 % multipath imbalance, 3 % overhead, flows sampled 1:100 and exported one cycle
    late) and high (25 % imbalance, 5 % overhead, 1:1000 sampling, two cycles late). The seeds and
    the moments are the same at every preset, so the demand is identical and only the gap differs.

    Counter-only demand estimate. The plan asks for one more run at the default gap with the
    counter-only (gravity) demand estimate. The twin as built has no such estimate: its demand
    matrix comes only from flow records (D11; the counter-only estimate belongs to the SNMP
    adapter, a Should item that was not built). Without flow records the demand matrix stays empty
    and every simulation would predict an idle network, so this run is not possible and is not
    reported as a result; results.json says so.

Definitions (part A)
    prediction      the twin's after_pct for a link, clipped at 100 % (a real link cannot carry
                    more than its capacity; the twin reports offered load, which may exceed 100 %).
    measured        the change branch's ground truth: the emulator's average over the cycle of the
                    busier direction as a share of capacity, which is at most 100 %.
    error           |prediction - measured| in percentage points (pts), per link and instance, for
                    links that are up in both the prediction and the change branch. A link the twin
                    predicts down but the network has up, or the reverse, is a status mismatch,
                    counted separately and left out of the error.
    busy links      links where the prediction or the measurement is 5 % or more (so a link the
                    twin wrongly loads, or wrongly leaves idle, is included).
    MAE, p95, max   mean, 95th percentile and maximum of the errors over all links and instances of
                    a scenario type (or of all types, per preset).
    no-change error the error of simply assuming the change does nothing (the twin's current
                    reading of each link), for comparison.
    effect error    |(predicted after - predicted before) - (change branch - base branch)|: the
                    error in the predicted effect of the change alone. Because both branches carry
                    the same demand, this removes the drift of demand over the 3 minutes and the
                    twin's baseline error, and isolates how well the twin models the change.
    bottleneck set  links at or above the critical threshold (90 %, D1): predicted (after_pct, links
                    the twin predicts up) and measured (change branch, third cycle, links up), whether
                    or not the two agree on the link's status. Precision = predicted bottlenecks that
                    were real / all predicted; recall = real bottlenecks that were predicted / all
                    real. Counts are summed over the instances of a type (micro-average); a ratio
                    with an empty denominator is reported as undefined, not as 0 or 100 %.
    error per link  the same errors grouped by link over all instances and types (error_by_link.csv).

Unchanged-configuration check (plan target: configuration always unchanged)
    Before and after every simulation the twin runs (each part-A scenario, and each call of the
    recommendation engine in part B), a SHA-256 is taken of the configuration of the world the
    twin is monitoring: device and link lists, link capacities, routing costs, administrative
    state of links and devices, pinned paths (reroutes), access-control blocks, QoS limits and
    lab traffic scaling. Traffic itself is not hashed. The same is done for the network model the
    simulation engine was given: once over its configuration (devices, links, capacities, costs,
    statuses) and once over its entire state including every reading and the demand matrix. In
    part A that is the twin's live model; in part B it is the snapshot the engine hands to the
    recommendation engine (runtime/engine.py copies the live model at the alert), and the live
    model is checked as well. All must be identical before and after, in every instance. The
    world's configuration is hashed once more after all of a moment's forks have received their
    changes, which checks that the forks are independent of it.

Lab-call log
    Every call of the emulator's change methods (apply_change, add_surge, reset_changes, fail_*,
    repair_*) is logged with the module that made it, the world it went to and whether the call
    stack contained any of the twin's code (digital_twin, data_collection, apps). Calls the emulator
    makes to itself are logged only if they happen while a twin simulation is running. The log is
    written to lab_calls.csv; the target is that no call comes from the twin's code and none
    happens during a simulation. lint-imports is also run and its contracts (the twin never
    imports the emulator or the lab client; the simulation engine cannot reach the adapters) are
    recorded.

Part B: recommendations (plan section 7.7), at the default reality gap
    The world. One continuous emulated campus (seed 2526, flash crowds seed 4500) runs from Monday
    2 Nov 2026 00:00 WAT. Every cycle goes through the twin's ingest path into the forecasting
    history buffer, as the engine's buffer is filled at start-up. The engine's own ForecastService
    (runtime/forecasting.py, with only its database write removed) runs every cycle in the 10
    minutes before each case, so that its alert tracker holds the episodes active at that moment
    (an episode ends after 5 calm cycles), and every cycle of each case world. It uses the active
    models from var/models (the full model, as more than a day of history exists, so its "same
    time yesterday" features see Monday), the warning rule chosen at training time and the alert
    tracker with the engine's hysteresis. Random flash crowds are switched off at 07:50 Tuesday,
    so that the only surges are the injected ones. The lab switch (POST /lab/faults
    {"random_surges": false}) only stops new days' flash crowds from being drawn, and the emulator
    draws a whole day's when the day begins, so Tuesday's that have not started yet are removed as
    well (as E3 does); one already in progress would run to its end. results.json lists both.

    Cases. Twelve surges on Tuesday 3 Nov, every 80 minutes from 08:00 to 22:40, at zones and
    traffic classes fixed in advance (CASES below): daytime surges in the schools, library and ICT
    centre, evening surges in the hostels. Each ramps up over 15 minutes and holds for 30. Its size
    is the smallest multiplier on the ladder 1.5, 2, 3, 4, 6, 8, 12 for which some link reaches
    95 % or more in a probe fork without the twin within the ramp and hold (E3's rule; a probe
    stops as soon as that happens), so that there is a problem to fix.
    The surge is injected into a fork of the world (the case world) with its own copy of the twin
    and of the forecasting state; the main world never sees it.

    Triggers. The case world runs for the surge's ramp and hold (45 cycles) with the twin and the
    forecasting running every cycle, as the engine does. Recommendations are worked out exactly as
    runtime/recommendations.py store_for_episode does, without the database rows:
      alert (forecast basis)  when a new alert episode starts on a link, recommend(snapshot of the
                              model, link, forecast at the episode's horizon, basis "forecast +h").
                              This is the production path (once per episode, D22).
      on request (current basis)  the first cycle in which the twin measures a link at 90 % or
                              more, recommend(snapshot, link) without a forecast, as an
                              administrator asking from the link's page would get.
    At most three triggers of each basis per case.

    Testing each recommendation for real. At the trigger the case world is forked again: one
    no-action branch, and one branch per recommendation that receives the recommendation's real
    equivalent through apply_change at that moment (routing cost, reroute with the twin's path,
    QoS limit on the link, capacity upgrade). Every branch runs 35 one-minute cycles (the 35-minute
    window E3 uses to judge whether a warning was followed by congestion; the longest forecast
    horizon is 30 minutes).
      success          the no-action branch has the target link at or above 90 % in at least one
                       cycle of the window, the action branch never has it at or above 90 %, and
                       the action branch has no other link at or above 90 % that the no-action
                       branch did not have.
      still congested  the no-action branch congests and the action branch also reaches 90 % on
                       the target link.
      new bottleneck   the target link is relieved, but another link reaches 90 % only because
                       of the action.
      not scorable     the no-action branch never reaches 90 % on the target link in the window:
                       the alert was a false alarm for this purpose, so the action cannot show that
                       it prevented anything. Never counted as a success.
    Success rate = successes / scorable recommendations, per action type and basis. The plan's
    rule ("the no-action branch congests and the action branch does not") is read strictly: a
    new bottleneck elsewhere is not a success. The rate on the target link alone (success + new
    bottleneck) is reported beside it as target_relieved. Each action branch is checked to have
    drawn the same random demand as its no-action branch. The capacity upgrade is planning advice,
    not an immediate fix (plan 7.7), so it is reported separately. Every recommended action has a
    lab equivalent; if one did not, it would be listed as not testable.

Target (plan section 11)
    Configuration always unchanged: every check above identical before and after, no lab call
    from the twin's code and none during a simulation. The accuracy and recommendation figures
    are reported as measured; there is no target for them.

Deviations from the plan (also in results.json, config.deviation_from_plan)
    * No run with the counter-only demand estimate (see above): not possible with the twin as built.
    * add_link is not tested: a Could type with no lab equivalent.
    The full run is the plan's size (12 instances per type at each of the three presets), so
    nothing is reduced for the laptop.

Outputs (results/E4/)
    results.json; link_errors.csv (every link of every instance); instances.csv; accuracy_by_type.csv
    (every type at every preset); error_by_link.csv; error_by_type.csv, bottleneck_by_type.csv,
    error_by_preset.csv and recommendation_success.csv (the numbers behind the charts);
    unchanged_checks.csv; lab_calls.csv; cases.csv, triggers.csv and recommendations.csv (part B);
    charts e4_error_by_type.png, e4_bottleneck_pr_by_type.png, e4_error_by_preset.png and
    e4_recommendation_success.png. Chart labels are rounded against the system (errors up,
    precision and recall down); the CSVs hold the unrounded values.

Limitations
    * The real network is the emulator. Its traffic is a smooth synthetic model, and the twin's
      calibration and routing were developed against it, so real equipment would very likely show
      larger errors than these. The reality-gap presets make the comparison harder but do not make
      it real.
    * Each part-A world starts fresh 15 minutes before its moment, so events scheduled by day
      number (registration rush on days 2-3, software-update day 11) never occur in part A, and the
      demand noise has not fully settled. The twin's demand matrix at t comes from flow records of
      the cycle(s) before t (one cycle late at the default gap), so part of the error is the
      demand moving over 3-4 minutes; the effect error removes it.
    * Twelve instances per type, one topology, one seed per moment. Bottlenecks are rare on this
      campus (only the ISP uplinks, the hostel Wi-Fi uplinks and a few downgraded links can reach
      90 %), so precision and recall rest on small counts and a 1-point error at 90 % can flip a
      link in or out of the set.
    * The twin's QoS limit on one link counts the whole of every flow that crosses the link, while
      the emulator counts only the share of each flow routed over it; where a flow is split over
      two equal-cost paths (the two ISP uplinks) the real limit bites less than predicted. The
      recommendation engine's QoS candidate is sized the same way (70 % of the whole-flow load),
      so on the ISP uplinks it may not bite at all. This is a genuine model difference, found by
      this experiment, and stays in the results.
    * Recommendations: the action is applied at the moment of the alert, the most favourable
      timing (an administrator would take minutes). Surge sizes come from an oracle probe of the
      future, so every case is known to congest some link, though not necessarily the one alerted.
      The success definition uses single one-minute cycles at 90 %. Twelve cases on one weekday at
      the default gap only; the counts per action type are small.
    * The harness, the twin and the emulator run in one Python process. The twin reads the
      emulator only through the production adapter over an in-memory transport that answers as the
      HTTP feed does; the lab-call log and the import contracts show it has no other path, but this
      is not the separate-process deployment.

Quick mode (--quick) checks the pipeline in about five minutes: 2 moments (Mon 10:00 and 21:30) at
all three presets (2 instances per type), and 1 recommendation case (Tue 08:00) in a world started
at 06:45, so the short-history model serves. Its numbers are not for Chapter 4. The full run takes
about 25-40 minutes on the 2-core Celeron laptop (results.json, summary.timings, has the parts).

    python -m evaluation.e4_sim_vs_reality [--quick] [--presets off,default,high] [--moments 12]
                                           [--cases 12] [--no-recommendations]
    python -m evaluation.e4_sim_vs_reality --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import networkx as nx
import numpy as np

from digital_twin.network_model import INTERNET as TWIN_INTERNET
from digital_twin.network_model import NetworkModel, routing_graph
from digital_twin.simulation_engine import REGISTRY, ScenarioError, recommend, run_scenario
from netemu.network import EmulatedNetwork
from netemu.topology import INTERNET as LAB_INTERNET
from netemu.topology import Topology, load_topology, with_reality_gap

from .common import BACKEND, INK_2, MUTED, ROOT, SERIES, Results, chart, git_commit, legend
from .twin import Twin

CAMPUS = ROOT / "data" / "topologies" / "campus.yaml"
WAT = timezone(timedelta(hours=1), "WAT")
PRESETS = ("off", "default", "high")
CYCLE_SECONDS = 60
CRITICAL_PCT = 90.0           # D1; checked against the twin's settings in part B
BUSY_PCT = 5.0
WARMUP_CYCLES = 15            # part A: the twin's ingest before each moment
SETTLE_CYCLES = 3             # part A: cycles after the change; the last one is compared
HISTORY_CYCLES = 40           # emulator truth / flow records kept in memory (forks copy them)
SEED_A, FLASH_SEED_A = 2026 + 400, 4400
SEED_B, FLASH_SEED_B = 2026 + 500, 4500

# part B
REC_WORLD_START = datetime(2026, 11, 2, 0, 0, tzinfo=WAT)          # Monday: a day of history first
QUICK_REC_WORLD_START = datetime(2026, 11, 3, 6, 45, tzinfo=WAT)   # quick: short-history model
FORECAST_LEAD_MINUTES = 10    # the engine's forecasting runs for the 10 minutes before each case
RAMP_MINUTES, HOLD_MINUTES = 15, 30
LADDER = (1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)
PROBE_PEAK_PCT = 95.0
WINDOW_CYCLES = 35
MAX_TRIGGERS = 3              # per basis and case
QUICK_MOMENTS, QUICK_CASES = 2, 1

TYPES = ("traffic_increase", "link_failure", "device_failure", "routing_change", "reroute_traffic",
         "capacity_change", "access_control_rule", "qos_policy")
NOT_TESTABLE_TYPES = {"add_link": "the lab interface cannot install a new link in the emulated network"}
TYPE_LABEL = {"traffic_increase": "Traffic\nincrease", "link_failure": "Link\nfailure",
              "device_failure": "Device\nfailure", "routing_change": "Routing\nchange",
              "reroute_traffic": "Reroute\ntraffic", "capacity_change": "Capacity\nchange",
              "access_control_rule": "Access\nrule", "qos_policy": "QoS\npolicy"}
ACTIONS = ("routing_change", "reroute_traffic", "qos_policy", "capacity_change")
ACTION_LABEL = {"routing_change": "Raise routing cost", "reroute_traffic": "Reroute largest flow",
                "qos_policy": "QoS limit on class", "capacity_change": "Capacity upgrade\n(planning advice)"}
BASES = ("forecast", "current")
BASIS_LABEL = {"forecast": "On alert (forecast load)", "current": "On request (current load)"}

MOMENTS = [datetime(2026, 11, d, h, m, tzinfo=WAT) for d, h, m in (
    (2, 10, 0), (2, 21, 30), (3, 8, 30), (3, 13, 0), (4, 15, 30), (4, 19, 30),
    (5, 11, 0), (5, 23, 0), (6, 2, 0), (6, 16, 30), (7, 12, 0), (8, 20, 30))]

ISP_A, ISP_B = ("ISP-A-GW", "EDGE-RTR-01"), ("ISP-B-GW", "EDGE-RTR-01")
FW_C1, FW_C2 = ("FW-01", "CORE-SW-01"), ("FW-01", "CORE-SW-02")

# Pre-registered part-A instances, one per moment (index = moment k), in names.
SCENARIOS: dict[str, list[dict]] = {
    "link_failure": [{"link": lk} for lk in (
        ISP_A, ("DIST-HOSTEL", "CORE-SW-01"), ISP_B, FW_C1, ("DIST-SCI", "CORE-SW-02"), ISP_A,
        ("CORE-SW-01", "DC-SW-01"), ("DIST-HOSTEL", "AP-HOSTEL-01"), ISP_B, FW_C2,
        ("DIST-LIB", "CORE-SW-01"), ISP_A)],
    "device_failure": [{"device": d} for d in (
        "CORE-SW-01", "ISP-B-GW", "CORE-SW-02", "DIST-CBT", "ISP-A-GW", "AP-HOSTEL-02", "DC-SW-01",
        "CORE-SW-02", "SRV-LMS", "DIST-SOT", "CORE-SW-01", "ISP-B-GW")],
    "routing_change": [{"costs": c} for c in (
        [(ISP_B, 40)], [(ISP_A, 40)], [(FW_C1, 30)], [(("DIST-CBT", "CORE-SW-01"), 25)], [(ISP_A, 5)],
        [(("DIST-HOSTEL", "CORE-SW-02"), 50)], [(("CORE-SW-01", "DC-SW-01"), 20)],
        [(ISP_B, 20), (("DIST-HOSTEL", "CORE-SW-01"), 30)], [(ISP_A, 40)],
        [(FW_C2, 30), (("DIST-ENG", "CORE-SW-01"), 30)], [(("DIST-LIB", "CORE-SW-02"), 15)], [(ISP_B, 5)])],
    "reroute_traffic": [{"source": s, "dest": d, "cls": c, "avoid": [a]} for s, d, c, a in (
        ("ACC-SCI-01", "internet", None, ISP_A), ("AP-HOSTEL-01", "internet", "video", ISP_B),
        ("ACC-SOT-01", "SRV-LMS", None, ("CORE-SW-01", "DC-SW-01")),
        ("ACC-CBT-01", "SRV-CBT", "cbt", ("DIST-CBT", "CORE-SW-01")),
        ("ACC-ENG-01", "internet", None, ("DIST-ENG", "CORE-SW-01")),
        ("ACC-HOSTEL-01", "internet", None, ISP_A), ("ACC-LIB-01", "SRV-LIB", "library", ("DIST-LIB", "CORE-SW-02")),
        ("AP-HOSTEL-02", "internet", None, ISP_A), ("ACC-HOSTEL-01", "internet", "web", FW_C1),
        ("AP-SOT-01", "internet", "web", ISP_B), ("ACC-ICT-01", "internet", None, FW_C1),
        ("AP-HOSTEL-01", "internet", None, ISP_B))],
    "capacity_change": [{"link": lk, "capacity": c} for lk, c in (
        (ISP_B, 150), (("DIST-HOSTEL", "AP-HOSTEL-01"), 1000), (ISP_A, 200), (("DC-SW-01", "SRV-CBT"), 300),
        (ISP_B, 300), (("DIST-HOSTEL", "AP-HOSTEL-02"), 50), (FW_C1, 100), (("DIST-HOSTEL", "AP-HOSTEL-01"), 60),
        (ISP_A, 100), (("EDGE-RTR-01", "FW-01"), 300), (ISP_B, 100), (("DIST-HOSTEL", "AP-HOSTEL-02"), 200))],
    "traffic_increase": [{"zone": z, "cls": c, "percent": p} for z, c, p in (
        ("SCI", "video", 150), ("HOSTEL", None, 40), (None, "web", 30), ("CBT", "cbt", 30), ("SOT", None, 100),
        ("HOSTEL", "video", 80), ("LIB", "library", 200), ("HOSTEL", "web", 60), (None, None, 50),
        ("ENG", None, -50), ("LIB", "video", 200), ("HOSTEL", "video", 120))],
    "access_control_rule": [{"zone": z, "cls": c, "source": s, "dest": d} for z, c, s, d in (
        (None, "video", None, None), ("HOSTEL", "video", None, None), ("SCI", None, None, "internet"),
        (None, "web", None, None), (None, None, "ACC-SOT-01", None), ("HOSTEL", "web", None, None),
        (None, "elearning", None, None), ("HOSTEL", None, None, None), (None, "bulk", None, None),
        ("ENG", "video", None, None), ("LIB", "library", None, None), (None, "video", None, None))],
    "qos_policy": [{"cls": c, "limit": m, "link": lk} for c, m, lk in (
        ("video", 40, ISP_B), ("video", 100, None), ("web", 50, ISP_A), ("cbt", 150, ("DC-SW-01", "SRV-CBT")),
        ("elearning", 20, None), ("video", 10, ("DIST-HOSTEL", "AP-HOSTEL-01")), ("web", 80, None),
        ("web", 20, ("DIST-HOSTEL", "CORE-SW-01")), ("bulk", 30, None), ("video", 60, ISP_A),
        ("library", 10, None), ("video", 8, ("DIST-HOSTEL", "AP-HOSTEL-02")))],
}


@dataclass(frozen=True)
class Case:
    """A pre-registered part-B surge."""

    id: str
    time: datetime
    zone: str
    cls: str


CASES = [Case(f"R{i + 1:02d}", datetime(2026, 11, 3, 8, 0, tzinfo=WAT) + timedelta(minutes=80 * i), z, c)
         for i, (z, c) in enumerate((
             ("SCI", "video"), ("SOT", "web"), ("ENG", "video"), ("LIB", "video"), ("ICT", "web"),
             ("SCI", "web"), ("SOT", "video"), ("HOSTEL", "video"), ("HOSTEL", "web"), ("HOSTEL", "video"),
             ("HOSTEL", "elearning"), ("HOSTEL", "web")))]


def log(message: str) -> None:
    print(f"[E4 {time.strftime('%H:%M:%S')}] {message}", flush=True)


TIMINGS: dict[str, list] = defaultdict(lambda: [0.0, 0])   # name -> [seconds, calls], for the run-time estimate


@contextmanager
def timed(name: str):
    began = time.perf_counter()
    try:
        yield
    finally:
        entry = TIMINGS[name]
        entry[0] += time.perf_counter() - began
        entry[1] += 1


def timing_summary() -> dict:
    return {name: {"seconds": round(total, 2), "calls": calls, "ms_per_call": round(1000 * total / calls, 1)}
            for name, (total, calls) in sorted(TIMINGS.items()) if calls}


class NotTestable(Exception):
    """A twin change with no equivalent in the lab interface."""


# ------------------------------------------------------------------ scoring (unit-tested)
def error_stats(errors) -> dict:
    """Mean, 95th percentile and maximum of absolute errors, in percentage points."""
    e = np.asarray(list(errors), dtype=float)
    e = e[~np.isnan(e)]
    if e.size == 0:
        return {"n": 0, "mae": None, "p50": None, "p95": None, "max": None}
    return {"n": int(e.size), "mae": float(e.mean()), "p50": float(np.percentile(e, 50)),
            "p95": float(np.percentile(e, 95)), "max": float(e.max())}


def set_counts(predicted: set, measured: set) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives) of a predicted set against the measured set."""
    return len(predicted & measured), len(predicted - measured), len(measured - predicted)


def precision_recall(tp: int, fp: int, fn: int) -> tuple[float | None, float | None]:
    """Precision and recall; None when the denominator is empty (undefined, not 0 or 1)."""
    return (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)


def judge(no_action: np.ndarray, action: np.ndarray, target: int, critical: float = CRITICAL_PCT) -> dict:
    """Verdict on one recommendation from its two branches, arrays (cycles, links) of utilisation %."""
    congested = bool((no_action[:, target] >= critical).any())
    still = bool((action[:, target] >= critical).any())
    base_hot = (no_action >= critical).any(axis=0)
    act_hot = (action >= critical).any(axis=0)
    new = [int(j) for j in np.flatnonzero(act_hot & ~base_hot) if j != target]
    if not congested:
        outcome = "not_scorable"
    elif still:
        outcome = "still_congested"
    elif new:
        outcome = "new_bottleneck"
    else:
        outcome = "success"
    onset = int(np.argmax(no_action[:, target] >= critical)) + 1 if congested else None
    return {"outcome": outcome, "no_action_peak_pct": float(no_action[:, target].max()),
            "action_peak_pct": float(action[:, target].max()), "new_bottleneck_columns": new,
            "no_action_onset_cycle": onset}


def digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def network_configuration(net: EmulatedNetwork) -> dict:
    """The configuration of the emulated network (not its traffic): what a write path would change."""
    return {
        "devices": list(net.device_names),
        "links": [[lk.a, lk.b] for lk in net.links],
        "capacity_mbps": net.capacity.tolist(),
        "routing_cost": net.cost.tolist(),
        "link_admin_up": net.link_admin_up.tolist(),
        "device_up": net.device_up.tolist(),
        "pinned_paths": {str(k): list(v) for k, v in sorted(net.pinned_paths.items())},
        "access_rules_blocked": net.traffic.blocked.tolist(),
        "qos_limits": [[c, float(m), None if lk is None else int(lk)] for c, m, lk in net.qos_caps],
        "lab_traffic_scale": net.traffic.scale.tolist(),
    }


def model_configuration(model: NetworkModel) -> dict:
    nodes = [[n, d["name"], d["device_type"], d["status"], d["configuration"]]
             for n, d in sorted(model.graph.nodes(data=True), key=lambda item: item[0])]
    edges = [[d["link_id"], u, v, d["capacity_mbps"], d["cost"], d["explicit_cost"], d["status"]]
             for u, v, d in sorted(model.graph.edges(data=True), key=lambda item: item[2]["link_id"])]
    return {"devices": nodes, "links": edges, "link_ends": sorted(model.link_ends.items()),
            "thresholds": [model.warning_pct, model.critical_pct]}


def model_state(model: NetworkModel) -> dict:
    """Everything the live model holds: configuration, every reading and the demand matrix."""
    return {"configuration": model_configuration(model),
            "nodes": [[n, d.get("cpu_util"), d.get("traffic_in"), d.get("traffic_out"), d.get("error_count")]
                      for n, d in sorted(model.graph.nodes(data=True), key=lambda item: item[0])],
            "links": [[d["link_id"], d.get("traffic_out"), d.get("traffic_in"), d.get("utilisation_pct"),
                       d.get("error_count")]
                      for _, _, d in sorted(model.graph.edges(data=True), key=lambda item: item[2]["link_id"])],
            "demands": [[d.source_id, d.dest_id, d.cls, d.mbps, d.down_ratio] for d in model.demands],
            "timestamp": model.timestamp}


@dataclass
class Fingerprint:
    network: str
    model_config: str
    model_state: str

    @classmethod
    def take(cls, net: EmulatedNetwork, model: NetworkModel) -> Fingerprint:
        return cls(digest(network_configuration(net)), digest(model_configuration(model)), digest(model_state(model)))


# ------------------------------------------------------------------ lab-call log
TWIN_PACKAGES = ("digital_twin", "data_collection", "apps")
LAB_METHODS = ("apply_change", "add_surge", "reset_changes", "fail_link", "fail_device", "repair_link",
               "repair_device")


class LabLog:
    """Logs every call of the emulator's change methods, with who made it (class-level wrappers, so
    forks made with copy.deepcopy are covered too)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.simulating = False
        self.labels: dict[int, str] = {}
        self._originals: dict[str, object] = {}

    def install(self) -> None:
        for name in LAB_METHODS:
            original = getattr(EmulatedNetwork, name)
            self._originals[name] = original
            setattr(EmulatedNetwork, name, self._wrap(name, original))

    def uninstall(self) -> None:
        for name, original in self._originals.items():
            setattr(EmulatedNetwork, name, original)
        self._originals.clear()

    def _wrap(self, name: str, original):
        lab_log = self

        def wrapper(net, *args, **kwargs):
            frame = sys._getframe(1)
            modules = []
            while frame is not None:
                modules.append(str(frame.f_globals.get("__name__", "")))
                frame = frame.f_back
            caller = modules[0]
            if not caller.startswith("netemu") or lab_log.simulating:
                lab_log.calls.append({
                    "n": len(lab_log.calls) + 1, "method": name, "world": lab_log.labels.get(id(net), "unlabelled"),
                    "caller": "evaluation.e4_sim_vs_reality" if caller == "__main__" else caller,
                    "from_twin_code": any(m.split(".")[0] in TWIN_PACKAGES for m in modules),
                    "during_twin_simulation": lab_log.simulating,
                    "detail": json.dumps(args[0] if name == "apply_change" and args else list(args)[:5], default=str),
                })
            return original(net, *args, **kwargs)

        wrapper.__wrapped__ = original
        return wrapper

    @contextmanager
    def simulation(self):
        self.simulating = True
        try:
            yield
        finally:
            self.simulating = False

    def summary(self) -> dict:
        return {"calls": len(self.calls), "from_twin_code": sum(c["from_twin_code"] for c in self.calls),
                "during_twin_simulation": sum(c["during_twin_simulation"] for c in self.calls),
                "by_method": dict(sorted(_count(c["method"] for c in self.calls).items())),
                "callers": sorted({c["caller"] for c in self.calls})}


def _count(items) -> dict:
    out: dict = defaultdict(int)
    for item in items:
        out[item] += 1
    return dict(out)


# ------------------------------------------------------------------ worlds and forks
def world_topology(base: Topology, preset: str, flash_seed: int) -> Topology:
    topo = replace(base, random_surges=replace(base.random_surges, seed=flash_seed))
    return with_reality_gap(topo, preset)


def fork(net: EmulatedNetwork, label: str, lab_log: LabLog) -> EmulatedNetwork:
    """An identical branch of the world. The topology description is immutable and shared."""
    clone = copy.deepcopy(net, {id(net.topo): net.topo})
    lab_log.labels[id(clone)] = label
    return clone


def fork_twin(twin: Twin, net: EmulatedNetwork) -> Twin:
    """A copy of the twin's ingest state (model, preprocessor, feed cursors) reading another world."""
    clone = Twin(twin.topo, net, cycle_seconds=twin.cycle_seconds)
    clone.model = copy.deepcopy(twin.model)
    clone.preprocessor = copy.deepcopy(twin.preprocessor)
    clone.feed._flow_cursor = twin.feed._flow_cursor
    clone.feed._event_cursor = twin.feed._event_cursor
    return clone


def fork_service(service):
    """A copy of the forecasting state (history buffer, alert tracker); the trained models are shared."""
    clone = copy.copy(service)
    clone.predictor = copy.copy(service.predictor)
    clone.buffer = copy.deepcopy(service.buffer)
    clone.tracker = copy.deepcopy(service.tracker)
    clone.last_rows = list(service.last_rows)
    return clone


def truth_row(net: EmulatedNetwork) -> tuple[np.ndarray, np.ndarray]:
    links = net.truth[-1]["links"]
    return (np.array([x["utilisation_pct"] for x in links], dtype=float),
            np.array([x["up"] for x in links], dtype=bool))


def emulator_cycle(net: EmulatedNetwork) -> tuple[np.ndarray, np.ndarray]:
    """One monitoring cycle of a branch with no twin attached; returns its ground truth.

    Paired branches are both twin-less, so they draw from the emulator's random stream alike. The
    demand comes from the traffic model's own random stream, which nothing else draws from, so it
    is identical in every branch of a fork whatever else happens (checked per instance)."""
    for _ in range(net.steps_per_cycle()):
        net.step()
    return truth_row(net)


# ------------------------------------------------------------------ twin <-> lab mapping
def twin_params(kind: str, spec: dict, twin: Twin) -> dict:
    """Run_scenario parameters (ids) for a pre-registered instance (names)."""
    dev = {name: ref.device_id for name, ref in twin.index.devices.items()}

    def dest(value):
        return "internet" if value == "internet" else dev[value]

    if kind == "link_failure":
        return {"link_id": twin.link_id(*spec["link"])}
    if kind == "device_failure":
        return {"device_id": dev[spec["device"]]}
    if kind == "routing_change":
        return {"link_costs": [{"link_id": twin.link_id(*lk), "cost": cost} for lk, cost in spec["costs"]]}
    if kind == "capacity_change":
        return {"link_id": twin.link_id(*spec["link"]), "capacity_mbps": spec["capacity"]}
    if kind == "reroute_traffic":
        out = {"source_id": dev[spec["source"]], "dest": dest(spec["dest"]),
               "avoid_link_ids": [twin.link_id(*lk) for lk in spec["avoid"]]}
        if spec.get("cls"):
            out["cls"] = spec["cls"]
        return out
    out: dict = {}
    if spec.get("zone"):
        out["source_zone"] = spec["zone"]
    if spec.get("cls"):
        out["cls"] = spec["cls"]
    if spec.get("source"):
        out["source_id"] = dev[spec["source"]]
    if spec.get("dest"):
        out["dest"] = dest(spec["dest"])
    if kind == "traffic_increase":
        return {"percent": spec["percent"], **out}
    if kind == "access_control_rule":
        return out
    if kind == "qos_policy":
        out["limit_mbps"] = spec["limit"]
        if spec.get("link"):
            out["link_id"] = twin.link_id(*spec["link"])
        return out
    raise ValueError(kind)


def reroute_path(model: NetworkModel, params: dict) -> list:
    """The path the twin's reroute_traffic chooses (scenarios._a_reroute: the router's graph without
    the avoided links, shortest by routing cost), checked against the scenario's own pinned paths."""
    g = routing_graph(model)
    for link_id in params["avoid_link_ids"]:
        u, v = model.link_ends[link_id]
        if g.has_edge(u, v):
            g.remove_edge(u, v)
    dest = TWIN_INTERNET if params["dest"] == "internet" else params["dest"]
    path = nx.shortest_path(g, params["source_id"], dest, weight="cost")
    copy_ = model.copy()
    pinned = REGISTRY["reroute_traffic"].apply(copy_, list(copy_.demands), params).pinned
    if any(list(p) != list(path) for p in pinned.values()):
        raise RuntimeError("the reroute path differs from the scenario's own choice")
    return path


def to_lab(kind: str, params: dict, model: NetworkModel) -> dict:
    """The real-network equivalent of a validated twin change, as POST /lab/change takes it."""
    def name(device_id):
        return model.name_of(device_id)

    def link(link_id):
        u, v = model.link_ends[link_id]
        return [name(u), name(v)]

    def dest(value):
        return LAB_INTERNET if value == "internet" else name(value)

    if kind in NOT_TESTABLE_TYPES:
        raise NotTestable(NOT_TESTABLE_TYPES[kind])
    if kind == "link_failure":
        return {"type": kind, "link": link(params["link_id"])}
    if kind == "device_failure":
        return {"type": kind, "device": name(params["device_id"])}
    if kind == "routing_change":
        return {"type": kind, "link_costs": [{"link": link(i["link_id"]), "cost": float(i["cost"])}
                                             for i in params["link_costs"]]}
    if kind == "capacity_change":
        return {"type": kind, "link": link(params["link_id"]), "capacity_mbps": float(params["capacity_mbps"])}
    filters: dict = {}
    if params.get("source_zone"):
        filters["zone"] = params["source_zone"]
    if params.get("cls"):
        filters["cls"] = params["cls"]
    if params.get("source_id") is not None:
        filters["source"] = name(params["source_id"])
    if params.get("dest") is not None:
        filters["dest"] = dest(params["dest"])
    if kind == "traffic_increase":
        return {"type": kind, "percent": float(params["percent"]), **filters}
    if kind == "access_control_rule":
        return {"type": kind, **filters}
    if kind == "qos_policy":
        if set(filters) - {"cls"}:
            raise NotTestable("the lab's QoS policy has no source or destination filter")
        out = {"type": kind, "cls": params["cls"], "limit_mbps": float(params["limit_mbps"])}
        if params.get("link_id") is not None:
            out["link"] = link(params["link_id"])
        return out
    if kind == "reroute_traffic":
        path = [TWIN_INTERNET if n == TWIN_INTERNET else name(n) for n in reroute_path(model, params)]
        return {"type": kind, **filters, "path": [LAB_INTERNET if n == TWIN_INTERNET else n for n in path]}
    raise NotTestable(f"no lab equivalent for {kind}")


# ------------------------------------------------------------------ part A
@dataclass
class PartA:
    link_rows: list
    instance_rows: list
    checks: list
    seconds: float = 0.0


def score_links(outcome, measured: np.ndarray, measured_up: np.ndarray, base: np.ndarray, base_up: np.ndarray,
                critical: float) -> tuple[list[dict], dict]:
    """Per-link comparison of one simulation with its change branch (and base branch)."""
    rows, predicted_set, measured_set, mismatches = [], set(), set(), 0
    for lk in outcome.links:
        i = lk.link_id - 1
        pred_up, meas_up = lk.status_after != "down", bool(measured_up[i])
        pred = min(lk.after_pct, 100.0) if pred_up else 0.0
        row = {"link_id": lk.link_id, "link": lk.label, "capacity_mbps": lk.capacity_mbps,
               "observed_now_pct": lk.observed_pct, "before_pct": lk.before_pct, "after_pct": lk.after_pct,
               "predicted_pct": pred, "predicted_up": pred_up, "measured_pct": float(measured[i]),
               "measured_up": meas_up, "base_pct": float(base[i]), "base_up": bool(base_up[i]),
               "error": None, "busy": None, "no_change_error": None, "effect_error": None}
        # the sets do not depend on the status agreeing: a real bottleneck on a link the twin
        # wrongly predicts down is missed, and a predicted one on a link really down is false
        if pred_up and lk.after_pct >= critical:
            predicted_set.add(lk.link_id)
        if meas_up and measured[i] >= critical:
            measured_set.add(lk.link_id)
        if pred_up != meas_up:
            mismatches += 1
        elif pred_up:
            row["error"] = abs(pred - float(measured[i]))
            row["busy"] = max(pred, float(measured[i])) >= BUSY_PCT
            if lk.observed_pct is not None:
                row["no_change_error"] = abs(float(lk.observed_pct) - float(measured[i]))
            if base_up[i]:
                predicted_effect = pred - min(lk.before_pct, 100.0)
                row["effect_error"] = abs(predicted_effect - (float(measured[i]) - float(base[i])))
        rows.append(row)
    tp, fp, fn = set_counts(predicted_set, measured_set)
    errors = [r["error"] for r in rows if r["error"] is not None]
    busy = [r["error"] for r in rows if r["busy"]]
    summary = {"links_scored": len(errors), "status_mismatches": mismatches,
               "mae": error_stats(errors)["mae"], "busy_mae": error_stats(busy)["mae"],
               "max_error": error_stats(errors)["max"],
               "predicted_bottlenecks": sorted(predicted_set), "measured_bottlenecks": sorted(measured_set),
               "tp": tp, "fp": fp, "fn": fn}
    return rows, summary


def run_moment(base: Topology, preset: str, k: int, moment: datetime, lab_log: LabLog, out: PartA,
               critical: float) -> None:
    topo = world_topology(base, preset, FLASH_SEED_A + k)
    net = EmulatedNetwork(topo, moment - timedelta(minutes=WARMUP_CYCLES), cycle_seconds=CYCLE_SECONDS,
                          seed=SEED_A + k, history_cycles=HISTORY_CYCLES)
    net.random_faults = False
    lab_log.labels[id(net)] = f"{preset}/M{k + 1:02d} monitored world"
    twin = Twin(topo, net, cycle_seconds=CYCLE_SECONDS)
    with timed(f"part A warm-up ({WARMUP_CYCLES} twin cycles)"):
        twin.advance(WARMUP_CYCLES)
    if twin.model.timestamp != moment or not twin.model.demands:
        raise RuntimeError(f"twin not ready at {moment}: model time {twin.model.timestamp}, "
                           f"{len(twin.model.demands)} demands")
    names = [f"{lk.a} <-> {lk.b}" for lk in net.links]
    if names != [twin.model.link_label(i) for i in range(1, len(names) + 1)]:
        raise RuntimeError("twin link ids do not follow the emulator's link order")
    world_before = digest(network_configuration(net))

    base_branch = fork(net, f"{preset}/M{k + 1:02d} base", lab_log)
    for _ in range(SETTLE_CYCLES):
        base_util, base_up = emulator_cycle(base_branch)
    for kind in TYPES:
        spec = SCENARIOS[kind][k % len(SCENARIOS[kind])]
        instance = f"{preset}/M{k + 1:02d}/{kind}"
        params = twin_params(kind, spec, twin)
        row = {"preset": preset, "moment": f"M{k + 1:02d}", "time_wat": f"{moment:%a %d %b %H:%M}",
               "scenario_type": kind, "instance": instance, "spec": json.dumps(spec, default=list),
               "twin_parameters": json.dumps(params), "status": "scored"}
        before = Fingerprint.take(net, twin.model)
        began = time.perf_counter()
        try:
            with lab_log.simulation():
                outcome = run_scenario(twin.model, kind, params)
        except ScenarioError as exc:
            outcome = None
            row.update(status="rejected by the twin", note=str(exc))
        row["simulation_ms"] = round((time.perf_counter() - began) * 1000, 1)
        after = Fingerprint.take(net, twin.model)
        out.checks.append({"part": "A", "instance": instance, "check": "run_scenario",
                           "network_configuration_unchanged": before.network == after.network,
                           "twin_model_configuration_unchanged": before.model_config == after.model_config,
                           "twin_model_state_unchanged": before.model_state == after.model_state,
                           "network_sha256": after.network})
        if outcome is None:
            out.instance_rows.append(row)
            continue
        try:
            change = to_lab(kind, outcome.parameters, twin.model)
        except NotTestable as exc:
            row.update(status="not testable", note=str(exc))
            out.instance_rows.append(row)
            continue
        branch = fork(net, f"{instance} change", lab_log)
        branch.apply_change(change)
        for _ in range(SETTLE_CYCLES):
            util, up = emulator_cycle(branch)
        same_demand = bool(np.array_equal(branch.traffic.noise_state, base_branch.traffic.noise_state))
        rows, summary = score_links(outcome, util, up, base_util, base_up, critical)
        for r in rows:
            out.link_rows.append({"preset": preset, "moment": f"M{k + 1:02d}", "scenario_type": kind, **r})
        row.update(lab_change=json.dumps(change), calibration_factor=outcome.calibration_factor,
                   same_random_demand=same_demand, **{k2: (json.dumps(v) if isinstance(v, list) else v)
                                                      for k2, v in summary.items()})
        out.instance_rows.append(row)
    world_after = digest(network_configuration(net))
    out.checks.append({"part": "A", "instance": f"{preset}/M{k + 1:02d}", "check": "after all forks changed",
                       "network_configuration_unchanged": world_before == world_after,
                       "twin_model_configuration_unchanged": None, "twin_model_state_unchanged": None,
                       "network_sha256": world_after})
    twin.close()


def run_part_a(base: Topology, presets: list[str], moments: list[datetime], lab_log: LabLog,
               critical: float) -> PartA:
    out = PartA([], [], [])
    began = time.perf_counter()
    for preset in presets:
        for k, moment in enumerate(moments):
            t0 = time.perf_counter()
            run_moment(base, preset, k, moment, lab_log, out, critical)
            log(f"part A {preset:>7} M{k + 1:02d} {moment:%a %H:%M}: {time.perf_counter() - t0:.1f} s")
    out.seconds = time.perf_counter() - began
    return out


def accuracy_tables(part: PartA, presets: list[str]) -> tuple[list[dict], list[dict]]:
    """Per (preset, type) and per preset (all types) accuracy rows."""
    by_type, by_preset = [], []
    for preset in presets:
        for kind in [*TYPES, None]:
            links = [r for r in part.link_rows if r["preset"] == preset and (kind is None or r["scenario_type"] == kind)]
            inst = [r for r in part.instance_rows if r["preset"] == preset and (kind is None or r["scenario_type"] == kind)]
            scored = [r for r in inst if r["status"] == "scored"]
            errors = [r["error"] for r in links if r["error"] is not None]
            busy = [r["error"] for r in links if r["busy"]]
            tp, fp, fn = (sum(r[x] for r in scored) for x in ("tp", "fp", "fn"))
            precision, recall = precision_recall(tp, fp, fn)
            all_e, busy_e = error_stats(errors), error_stats(busy)
            row = {"preset": preset, "scenario_type": kind or "all", "instances": len(inst), "scored": len(scored),
                   "rejected_or_not_testable": len(inst) - len(scored),
                   "link_samples": all_e["n"], "mae": all_e["mae"], "p95": all_e["p95"], "max": all_e["max"],
                   "busy_samples": busy_e["n"], "busy_mae": busy_e["mae"], "busy_p95": busy_e["p95"],
                   "busy_max": busy_e["max"],
                   "no_change_mae": error_stats(r["no_change_error"] for r in links if r["no_change_error"] is not None)["mae"],
                   "busy_no_change_mae": error_stats(r["no_change_error"] for r in links
                                                     if r["busy"] and r["no_change_error"] is not None)["mae"],
                   "busy_effect_mae": error_stats(r["effect_error"] for r in links
                                                  if r["busy"] and r["effect_error"] is not None)["mae"],
                   "status_mismatches": sum(r["status_mismatches"] for r in scored),
                   "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
                   "same_random_demand": all(r.get("same_random_demand", True) for r in scored)}
            (by_preset if kind is None else by_type).append(row)
    return by_type, by_preset


def link_table(part: PartA, presets: list[str], base: Topology) -> list[dict]:
    """Error per link over every instance of every type, per preset."""
    rows = []
    for preset in presets:
        by_link: dict[int, list] = defaultdict(list)
        for r in part.link_rows:
            if r["preset"] == preset:
                by_link[r["link_id"]].append(r)
        for link_id, items in sorted(by_link.items()):
            lk = base.links[link_id - 1]
            all_e = error_stats(r["error"] for r in items if r["error"] is not None)
            busy_e = error_stats(r["error"] for r in items if r["busy"])
            rows.append({"preset": preset, "link_id": link_id, "link": items[0]["link"],
                         "capacity_mbps": lk.capacity_mbps, "instances": len(items), "link_samples": all_e["n"],
                         "mae": all_e["mae"], "p95": all_e["p95"], "max": all_e["max"],
                         "busy_samples": busy_e["n"], "busy_mae": busy_e["mae"],
                         "mean_measured_pct": float(np.mean([r["measured_pct"] for r in items])),
                         "status_mismatches": sum(r["predicted_up"] != r["measured_up"] for r in items)})
    return rows


# ------------------------------------------------------------------ part B
@dataclass
class PartB:
    cases: list
    triggers: list
    recommendations: list
    checks: list
    config: dict
    seconds: float = 0.0


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django
    django.setup()


def switch_off_flash_crowds(net: EmulatedNetwork) -> dict:
    """Random flash crowds off from now on. The lab's switch (POST /lab/faults {"random_surges": false})
    only stops new days from being drawn: the emulator draws a whole day's flash crowds when the day
    is first seen, so the current day's would still start later. Those that have not started yet are
    removed as well (as E3 does); one already in progress runs to its end. Lab surges are injected only
    into forks, so every surge in the monitored world is a random flash crowd."""
    def listed(surges):
        return [{"zone": s.zone, "cls": s.cls, "multiplier": round(s.multiplier, 3),
                 "start": s.start.astimezone(WAT).isoformat(timespec="minutes"),
                 "end": s.end.astimezone(WAT).isoformat(timespec="minutes")} for s in surges]

    net.traffic.random_surges_enabled = False
    later = [s for s in net.traffic.surges if s.start > net.t]
    net.traffic.surges = [s for s in net.traffic.surges if s.start <= net.t]
    return {"switched_off_at": net.t.astimezone(WAT).isoformat(timespec="minutes"),
            "removed_not_started": listed(later), "in_progress": listed(net.traffic.surges)}


def buffer_append(service, clean) -> None:
    """Add one cycle to the history buffer exactly as ForecastService.on_cycle does (no forecast)."""
    util = {link_id: r.utilisation_pct for link_id, r in clean.links.items()}
    errors = {link_id: (float(r.error_count) if r.error_count is not None else None) for link_id, r in clean.links.items()}
    service.buffer.append(clean.timestamp, util, errors)


def test_trigger(case: Case, basis: str, link_id: int, predicted, horizon, world: EmulatedNetwork, ctwin: Twin,
                 lab_log: LabLog, out: PartB, critical: float) -> None:
    model = ctwin.model
    label = f"forecast +{horizon} min" if predicted else "current"
    trigger_id = f"{case.id}/{basis}/{link_id}"
    now = model.link(link_id)["utilisation_pct"]
    snapshot = model.copy()                     # as the engine: the network as it was at the trigger
    live_before = digest(model_state(model))
    before = Fingerprint.take(world, snapshot)  # the model the recommendation engine is given
    began = time.perf_counter()
    with lab_log.simulation(), timed("recommend()"):
        recs = recommend(snapshot, link_id, predicted, basis=label)
    ms = round((time.perf_counter() - began) * 1000, 1)
    after = Fingerprint.take(world, snapshot)
    live_unchanged = digest(model_state(model)) == live_before
    out.checks.append({"part": "B", "instance": trigger_id, "check": "recommend",
                       "network_configuration_unchanged": before.network == after.network,
                       "twin_model_configuration_unchanged": before.model_config == after.model_config,
                       "twin_model_state_unchanged": before.model_state == after.model_state and live_unchanged,
                       "network_sha256": after.network})
    at = world.t
    no_action_branch = fork(world, f"{trigger_id} no action", lab_log)
    with timed(f"branch of {WINDOW_CYCLES} cycles, no twin"):
        no_action = np.array([emulator_cycle(no_action_branch)[0] for _ in range(WINDOW_CYCLES)])
    no_action_noise = no_action_branch.traffic.noise_state.copy()
    target = link_id - 1
    out.triggers.append({
        "trigger": trigger_id, "case": case.id, "basis": basis, "time_wat": f"{at.astimezone(WAT):%a %H:%M}",
        "link_id": link_id, "link": model.link_label(link_id), "twin_now_pct": now, "horizon_min": horizon,
        "forecast_pct": (predicted or {}).get(link_id), "recommendations": len(recs), "recommend_ms": ms,
        "no_action_peak_pct": float(no_action[:, target].max()),
        "no_action_congested": bool((no_action[:, target] >= critical).any())})
    for rank, rec in enumerate(recs, start=1):
        row = {"trigger": trigger_id, "case": case.id, "basis": basis, "link": model.link_label(link_id),
               "rank": rank, "action": rec.scenario_type, "kind": rec.kind, "title": rec.title,
               "twin_parameters": json.dumps(rec.outcome.parameters),
               "predicted_target_pct": round(rec.target_after_pct, 2), "predicted_max_after": rec.outcome.max_after["pct"]}
        try:
            change = to_lab(rec.scenario_type, rec.outcome.parameters, snapshot)
        except NotTestable as exc:
            row.update(outcome="not_testable", note=str(exc))
            out.recommendations.append(row)
            continue
        branch = fork(world, f"{trigger_id} action {rank}", lab_log)
        branch.apply_change(change)
        with timed(f"branch of {WINDOW_CYCLES} cycles, no twin"):
            action = np.array([emulator_cycle(branch)[0] for _ in range(WINDOW_CYCLES)])
        verdict = judge(no_action, action, target, critical)
        new = verdict.pop("new_bottleneck_columns")
        row.update(lab_change=json.dumps(change), **verdict,
                   new_bottlenecks=json.dumps([model.link_label(j + 1) for j in new]),
                   same_random_demand=bool(np.array_equal(branch.traffic.noise_state, no_action_noise)))
        out.recommendations.append(row)


def run_case(case: Case, net: EmulatedNetwork, twin: Twin, service, lab_log: LabLog, out: PartB,
             critical: float) -> None:
    cycles = RAMP_MINUTES + HOLD_MINUTES
    tries, chosen = [], None
    for multiplier in LADDER:
        probe = fork(net, f"{case.id} probe x{multiplier:g}", lab_log)
        probe.add_surge(case.zone, case.cls, multiplier, RAMP_MINUTES, HOLD_MINUTES, 0.0)
        peaks = np.zeros(len(net.links))
        for _ in range(cycles):                  # stops early once a link reaches the probe level
            with timed("emulator cycle, no twin (probes and branches)"):
                peaks = np.maximum(peaks, emulator_cycle(probe)[0])
            if peaks.max() >= PROBE_PEAK_PCT:
                break
        j = int(np.argmax(peaks))
        tries.append({"multiplier": multiplier, "peak_pct": float(peaks[j]), "peak_link": twin.model.link_label(j + 1)})
        if peaks[j] >= PROBE_PEAK_PCT:
            chosen = multiplier
            break
    row = {"case": case.id, "time_wat": f"{case.time:%a %d %b %H:%M}", "zone": case.zone, "traffic_class": case.cls,
           "ramp_min": RAMP_MINUTES, "hold_min": HOLD_MINUTES, "multiplier": chosen,
           "probe_peak_pct": tries[-1]["peak_pct"], "probe_peak_link": tries[-1]["peak_link"],
           "probes": json.dumps(tries)}
    if chosen is None:
        row["note"] = "no multiplier on the ladder congests a link: case not run"
        out.cases.append(row)
        return
    world = fork(net, f"{case.id} case world", lab_log)
    ctwin, cservice = fork_twin(twin, world), fork_service(service)
    world.add_surge(case.zone, case.cls, chosen, RAMP_MINUTES, HOLD_MINUTES, 0.0)
    done = {basis: set() for basis in BASES}
    alerts, served = 0, defaultdict(int)
    for _ in range(cycles):
        with timed("emulator cycle + twin ingest"):
            ctwin.step_cycle()
            clean = ctwin.ingest()
        if clean is None:
            continue
        with timed("forecasting cycle (ForecastService.on_cycle)"):
            rows, started, _ended = cservice.on_cycle(clean)
        if rows:
            served[rows[0].model_version] += 1
        alerts += len(started)
        for episode in sorted(started, key=lambda e: e.link_id):
            if episode.link_id in done["forecast"] or len(done["forecast"]) >= MAX_TRIGGERS:
                continue
            done["forecast"].add(episode.link_id)
            test_trigger(case, "forecast", episode.link_id, cservice.latest_forecast(episode.horizon_minutes),
                         episode.horizon_minutes, world, ctwin, lab_log, out, critical)
        for link_id, reading in sorted(clean.links.items()):
            value = reading.utilisation_pct
            if value is None or value < critical or link_id in done["current"] or len(done["current"]) >= MAX_TRIGGERS:
                continue
            done["current"].add(link_id)
            test_trigger(case, "current", link_id, None, None, world, ctwin, lab_log, out, critical)
    row.update(alert_episodes_started=alerts, forecast_triggers=len(done["forecast"]),
               current_triggers=len(done["current"]), model_cycles=json.dumps(dict(served)))
    out.cases.append(row)
    ctwin.close()


def run_part_b(base: Topology, quick: bool, n_cases: int, lab_log: LabLog) -> PartB:
    with timed("Django set-up"):
        setup_django()
    from django.conf import settings

    from digital_twin.runtime import forecasting

    cfg = settings.TWIN
    critical = float(cfg["CRITICAL_THRESHOLD_PCT"])
    cycle = int(cfg["CYCLE_SECONDS"])
    if cycle != CYCLE_SECONDS:
        raise SystemExit(f"E4 assumes {CYCLE_SECONDS}-second cycles; the settings say {cycle}")
    cases = CASES[:n_cases]
    topo = world_topology(base, "default", FLASH_SEED_B)
    start = QUICK_REC_WORLD_START if quick else REC_WORLD_START
    predict_from = cases[0].time - timedelta(minutes=FORECAST_LEAD_MINUTES)
    net = EmulatedNetwork(topo, start, cycle_seconds=cycle, seed=SEED_B, history_cycles=HISTORY_CYCLES)
    net.random_faults = False
    lab_log.labels[id(net)] = "part B monitored world"
    twin = Twin(topo, net, cycle_seconds=cycle)
    out = PartB([], [], [], [], {})
    began = time.perf_counter()
    with mock.patch.object(forecasting.persistence, "write_predictions", lambda rows: None):
        with timed("loading the forecasting models"):
            service = forecasting.ForecastService(twin.model, cycle_seconds=cycle, critical_pct=critical,
                                                  warning_probability=cfg["WARNING_PROBABILITY"],
                                                  model_dir=str(cfg["MODEL_DIR"]))
        out.config = {"models": {kind: m.version for kind, m in service.predictor.models.items()},
                      "world_start": start.isoformat(), "flash_crowds_off_from": predict_from.isoformat(),
                      "forecasting_minutes_before_each_case": FORECAST_LEAD_MINUTES,
                      "critical_pct": critical, "warning_probability_setting": cfg["WARNING_PROBABILITY"],
                      "clear_below_pct": service.tracker.clear_below_pct, "clear_cycles": service.tracker.clear_cycles}
        if not service.predictor.models:
            raise SystemExit("no trained models in the registry (var/models/active.json)")
        log(f"part B: world from {start:%a %d %b %H:%M} WAT, first case {cases[0].time:%a %H:%M}, "
            f"{len(cases)} case(s)")
        served: dict = defaultdict(int)
        pending = list(cases)
        while pending:
            if net.t >= pending[0].time:
                case = pending.pop(0)
                t0 = time.perf_counter()
                run_case(case, net, twin, service, lab_log, out, critical)
                log(f"part B case {case.id} {case.time:%H:%M} {case.zone} {case.cls}: {time.perf_counter() - t0:.1f} s")
                continue
            with timed("emulator cycle + twin ingest"):
                twin.step_cycle()
                clean = twin.ingest()
            if clean is None:
                continue
            if net.t > predict_from and net.traffic.random_surges_enabled:
                out.config["flash_crowds_switched_off"] = switch_off_flash_crowds(net)
            if net.t > pending[0].time - timedelta(minutes=FORECAST_LEAD_MINUTES):
                with timed("forecasting cycle (ForecastService.on_cycle)"):
                    rows, _started, _ended = service.on_cycle(clean)
                if rows:
                    served[rows[0].model_version] += 1
            else:
                buffer_append(service, clean)
        out.config["model_cycles_served_main_world"] = dict(served)
    twin.close()
    out.seconds = time.perf_counter() - began
    return out


def recommendation_tables(part: PartB) -> list[dict]:
    rows = []
    for basis in BASES:
        for action in ACTIONS:
            recs = [r for r in part.recommendations if r["basis"] == basis and r["action"] == action]
            outcomes = _count(r["outcome"] for r in recs)
            scorable = sum(v for k, v in outcomes.items() if k in ("success", "still_congested", "new_bottleneck"))
            relieved = outcomes.get("success", 0) + outcomes.get("new_bottleneck", 0)
            rows.append({"basis": basis, "action": action, "kind": "planning" if action == "capacity_change" else "immediate",
                         "recommended": len(recs), "not_testable": outcomes.get("not_testable", 0),
                         "not_scorable": outcomes.get("not_scorable", 0), "scorable": scorable,
                         "success": outcomes.get("success", 0), "still_congested": outcomes.get("still_congested", 0),
                         "new_bottleneck": outcomes.get("new_bottleneck", 0),
                         "success_rate": outcomes.get("success", 0) / scorable if scorable else None,
                         "target_relieved": relieved, "target_relieved_rate": relieved / scorable if scorable else None})
    return rows


# ------------------------------------------------------------------ charts
def against(value: float, digits: int, higher_is_better: bool) -> float:
    """Rounded for a label, never in the system's favour: down if higher is better, up if lower is."""
    scale = 10 ** digits
    shifted = value * scale
    return (math.floor(shifted + 1e-9) if higher_is_better else math.ceil(shifted - 1e-9)) / scale


def _bar_labels(axes, xs, values, digits: int = 2, higher_is_better: bool = False) -> None:
    top = axes.get_ylim()[1]
    for x, v in zip(xs, values, strict=True):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        text = f"{against(v, digits, higher_is_better):.{digits}f}"
        axes.text(x, v + top * 0.012, text, ha="center", va="bottom", fontsize=7, color=INK_2)


def chart_error_by_type(results: Results, rows: list[dict], preset: str) -> list[dict]:
    data = [r for r in rows if r["preset"] == preset]
    table = [{"scenario_type": r["scenario_type"], "preset": preset, "busy_samples": r["busy_samples"],
              "busy_mae_pts": r["busy_mae"], "busy_p95_pts": r["busy_p95"], "busy_max_pts": r["busy_max"],
              "all_links_mae_pts": r["mae"], "all_links_p95_pts": r["p95"],
              "busy_no_change_mae_pts": r["busy_no_change_mae"], "busy_effect_mae_pts": r["busy_effect_mae"]}
             for r in data]
    results.write_csv("error_by_type.csv", table)
    figure, axes = chart(7.5, 3.4)
    x = np.arange(len(table))
    mae = [np.nan if t["busy_mae_pts"] is None else t["busy_mae_pts"] for t in table]
    p95 = [np.nan if t["busy_p95_pts"] is None else t["busy_p95_pts"] for t in table]
    axes.bar(x - 0.2, mae, 0.38, color=SERIES[0], label="Mean absolute error")
    axes.bar(x + 0.2, p95, 0.38, color=SERIES[1], label="95th percentile")
    axes.set_ylim(0, max(1.0, np.nanmax([*mae, *p95, 0.0]) * 1.18))
    _bar_labels(axes, x - 0.2, mae)
    _bar_labels(axes, x + 0.2, p95)
    axes.set_xticks(x, [TYPE_LABEL[t["scenario_type"]] for t in table], fontsize=8)
    axes.set_ylabel("Error on busy links (percentage points)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e4_error_by_type.png")
    return table


def chart_bottlenecks(results: Results, rows: list[dict], preset: str) -> list[dict]:
    data = [r for r in rows if r["preset"] == preset]
    table = [{"scenario_type": r["scenario_type"], "preset": preset, "true_positives": r["tp"],
              "false_positives": r["fp"], "false_negatives": r["fn"],
              "precision_pct": None if r["precision"] is None else 100 * r["precision"],
              "recall_pct": None if r["recall"] is None else 100 * r["recall"]} for r in data]
    results.write_csv("bottleneck_by_type.csv", table)
    figure, axes = chart(7.5, 3.6)
    x = np.arange(len(table))
    precision = [np.nan if t["precision_pct"] is None else t["precision_pct"] for t in table]
    recall = [np.nan if t["recall_pct"] is None else t["recall_pct"] for t in table]
    axes.bar(x - 0.2, precision, 0.38, color=SERIES[0], label="Precision")
    axes.bar(x + 0.2, recall, 0.38, color=SERIES[1], label="Recall")
    axes.set_ylim(0, 118)
    axes.set_yticks([0, 20, 40, 60, 80, 100])
    _bar_labels(axes, x - 0.2, precision, 0, higher_is_better=True)
    _bar_labels(axes, x + 0.2, recall, 0, higher_is_better=True)
    for xi, (p, r) in enumerate(zip(precision, recall, strict=True)):
        if np.isnan(p) and np.isnan(r):
            axes.text(xi, 3, "none\npredicted\nor measured", ha="center", va="bottom", fontsize=6.5, color=MUTED)
    axes.set_xlim(-0.6, len(table) - 0.4)
    labels = [f"{TYPE_LABEL[t['scenario_type']]}\n{t['true_positives']} / {t['false_positives']} / {t['false_negatives']}"
              for t in table]
    axes.set_xticks(x, labels, fontsize=8)
    axes.set_xlabel("Scenario type, with true positives / false positives / false negatives (links at 90 % or more)",
                    fontsize=8)
    axes.set_ylabel("Bottleneck set (%)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e4_bottleneck_pr_by_type.png")
    return table


def chart_by_preset(results: Results, rows: list[dict]) -> list[dict]:
    table = [{"preset": r["preset"], "instances_scored": r["scored"], "busy_samples": r["busy_samples"],
              "busy_mae_pts": r["busy_mae"], "busy_p95_pts": r["busy_p95"], "busy_max_pts": r["busy_max"],
              "all_links_mae_pts": r["mae"], "all_links_p95_pts": r["p95"], "busy_effect_mae_pts": r["busy_effect_mae"],
              "busy_no_change_mae_pts": r["busy_no_change_mae"], "precision": r["precision"], "recall": r["recall"]}
             for r in rows]
    results.write_csv("error_by_preset.csv", table)
    figure, axes = chart(5.2, 3.2)
    x = np.arange(len(table))
    mae = [np.nan if t["busy_mae_pts"] is None else t["busy_mae_pts"] for t in table]
    p95 = [np.nan if t["busy_p95_pts"] is None else t["busy_p95_pts"] for t in table]
    axes.bar(x - 0.2, mae, 0.38, color=SERIES[0], label="Mean absolute error")
    axes.bar(x + 0.2, p95, 0.38, color=SERIES[1], label="95th percentile")
    axes.set_ylim(0, max(1.0, np.nanmax([*mae, *p95, 0.0]) * 1.18))
    _bar_labels(axes, x - 0.2, mae)
    _bar_labels(axes, x + 0.2, p95)
    axes.set_xticks(x, [{"off": "Off", "default": "Default", "high": "High"}[t["preset"]] for t in table])
    axes.set_xlabel("Reality-gap preset")
    axes.set_ylabel("Error on busy links (percentage points)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e4_error_by_preset.png")
    return table


def chart_recommendations(results: Results, rows: list[dict]) -> None:
    results.write_csv("recommendation_success.csv", rows)
    figure, axes = chart(7.0, 3.4)
    x = np.arange(len(ACTIONS))
    axes.set_ylim(0, 118)
    axes.set_yticks([0, 20, 40, 60, 80, 100])
    for j, basis in enumerate(BASES):
        offset = -0.2 if j == 0 else 0.2
        data = {r["action"]: r for r in rows if r["basis"] == basis}
        values = [np.nan if data[a]["success_rate"] is None else 100 * data[a]["success_rate"] for a in ACTIONS]
        axes.bar(x + offset, values, 0.38, color=SERIES[j], label=BASIS_LABEL[basis])
        for xi, a in enumerate(ACTIONS):
            r = data[a]
            text = f"{r['success']}/{r['scorable']}" if r["scorable"] else ("none\nscorable" if r["recommended"] else "none")
            y = (values[xi] if not np.isnan(values[xi]) else 0) + 1.5
            axes.text(xi + offset, y, text, ha="center", va="bottom", fontsize=7, color=INK_2 if r["scorable"] else MUTED)
    axes.set_xlim(-0.6, len(ACTIONS) - 0.4)
    axes.set_xticks(x, [ACTION_LABEL[a] for a in ACTIONS], fontsize=8)
    axes.set_xlabel("Recommended action (bar labels: successes / scorable recommendations)", fontsize=8)
    axes.set_ylabel("Success rate (%)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e4_recommendation_success.png")


# ------------------------------------------------------------------ static check
def import_contracts() -> dict:
    exe = BACKEND / ".venv" / "Scripts" / "lint-imports.exe"
    if not exe.exists():
        exe = BACKEND / ".venv" / "bin" / "lint-imports"
    try:
        run = subprocess.run([str(exe)], cwd=BACKEND, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": False, "error": str(exc)}
    tail = [line for line in run.stdout.splitlines() if "Contracts:" in line]
    return {"ran": True, "passed": run.returncode == 0, "result": tail[-1].strip() if tail else run.stdout[-200:]}


# ------------------------------------------------------------------ main
def _r(value, digits: int = 3):
    if isinstance(value, dict):
        return {k: _r(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_r(v, digits) for v in value]
    if isinstance(value, float | np.floating):
        return None if np.isnan(value) else round(float(value), digits)
    return value


def run(args) -> None:
    quick = args.quick
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    if any(p not in PRESETS for p in presets):
        raise SystemExit(f"unknown preset in {presets}; use {PRESETS}")
    n_moments = args.moments or (QUICK_MOMENTS if quick else len(MOMENTS))
    n_cases = args.cases or (QUICK_CASES if quick else len(CASES))
    moments = MOMENTS[:n_moments]
    base = load_topology(CAMPUS)
    config = {
        "quick": quick, "presets": presets, "moments": [m.isoformat() for m in moments],
        "scenario_types": list(TYPES), "not_testable_types": NOT_TESTABLE_TYPES,
        "instances_per_type_per_preset": n_moments, "warmup_cycles": WARMUP_CYCLES, "settle_cycles": SETTLE_CYCLES,
        "cycle_seconds": CYCLE_SECONDS, "busy_pct": BUSY_PCT, "critical_pct": CRITICAL_PCT,
        "seed_part_a": f"{SEED_A} + moment index", "flash_crowd_seed_part_a": f"{FLASH_SEED_A} + moment index",
        "random_faults": False, "data_quality_faults": "campus.yaml (on)", "topology": CAMPUS.relative_to(ROOT).as_posix(),
        "topology_sha256": hashlib.sha256(CAMPUS.read_bytes()).hexdigest(),
        "recommendations": not args.no_recommendations,
        "cases": [{"case": c.id, "time": c.time.isoformat(), "zone": c.zone, "cls": c.cls} for c in CASES[:n_cases]],
        "seed_part_b": SEED_B, "flash_crowd_seed_part_b": FLASH_SEED_B, "ramp_min": RAMP_MINUTES,
        "hold_min": HOLD_MINUTES, "ladder": list(LADDER), "probe_peak_pct": PROBE_PEAK_PCT,
        "window_cycles": WINDOW_CYCLES, "max_triggers_per_basis_and_case": MAX_TRIGGERS,
        "success_rule": "success: the no-action branch has the target link at 90 % or more in some cycle of the "
                        "window and the action branch never does, and the action adds no other link at 90 % or "
                        "more; target_relieved counts the target link only (success + new_bottleneck)",
        "code_version": git_commit(),
    }
    deviation = {
        "counter_only_demand_estimate": "not run: the twin as built has no counter-only (gravity) estimate; it "
                                        "belongs to the SNMP adapter, a Should item that was not built (D11)",
        "add_link": "not tested: a Could scenario type with no lab equivalent in the emulator",
    }
    if n_moments < 10:
        deviation["instances"] = f"{n_moments} instance(s) per scenario type and preset (plan: at least 10)"
    if presets != list(PRESETS):
        deviation["presets"] = f"only {', '.join(presets)} (plan: off, default and high)"
    if quick:
        deviation["quick"] = "pipeline check only: not for Chapter 4"
    config["deviation_from_plan"] = deviation
    results = Results("E4", "Safe, accurate change testing and recommendations (G3, UC3)", config)
    for stale in results.folder.glob("*"):
        if stale.suffix in (".csv", ".png", ".json"):
            stale.unlink()

    lab_log = LabLog()
    lab_log.install()
    try:
        log(f"part A: {len(moments)} moments x {len(TYPES)} scenario types x {len(presets)} presets")
        part_a = run_part_a(base, presets, moments, lab_log, CRITICAL_PCT)
        part_b = None
        if not args.no_recommendations:
            part_b = run_part_b(base, quick, n_cases, lab_log)
    finally:
        lab_log.uninstall()
    contracts = import_contracts()

    # ---- part A outputs
    by_type, by_preset = accuracy_tables(part_a, presets)
    link_fields = ["preset", "moment", "scenario_type", "link_id", "link", "capacity_mbps", "observed_now_pct",
                   "before_pct", "after_pct", "predicted_pct", "predicted_up", "measured_pct", "measured_up",
                   "base_pct", "base_up", "error", "busy", "no_change_error", "effect_error"]
    results.write_csv("link_errors.csv", part_a.link_rows, link_fields)
    instance_fields = ["preset", "moment", "time_wat", "scenario_type", "instance", "status", "note", "spec",
                       "twin_parameters", "lab_change", "calibration_factor", "simulation_ms", "links_scored",
                       "status_mismatches", "mae", "busy_mae", "max_error", "predicted_bottlenecks",
                       "measured_bottlenecks", "tp", "fp", "fn", "same_random_demand"]
    results.write_csv("instances.csv", part_a.instance_rows, instance_fields)
    results.write_csv("accuracy_by_type.csv", by_type + by_preset)
    by_link = link_table(part_a, presets, base)
    results.write_csv("error_by_link.csv", by_link)
    chart_preset = "default" if "default" in presets else presets[0]
    chart_error_by_type(results, by_type, chart_preset)
    chart_bottlenecks(results, by_type, chart_preset)
    chart_by_preset(results, by_preset)

    # ---- part B outputs
    checks = part_a.checks + (part_b.checks if part_b else [])
    results.write_csv("unchanged_checks.csv", checks)
    results.write_csv("lab_calls.csv", lab_log.calls,
                      ["n", "method", "world", "caller", "from_twin_code", "during_twin_simulation", "detail"])
    rec_rows: list[dict] = []
    if part_b:
        results.write_csv("cases.csv", part_b.cases, ["case", "time_wat", "zone", "traffic_class", "ramp_min",
                                                      "hold_min", "multiplier", "probe_peak_pct", "probe_peak_link",
                                                      "alert_episodes_started", "forecast_triggers", "current_triggers",
                                                      "model_cycles", "note", "probes"])
        results.write_csv("triggers.csv", part_b.triggers)
        results.write_csv("recommendations.csv", part_b.recommendations,
                          ["trigger", "case", "basis", "link", "rank", "action", "kind", "title", "twin_parameters",
                           "lab_change", "predicted_target_pct", "predicted_max_after", "outcome",
                           "no_action_peak_pct", "action_peak_pct", "no_action_onset_cycle", "new_bottlenecks",
                           "same_random_demand", "note"])
        rec_rows = recommendation_tables(part_b)
        chart_recommendations(results, rec_rows)
        config["part_b"] = part_b.config

    # ---- summary
    def flag(key):
        values = [c[key] for c in checks if c[key] is not None]
        return {"checked": len(values), "all_unchanged": all(values), "changed": sum(not v for v in values)}

    unchanged = {"network_configuration": flag("network_configuration_unchanged"),
                 "twin_model_configuration": flag("twin_model_configuration_unchanged"),
                 "twin_model_state": flag("twin_model_state_unchanged")}
    calls = lab_log.summary()
    target_met = all(u["all_unchanged"] for u in unchanged.values()) and not calls["from_twin_code"] \
        and not calls["during_twin_simulation"]
    keep = ("scored", "busy_samples", "busy_mae", "busy_p95", "busy_max", "mae", "p95", "max", "busy_no_change_mae",
            "busy_effect_mae", "status_mismatches", "tp", "fp", "fn", "precision", "recall")
    summary = {
        "target": "configuration always unchanged (plan section 11)",
        "target_met": target_met,
        "unchanged_checks": unchanged,
        "lab_calls": calls,
        "import_contracts": contracts,
        "accuracy_by_preset": {r["preset"]: {k: r[k] for k in keep} for r in by_preset},
        f"accuracy_by_type_{chart_preset}": {r["scenario_type"]: {k: r[k] for k in keep}
                                             for r in by_type if r["preset"] == chart_preset},
        f"worst_links_{chart_preset}": [
            {k: r[k] for k in ("link", "busy_samples", "busy_mae", "max")}
            for r in sorted((r for r in by_link if r["preset"] == chart_preset and r["busy_mae"] is not None),
                            key=lambda r: -r["busy_mae"])[:5]],
        "same_random_demand_in_every_pair": all(r["same_random_demand"] for r in by_preset),
        "instances_not_scored": [{"instance": r["instance"], "status": r["status"], "note": r.get("note")}
                                 for r in part_a.instance_rows if r["status"] != "scored"],
        "not_testable_scenario_types": NOT_TESTABLE_TYPES,
        "counter_only_demand_estimate": {
            "run": False,
            "reason": "not supported by the twin as built: its demand matrix comes only from flow records (D11); "
                      "the counter-only (gravity) estimate belongs to the SNMP adapter, a Should item that was not "
                      "built. Without flow records every simulation would route an empty demand matrix."},
        "seconds_part_a": round(part_a.seconds, 1),
    }
    if part_b:
        immediate = [r for r in rec_rows if r["kind"] == "immediate"]
        planning = [r for r in rec_rows if r["kind"] == "planning"]

        def pooled(items):
            scorable = sum(r["scorable"] for r in items)
            success = sum(r["success"] for r in items)
            relieved = sum(r["target_relieved"] for r in items)
            return {"recommended": sum(r["recommended"] for r in items), "scorable": scorable, "success": success,
                    "success_rate": success / scorable if scorable else None,
                    "target_relieved": relieved, "target_relieved_rate": relieved / scorable if scorable else None,
                    "not_scorable": sum(r["not_scorable"] for r in items),
                    "not_testable": sum(r["not_testable"] for r in items)}

        summary["recommendations"] = {
            "cases": len(part_b.cases), "cases_run": sum(1 for c in part_b.cases if c.get("multiplier")),
            "triggers": {b: sum(1 for t in part_b.triggers if t["basis"] == b) for b in BASES},
            "triggers_without_recommendation": sum(1 for t in part_b.triggers if not t["recommendations"]),
            "immediate_fixes": {b: pooled([r for r in immediate if r["basis"] == b]) for b in BASES},
            "planning_advice_capacity_upgrade": {b: pooled([r for r in planning if r["basis"] == b]) for b in BASES},
            "by_action": {f"{r['basis']}/{r['action']}": {k: r[k] for k in ("recommended", "scorable", "success",
                                                                            "success_rate", "target_relieved",
                                                                            "not_scorable", "still_congested",
                                                                            "new_bottleneck")}
                          for r in rec_rows},
            "same_random_demand_in_every_pair": all(r.get("same_random_demand", True) for r in part_b.recommendations),
            "actions_not_testable": sorted({r["action"] for r in part_b.recommendations if r["outcome"] == "not_testable"}),
            "models": part_b.config.get("models"),
        }
        summary["seconds_part_b"] = round(part_b.seconds, 1)
    summary["timings"] = timing_summary()
    results.summary = _r(summary)
    path = results.finish()
    log(f"done: {path}")
    log(f"target met (configuration always unchanged, no lab call from the twin): {target_met}")
    for r in by_preset:
        log(f"  {r['preset']:>7}: busy-link MAE {_fmt(r['busy_mae'])} pts, p95 {_fmt(r['busy_p95'])}, "
            f"max {_fmt(r['busy_max'])}; bottleneck precision {_fmt(r['precision'])}, recall {_fmt(r['recall'])}")
    if part_b:
        for b in BASES:
            p = summary["recommendations"]["immediate_fixes"][b]
            log(f"  recommendations ({b}): {p['success']}/{p['scorable']} immediate fixes succeeded, "
                f"{p['not_scorable']} not scorable")


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


# ------------------------------------------------------------------ self-test
def _selftest() -> None:
    from .twin import model_for

    # scoring
    s = error_stats([0.0, 1.0, 2.0, np.nan, 3.0])
    assert s["n"] == 4 and abs(s["mae"] - 1.5) < 1e-12 and s["max"] == 3.0
    assert error_stats([])["mae"] is None
    assert set_counts({1, 2}, {2, 3}) == (1, 1, 1)
    assert precision_recall(1, 1, 1) == (0.5, 0.5)
    assert precision_recall(0, 0, 2) == (None, 0.0) and precision_recall(0, 0, 0) == (None, None)
    no_action = np.array([[80.0, 10.0, 50.0], [92.0, 10.0, 60.0], [95.0, 10.0, 70.0]])
    assert judge(no_action, np.array([[70.0, 10, 50], [75, 10, 60], [80, 10, 70]]), 0)["outcome"] == "success"
    assert judge(no_action, np.array([[70.0, 10, 50], [91, 10, 60], [80, 10, 70]]), 0)["outcome"] == "still_congested"
    verdict = judge(no_action, np.array([[70.0, 10, 50], [75, 10, 95], [80, 10, 70]]), 0)
    assert verdict["outcome"] == "new_bottleneck" and verdict["new_bottleneck_columns"] == [2]
    assert verdict["no_action_onset_cycle"] == 2
    assert judge(no_action * 0.5, no_action * 0.4, 0)["outcome"] == "not_scorable"
    assert against(0.871, 2, False) == 0.88 and against(0.87, 2, False) == 0.87
    assert against(99.6, 0, True) == 99.0 and against(100.0, 0, True) == 100.0
    # a real bottleneck on a link the twin wrongly predicts down is a miss, not left out
    fake = SimpleNamespace(links=[
        SimpleNamespace(link_id=1, label="a", capacity_mbps=100.0, observed_pct=50.0, before_pct=50.0,
                        after_pct=95.0, status_after="up"),
        SimpleNamespace(link_id=2, label="b", capacity_mbps=100.0, observed_pct=50.0, before_pct=50.0,
                        after_pct=0.0, status_after="down")])
    measured, up = np.array([92.0, 95.0]), np.array([True, True])
    _, scored = score_links(fake, measured, up, measured, up, CRITICAL_PCT)
    assert (scored["tp"], scored["fp"], scored["fn"], scored["status_mismatches"]) == (1, 0, 1, 1), scored

    # every pre-registered instance names real elements and maps to a valid twin change and a lab change
    base = load_topology(CAMPUS)
    topo = with_reality_gap(base, "default")
    start = datetime(2026, 11, 2, 10, 0, tzinfo=WAT)
    net = EmulatedNetwork(topo, start, seed=1, history_cycles=5)
    net.random_faults = False
    twin = Twin(topo, net)
    model = model_for(topo, twin.index)
    model.known_classes = set(topo.classes) | {f.cls for f in topo.system_flows}
    twin.model = model
    for kind in TYPES:
        assert len(SCENARIOS[kind]) >= len(MOMENTS), kind
        for spec in SCENARIOS[kind]:
            params = REGISTRY[kind].validate(twin_params(kind, spec, twin), model)
            change = to_lab(kind, params, model)
            probe = copy.deepcopy(net)
            probe.apply_change(change)          # raises if a name is wrong
    try:
        to_lab("add_link", {}, model)
        raise AssertionError("add_link should not be testable")
    except NotTestable:
        pass
    try:
        to_lab("qos_policy", {"cls": "video", "limit_mbps": 5.0, "source_zone": "HOSTEL"}, model)
        raise AssertionError("a zone-filtered QoS policy has no lab equivalent")
    except NotTestable:
        pass
    reroute = REGISTRY["reroute_traffic"].validate(twin_params("reroute_traffic", SCENARIOS["reroute_traffic"][0], twin), model)
    path = to_lab("reroute_traffic", reroute, model)["path"]
    assert path[0] == "ACC-SCI-01" and path[-1] == LAB_INTERNET and "ISP-A-GW" not in path, path

    # forks: identical demand and truth without a change; the configuration hash sees changes, not traffic
    lab_log = LabLog()
    lab_log.install()
    try:
        a, b = fork(net, "a", lab_log), fork(net, "b", lab_log)
        before = digest(network_configuration(a))
        ua, ub = emulator_cycle(a)[0], emulator_cycle(b)[0]
        assert np.array_equal(ua, ub) and np.array_equal(a.traffic.noise_state, b.traffic.noise_state)
        assert digest(network_configuration(a)) == before, "traffic must not change the configuration hash"
        a.apply_change({"type": "capacity_change", "link": list(ISP_B), "capacity_mbps": 300})
        assert digest(network_configuration(a)) != digest(network_configuration(b))
        assert digest(network_configuration(net)) == before, "a fork's change reached the original"
        with lab_log.simulation():
            b.apply_change({"type": "link_failure", "link": list(ISP_A)})
        summary = lab_log.summary()
        # the harness's change to a; during the "simulation" the change to b and the emulator's own
        # fail_link inside it (internal calls are logged only while a simulation runs)
        assert summary["calls"] == 3 and summary["during_twin_simulation"] == 2 and summary["from_twin_code"] == 0
        assert lab_log.calls[0]["world"] == "a" and lab_log.calls[0]["caller"] == "evaluation.e4_sim_vs_reality"
        assert lab_log.calls[2]["method"] == "fail_link" and lab_log.calls[2]["caller"] == "netemu.network"
    finally:
        lab_log.uninstall()
    assert not hasattr(EmulatedNetwork.apply_change, "__wrapped__"), "the lab-call wrappers were not removed"

    # switching flash crowds off also removes the day's crowds that have not started yet
    crowd = EmulatedNetwork(topo, start, seed=1, history_cycles=5)
    crowd.step()                                # draws the day's flash crowds
    planned = len(crowd.traffic.surges)
    off = switch_off_flash_crowds(crowd)
    assert planned >= 1 and not crowd.traffic.random_surges_enabled
    assert all(s.start <= crowd.t for s in crowd.traffic.surges)
    assert len(off["removed_not_started"]) + len(off["in_progress"]) == planned, off

    # the twin's live model is untouched by a simulation (fingerprints)
    twin2 = Twin(topo, net)
    twin2.advance(3)
    fp0 = Fingerprint.take(net, twin2.model)
    run_scenario(twin2.model, "link_failure", {"link_id": twin2.link_id(*ISP_A)})
    fp1 = Fingerprint.take(net, twin2.model)
    assert fp0 == fp1
    twin2.model.link(1)["cost"] = 99.0
    assert Fingerprint.take(net, twin2.model).model_config != fp0.model_config
    twin.close()
    twin2.close()
    print("E4 self-test passed")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--quick", action="store_true", help="2 moments and 1 recommendation case (pipeline check)")
    parser.add_argument("--selftest", action="store_true", help="unit-level checks of the scoring and the mapping")
    parser.add_argument("--presets", default=",".join(PRESETS), help="reality-gap presets (default: off,default,high)")
    parser.add_argument("--moments", type=int, default=0, help=f"part-A moments (default {len(MOMENTS)}, quick 2)")
    parser.add_argument("--cases", type=int, default=0, help=f"part-B surge cases (default {len(CASES)}, quick 1)")
    parser.add_argument("--no-recommendations", action="store_true", help="skip part B")
    args = parser.parse_args(argv)
    if args.selftest:
        _selftest()
        return
    run(args)


if __name__ == "__main__":
    main()
