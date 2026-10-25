"""E3 Early warning (Abstract, gap G2, UC2): are problems flagged before they reach critical levels?

PRE-REGISTERED. The protocol is docs/evaluation/E3_PROTOCOL.md. It holds:
- the plan's definitions (section 11);
- the injection rule;
- the target;
- the "Amendments before the full run", the refinements where the plan is silent, fixed before the full run.

Its SHA-256 (line endings normalised) is fixed in this module (PROTOCOL_SHA256) and checked at
start-up; the run refuses to start if the protocol was changed.

Each run then writes its registration, results/E3/REGISTRATION.md. It holds every surge size
tried and chosen, the seeds, the model versions and file hashes, the cancelled flash crowds and
the code hashes. Its SHA-256 goes into registration.json BEFORE the first prediction.

Both files are hashed again at the end; the run is valid only if neither changed.

What is measured
    Whether the twin's forecasting raises a warning on a link before that link becomes congested,
    how far ahead (lead time), how often it warns when nothing follows (false alarms), how well it
    predicts the time of the problem, and whether its confidence score means what it says
    (calibration). A linear-trend alarm is scored on exactly the same series for comparison.

The world
    A fresh emulated campus (data/topologies/campus.yaml, reality gap "default", random link and
    device failures and data-quality faults on, as in normal operation) with emulator seed 2026
    (the training history used seed 7). It starts 7 days before the experiment and runs a warm-up
    week of normal behaviour, including random flash crowds (drawn with seed 2026; training used
    seed 11). Every warm-up cycle passes through the twin's own ingest path (evaluation/twin.py:
    the production telemetry adapter, preprocessing and network model) into the history buffer,
    as live operation would have filled it (the engine reloads 7 days at start-up,
    runtime/forecasting.py HISTORY_DAYS). No forecast is made during the warm-up.
    The experiment starts on Monday 2 November 2026 at 00:00 WAT, after the training window (the
    models were trained on network time 14-28 October 2026), and runs for 78 hours, to Thursday
    5 November 06:00 WAT. At its start the random flash crowds are switched off. The lab switch
    (POST /lab/faults {"random_surges": false}) stops new days' flash crowds from being drawn, but
    the emulator draws a whole day's flash crowds when the day begins, and the last warm-up step
    already begins Monday. So the flash crowds drawn for that day that have not started yet are
    removed as well; one already in progress from the evening before runs to its end. The
    protocol lists both.

The injected surges
    Three ramp classes: slow (demand ramps up over 30 minutes), medium (15 min) and fast (5 min).
    Every surge holds its peak for 30 minutes and then ramps down at the same rate. Six surges per
    class, 18 in all, at six times of day (08:00, 11:00, 14:00, 17:00, 20:00 and 23:00 WAT, so 3
    hours apart) on Monday to Wednesday. The class rotates so that each class meets each time of
    day exactly once. Surges are placed at zones and traffic classes that never had a flash crowd
    in training (training's flash crowds were mostly hostel video, plus hostel web, School of
    Technology web, School of Science video, Engineering web and Library video): daytime surges
    use School of Technology video, School of Science web, Engineering video, ICT Centre web and
    video, Administration web and Library web. In the evening only the hostels carry enough traffic
    for a surge to congest a link, so the 20:00 and 23:00 surges are hostel e-learning and hostel
    portal traffic (never a flash-crowd class in training). Between 01:00 and 07:00 a design probe
    (emulator only, before any forecast) found that only hostel video, training's most common
    flash crowd, could congest a link with a multiplier on the ladder; every allowed zone and
    class would need more than x30. So no surge is placed then; those hours still count for false
    alarms.
    Surge size. Each surge multiplies the chosen zone's demand for the chosen class. The
    multiplier is chosen BEFORE the prediction run, by probing: at the surge's start, the world
    is forked (copy.deepcopy, so the fork has the same random demand and faults), the surge is
    added to the fork, and the fork runs for ramp + hold minutes. The multiplier is the smallest
    on the fixed ladder 1.5, 2, 3, 4, 6, 8, 12, 16, 24 for which some link reaches 95 % or more
    (ground truth, one-minute average) in the fork. If none does, the surge is recorded as not
    congesting, is not injected, and is kept out of the detection statistics (it is reported).
    The planning pass runs the whole experiment this way, one surge after the other, without any
    forecasting, and the protocol records every multiplier tried. The prediction run then replays
    the same world with the recorded multipliers. Because the emulator is deterministic, the run's
    ground truth must equal the planning pass's exactly; results.json reports this check.

Each cycle of the prediction run (one per minute of network time)
    Twin ingest (adapter -> preprocessing -> network model), then the engine's own ForecastService
    (runtime/forecasting.py) with only its database write removed: the cycle is appended to the
    7-day history buffer, the Predictor forecasts every link at 5, 10, 15 and 30 minutes with the
    ACTIVE models from var/models (same model choice: the full model once a day of history
    exists; same warning rule: the classification forest with the threshold chosen at training
    time; same confidence), and the AlertTracker forms alert episodes with the engine's
    hysteresis (an episode starts at the first warning on a link and ends after 5 consecutive
    cycles with every horizon and the current utilisation below 85 %). Ground truth for the cycle
    is read from the emulator.
    The linear-trend alarm uses the same buffer and the same feature function: the 15-cycle
    least-squares slope continued to each horizon (models.baseline_predictions "linear_trend"); it
    warns when the projection reaches 90 % at any horizon, and its own AlertTracker (same
    hysteresis) forms its episodes.

Definitions (plan section 11, with the protocol's amendments)
    onset          the first of two consecutive ground-truth cycles at or above 90 % utilisation
                   on a link, after at least 5 consecutive cycles below 85 % on that link (so a
                   link must calm down before it can have a new onset). The onset time is the end
                   of that cycle, the moment the twin's reading of it exists. The detector's state
                   at the experiment start comes from the last 60 warm-up cycles.
    detected       the method warned on that link (any horizon) at a cycle 1 to 35 minutes before
                   the onset.
    lead time      onset time minus the first warning of the alert episode that covers the onset
                   (the episode containing the last warning in the 1-35 minute window). It can
                   exceed 35 minutes when that episode started earlier; such cases are flagged.
    false alarm    an alert episode with no onset on that link within 35 minutes after the
                   episode's start (onset time from the start to the start + 35 min). This, the
                   plan's definition, is the headline figure.
                   Amendment 2: an episode that starts while its link is still congested (after
                   an onset, before the link has re-armed) is also shown separately as a "late
                   alarm", and false alarms without the late ones are given as context.
                   Amendment 4: episodes that start less than 36 minutes before the end of the
                   run cannot be scored and are reported as unscored.
    attribution    an onset belongs to an injected surge when its time lies between the surge's
                   start and start + ramp + hold + 10 minutes; every other onset is natural and
                   is reported separately (onsets during a flash crowd left over from the
                   warm-up, or in the window of a surge that was not injected, are natural).
                   Amendment 7: attribution is by time alone, so an onset in a surge's window
                   that also contains a random link or device failure counts as injected, and
                   it is flagged.
    unit           the primary unit is the injected surge: its first onset (ties: the link with
                   the higher utilisation, then the lower link id) is scored. A surge can congest
                   two links at once (the two hostel Wi-Fi uplinks); all injected onsets are also
                   scored, as a secondary view.
    predicted problem time error  the episode's predicted problem time (Episode.predicted_time:
                   generated_at + the earliest warning horizon) minus the onset time, in minutes,
                   taken at the episode's first warning and, separately, at the last warning
                   before the onset. Negative = the problem was predicted too early.
    per-class false alarms  false-alarm episodes that start inside a surge's window (its start to
                   the end of its ramp-down + 10 min) count against that surge's class; the rest
                   are "outside surges". Totals are given per day and per episode.
    calibration    every Random Forest warning on a link below 90 % now (the classifier's
                   warnings; "critical now" warnings come from the regression trees and are
                   excluded), binned by its confidence score (0-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0),
                   against the share followed by an onset on that link within the warning's
                   horizon. The share that merely reached 90 % within the horizon (the
                   classifier's own training target) is shown beside it. Reported for all
                   warnings, per horizon, and (amendment 6) per ramp class: warnings at cycles
                   inside each class's surge windows, plus the warnings outside surges.

Target (plan section 11)
    A median lead time of 10 minutes or more: the median over the detected primary onsets of all
    injected surges, all ramp classes together (Random Forest). Reported beside it:
    - the detection rate;
    - the median with every missed surge counted as 0 minutes;
    - the median without the flagged leads (amendment 3).
    The run is valid only if the protocol, the registration and the active models are unchanged
    and the determinism check passes. An invalid run does not meet the target.

Example event chart: by a rule fixed in advance, the first medium-ramp surge in time order that has
an onset (if none has, the first surge with an onset).

Also reported per surge and class: the most lead possible (amendment 5). That is the onset time
minus the first reading that contains the surge, which is the surge's start + one cycle, because a
surge is added at the start of the cycle that begins then. A warning can only come earlier by
luck, and a detection whose episode started at or before the surge's start is flagged. The figure
shows how much of the possible lead each method used; the lead-time chart draws it as a third
series. The plain minutes from the surge's start to its onset are in surges.csv too.

Outputs (results/E3/):
- REGISTRATION.md and registration.json, written before the first prediction;
- results.json, written only at the end, so an interrupted run leaves no verdict;
- schedule.csv and probes.csv (the injection plan);
onsets.csv, surges.csv, episodes.csv (every scored item); metrics_by_class.csv; calibration.csv;
faults.csv; the CSV behind each chart; charts e3_lead_time_by_class.png,
e3_detection_rate_by_class.png, e3_example_event.png and e3_calibration.png.

Limitations
    * The network is the emulator, and the surges are synthetic trapezoids on top of smooth daily
      profiles. Real surges are less regular. Results show the method on this emulated campus.
    * Surge sizes come from an oracle probe of the future (the fork), so every injected surge is
      known to congest. The ladder is coarse, so a surge often overshoots 95 %; the link then
      crosses 90 % partway up the ramp, and the time from the surge's start to the onset (the
      most lead any method could have from the surge itself) is shorter than the ramp. It is
      reported per surge.
    * Locations differ from training at the source (zone, traffic class, time of day), but the
      campus has few links that can congest: daytime surges congest the 200 Mbps ISP-B uplink
      (it carries about half of all internet traffic) and evening surges the 100 Mbps hostel Wi-Fi
      uplinks. Training's flash crowds loaded the same links, so the models have seen ramps there.
    * Six surges per class: rates and medians carry wide uncertainty, and the 10th percentile of
      six values is close to the minimum. One world seed, one topology, three weekdays.
    * The surge times repeat every day, and the same links congest: ISP-B by day, the hostel
      uplinks in the evening. So from Tuesday on, the full model's same-time-yesterday features
      contain the previous day's injected surge.
      - The warning classifier uses only short-history features and is not affected.
      - The regression forest is affected: the predicted utilisation, the "critical now"
        warnings, and the calm test that ends episodes.
      False alarms are therefore reported per day (amendment 8).
    * An episode that starts more than 35 minutes before an onset is, by the definitions, both a
      false alarm and the episode that detects the onset. Such cases are flagged in the CSV.
    * Warnings of one link at four horizons and on consecutive minutes are strongly correlated, so
      the calibration table counts many dependent warnings from few episodes.
    * The predicted problem time is generated_at + the earliest warning horizon, so it moves in
      steps of the horizons (5, 10, 15, 30 min). A warning one minute before the onset always says
      "in 5 minutes", an error of +4 minutes by construction.
    * The twin's event path (instant up/down updates) is not exercised here; it does not affect
      forecasts, which use the per-cycle readings only.

Quick mode (--quick) checks the pipeline:
- 2 days of warm-up;
- a 9-hour experiment, Monday 07:00 to 16:00 WAT;
- one surge per class: 08:00 slow, 11:00 medium, 14:00 fast.

The full model still serves, because it needs only one day of history. A quick run takes about
5-12 minutes, depending on the load on the laptop. Its numbers are not for Chapter 4.

A full-mode run with --hours or --warmup-days other than the protocol's is recorded as a
deviation (amendment 9).

Run time (estimate). On the 2-core Celeron laptop the full run takes about 1 to 1.5 hours on an
idle machine: the warm-up (10,080 twin cycles at 27-45 ms, 5-8 min), the planning pass with its
probes (4,680 emulator cycles plus about 100 forks, 3-5 min) and 4,680 prediction cycles at about
0.5-1 s each (the Predictor rebuilds its features over the whole 7-day buffer every cycle, about
0.45 s idle). It can take 2 hours or more while other programs load the processor.

    python -m evaluation.e3_early_warning [--quick] [--hours 78] [--warmup-days 7]
    python -m evaluation.e3_early_warning --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import statistics
import time
import warnings
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np

from digital_twin.prediction_engine.alerts import AlertTracker, Episode, Forecast
from digital_twin.prediction_engine.features import (
    MAX_FILL_GAP,
    SHORT_HISTORY,
    FeatureSpec,
    build_features,
    fill_short_gaps,
)
from digital_twin.prediction_engine.models import baseline_predictions
from netemu.network import EmulatedNetwork
from netemu.topology import Topology, load_topology

from .common import (
    INK,
    INK_2,
    MUTED,
    ROOT,
    SERIES,
    Results,
    chart,
    git_commit,
    legend,
    threshold_lines,
)
from .twin import Twin

CAMPUS = ROOT / "data" / "topologies" / "campus.yaml"
PROTOCOL = ROOT / "docs" / "evaluation" / "E3_PROTOCOL.md"
PROTOCOL_SHA256 = "3bcc5537a4bfcc93cb199ba6516b7b05dd6e242666eb2240484cbe0b4fd73584"   # LF line endings
WAT = timezone(timedelta(hours=1), "WAT")

WORLD_SEED = 2026                  # emulator seed (the training history used 7)
FLASH_CROWD_SEED = 2026            # warm-up flash crowds (training used campus.yaml's seed 11)
EXPERIMENT_START = datetime(2026, 11, 2, 0, 0, tzinfo=WAT)    # Monday, after the training window
EXPERIMENT_HOURS = 78              # to Thursday 5 November 06:00 WAT
WARMUP_DAYS = 7                    # = runtime/forecasting.py HISTORY_DAYS (checked at run time)
QUICK_START = datetime(2026, 11, 2, 7, 0, tzinfo=WAT)
QUICK_HOURS = 9                    # to 16:00: past the last quick surge's false-alarm window, and ~5 min
QUICK_WARMUP_DAYS = 2
TRUTH_KEEP = 10                    # cycles of ground truth and flows the emulator keeps (cheap forks)

RAMP_CLASSES = (("slow", 30), ("medium", 15), ("fast", 5))      # ramp minutes
HOLD_MINUTES = 30
SLOT_HOURS = (8, 11, 14, 17, 20, 23)                              # WAT, 3 h apart
LOCATIONS = (                      # [day][slot] -> (zone, traffic class); none is a training template
    (("SOT", "video"), ("ICT", "web"), ("SCI", "web"), ("LIB", "web"),
     ("HOSTEL", "elearning"), ("HOSTEL", "portal")),
    (("SCI", "web"), ("ENG", "video"), ("ICT", "video"), ("SOT", "video"),
     ("HOSTEL", "portal"), ("HOSTEL", "elearning")),
    (("ENG", "video"), ("ADMIN", "web"), ("SOT", "video"), ("SCI", "web"),
     ("HOSTEL", "elearning"), ("HOSTEL", "portal")),
)
LADDER = (1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0)
PROBE_PEAK_PCT = 95.0

ONSET_PCT = 90.0                   # = the critical threshold (checked against settings at run time)
REARM_BELOW_PCT = 85.0
REARM_CYCLES = 5
DETECT_MIN_MINUTES, DETECT_MAX_MINUTES = 1, 35
FALSE_ALARM_MINUTES = 35
ATTRIBUTION_MARGIN_MINUTES = 10
ARMING_PREFIX = 60                 # warm-up cycles that set the onset detector's state
CONFIDENCE_BINS = (0.0, 0.4, 0.6, 0.8, 1.0)
TARGET_LEAD_MINUTES = 10.0
TREND_TAIL = SHORT_HISTORY + MAX_FILL_GAP + 5    # buffer rows the trend alarm needs (slope 15, gap fill)

METHODS = ("rf", "trend")
METHOD_LABELS = {"rf": "Random Forest warning", "trend": "Linear-trend alarm"}
CLASS_LABELS = {"slow": "Slow", "medium": "Medium", "fast": "Fast", "all": "All classes"}

_STARTED = time.perf_counter()


def log(message: str) -> None:
    print(f"{time.perf_counter() - _STARTED:6.0f} s  {message}", flush=True)


# ------------------------------------------------------------------ schedule
@dataclass
class Surge:
    number: int
    ramp_class: str
    ramp_minutes: int
    zone: str
    cls: str
    start: datetime
    hold_minutes: int = HOLD_MINUTES
    multiplier: float | None = None           # None: not congesting at any ladder value (not injected)
    tries: list = field(default_factory=list)  # [(multiplier, peak %, link id)] from the probe
    target_link: int | None = None             # the link that reached 95 % in the probe

    @property
    def id(self) -> str:
        return f"S{self.number:02d}"

    @property
    def t0(self) -> float:
        return self.start.timestamp()

    @property
    def peak_end(self) -> float:               # end of ramp + hold
        return self.t0 + (self.ramp_minutes + self.hold_minutes) * 60

    @property
    def attribution_end(self) -> float:
        return self.peak_end + ATTRIBUTION_MARGIN_MINUTES * 60

    @property
    def window_end(self) -> float:             # end of the ramp-down + 10 min (per-class false alarms)
        return self.t0 + (2 * self.ramp_minutes + self.hold_minutes + ATTRIBUTION_MARGIN_MINUTES) * 60

    @property
    def injected(self) -> bool:
        return self.multiplier is not None


def build_schedule(first_day: date, days: int, slots: tuple[int, ...] = SLOT_HOURS) -> list[Surge]:
    """The fixed injection schedule: class (slot + day) mod 3, so each class meets each slot once."""
    surges = []
    for day in range(days):
        for s, hour in enumerate(slots):
            name, ramp = RAMP_CLASSES[(s + day) % len(RAMP_CLASSES)]
            zone, cls = LOCATIONS[day][s]
            start = datetime(first_day.year, first_day.month, first_day.day, hour, 0, tzinfo=WAT) + timedelta(days=day)
            surges.append(Surge(len(surges) + 1, name, ramp, zone, cls, start))
    return surges


# ------------------------------------------------------------------ scoring (pure, self-tested)
def find_onsets(util: np.ndarray, onset_pct: float = ONSET_PCT, rearm_below: float = REARM_BELOW_PCT,
                rearm_cycles: int = REARM_CYCLES) -> tuple[list[tuple[int, int]], np.ndarray]:
    """Onsets in a (T, L) ground-truth array: [(row, column)], and a (T, L) mask that is True from
    an onset until the link has re-armed (5 consecutive cycles below 85 %).

    A link starts disarmed: it needs 5 cycles below 85 % before its first onset."""
    rows, links = util.shape
    onsets: list[tuple[int, int]] = []
    congested = np.zeros((rows, links), dtype=bool)
    for col in range(links):
        u = util[:, col]
        armed, below, after_onset = False, 0, False
        for i in range(rows):
            if armed and u[i] >= onset_pct and i + 1 < rows and u[i + 1] >= onset_pct:
                onsets.append((i, col))
                armed, after_onset = False, True
            below = below + 1 if u[i] < rearm_below else 0
            if below >= rearm_cycles:
                armed, after_onset = True, False
            congested[i, col] = after_onset          # state after this cycle
    return sorted(onsets), congested


@dataclass
class EpisodeRec:
    method: str
    link_id: int
    start: float                    # epoch seconds of the first warning
    end: float | None               # epoch seconds of the cycle that ended it (None: still active)
    predicted: float                # predicted problem time at the first warning
    horizon: int
    confidence: float
    critical_now: bool
    category: str = ""              # true / late / false / unscored
    surge: str = ""                 # surge whose window contains the start ("" = outside surges)
    ramp_class: str = ""


def episode_record(method: str, episode: Episode) -> EpisodeRec:
    return EpisodeRec(method, episode.link_id, episode.started_at.timestamp(), None,
                      episode.predicted_time.timestamp(), episode.horizon_minutes, episode.confidence,
                      episode.critical_now)


def covering_episode(episodes: list[EpisodeRec], moment: float) -> EpisodeRec | None:
    for ep in episodes:
        if ep.start <= moment and (ep.end is None or moment < ep.end):
            return ep
    return None


def score_onset(onset_t: float, warn_times: np.ndarray, episodes: list[EpisodeRec],
                earliest_warning: dict[float, int] | None = None) -> dict:
    """Detection, lead time and predicted-time errors of one onset for one method.

    warn_times: sorted epoch seconds of the cycles at which the method warned on this link.
    episodes: the method's episodes on this link. earliest_warning: {cycle time: earliest warning
    horizon in minutes} for this link, for the predicted time at the last warning."""
    lo, hi = onset_t - DETECT_MAX_MINUTES * 60, onset_t - DETECT_MIN_MINUTES * 60
    inside = warn_times[(warn_times >= lo - 1e-6) & (warn_times <= hi + 1e-6)]
    out = {"detected": False, "lead_min": None, "first_warning": None, "episode_start": None,
           "predicted_error_first_min": None, "predicted_error_last_min": None, "early_episode": False}
    if len(inside) == 0:
        return out
    last = float(inside.max())
    episode = covering_episode(episodes, last)
    if episode is None:              # cannot happen when episodes come from the same warnings
        raise ValueError("a warning outside every episode")
    out.update(detected=True, lead_min=(onset_t - episode.start) / 60.0, first_warning=episode.start,
               episode_start=episode.start, predicted_error_first_min=(episode.predicted - onset_t) / 60.0,
               early_episode=episode.start < lo - 1e-6)
    if earliest_warning is not None and last in earliest_warning:
        out["predicted_error_last_min"] = (last + earliest_warning[last] * 60 - onset_t) / 60.0
    return out


def classify_episode(ep: EpisodeRec, onset_times: np.ndarray, congested_at_start: bool,
                     last_scorable: float) -> str:
    """true: an onset on the link within 35 min after the start; late: started while the link was
    still congested; unscored: the 35-minute window runs past the end of the run; else false."""
    window = (onset_times >= ep.start - 1e-6) & (onset_times <= ep.start + FALSE_ALARM_MINUTES * 60 + 1e-6)
    if window.any():
        return "true"
    if congested_at_start:
        return "late"
    if ep.start + FALSE_ALARM_MINUTES * 60 > last_scorable:
        return "unscored"
    return "false"


def lead_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p10": None, "min": None, "max": None}
    arr = np.asarray(values, dtype=float)
    return {"n": len(values), "median": float(np.median(arr)), "p10": float(np.percentile(arr, 10)),
            "min": float(arr.min()), "max": float(arr.max())}


def reliability(confidence: np.ndarray, followed: np.ndarray, reached: np.ndarray,
                bins: tuple[float, ...] = CONFIDENCE_BINS) -> list[dict]:
    """Rows per confidence bin: warnings, mean confidence, share followed by an onset, share reaching 90 %."""
    rows = []
    for i, (lo, hi) in enumerate(zip(bins[:-1], bins[1:], strict=True)):
        last = i == len(bins) - 2
        mask = (confidence >= lo) & ((confidence <= hi) if last else (confidence < hi))
        n = int(mask.sum())
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "warnings": n,
                     "mean_confidence": float(confidence[mask].mean()) if n else None,
                     "share_followed_by_onset": float(followed[mask].mean()) if n else None,
                     "share_reaching_90": float(reached[mask].mean()) if n else None})
    return rows


def trend_projection(times: np.ndarray, util: np.ndarray, errors: np.ndarray, static: np.ndarray,
                     spec: FeatureSpec) -> tuple[np.ndarray, np.ndarray]:
    """The linear-trend alarm's projections (L, H) and the current (gap-filled) utilisation (L,),
    from the tail of the history buffer, with the production feature function."""
    tail = slice(max(0, len(times) - TREND_TAIL), len(times))
    filled = fill_short_gaps(util[tail])
    X = build_features(filled, times[tail], static, errors[tail], spec, np.array([len(filled) - 1]))[0]
    return baseline_predictions(X, spec)["linear_trend"], X[:, 0]


# ------------------------------------------------------------------ world
def e3_topology() -> Topology:
    topo = load_topology(CAMPUS)
    return replace(topo, random_surges=replace(topo.random_surges, seed=FLASH_CROWD_SEED))


def truth_util(net: EmulatedNetwork) -> np.ndarray:
    return np.array([x["utilisation_pct"] for x in net.truth[-1]["links"]], dtype=np.float64)


def emulator_cycle(net: EmulatedNetwork) -> np.ndarray:
    """One monitoring cycle of the emulator alone, drawing from its random stream exactly as the
    twin's poll does (one /v1/snapshot per cycle), so a fork stays identical to the real run."""
    for _ in range(net.steps_per_cycle()):
        net.step()
    net.snapshot()
    return truth_util(net)


def switch_off_flash_crowds(net: EmulatedNetwork) -> list[dict]:
    """Random flash crowds off from now on. The lab's switch (POST /lab/faults {"random_surges": false})
    only stops new days from being drawn: the emulator draws a whole day's flash crowds when the day
    is first seen, so the current day's would still start later. Those that have not started yet
    are removed as well (returned); one already in progress runs to its end."""
    net.traffic.random_surges_enabled = False
    later = [s for s in net.traffic.surges if s.start > net.t]
    net.traffic.surges = [s for s in net.traffic.surges if s.start <= net.t]
    return [{"zone": s.zone, "cls": s.cls, "multiplier": round(s.multiplier, 3),
             "start": s.start.astimezone(WAT).isoformat(timespec="minutes")} for s in later]


def surge_list(net: EmulatedNetwork) -> list[dict]:
    return [{"zone": s.zone, "cls": s.cls, "multiplier": round(s.multiplier, 3),
             "start": s.start.astimezone(WAT).isoformat(timespec="minutes"),
             "end": s.end.astimezone(WAT).isoformat(timespec="minutes")}
            for s in net.traffic.surges]


@dataclass
class WarmUp:
    times: np.ndarray
    util: np.ndarray
    errors: np.ndarray
    prefix: np.ndarray              # last ARMING_PREFIX ground-truth cycles
    congested_cycles: int           # cycles in which some link was at or above 90 % (ground truth)


def warm_up(twin: Twin, cycles: int, link_ids: list[int]) -> WarmUp:
    times = np.zeros(cycles)
    util = np.full((cycles, len(link_ids)), np.nan, dtype=np.float32)
    errors = np.full((cycles, len(link_ids)), np.nan, dtype=np.float32)
    column = {link_id: i for i, link_id in enumerate(link_ids)}
    prefix: list[np.ndarray] = []
    congested = 0
    for k in range(cycles):
        twin.step_cycle()
        clean = twin.ingest()
        truth = truth_util(twin.net)
        congested += int(truth.max() >= ONSET_PCT)
        prefix = (prefix + [truth])[-ARMING_PREFIX:]
        if clean is None:
            times[k] = np.nan
            continue
        times[k] = clean.timestamp.timestamp()
        for link_id, reading in clean.links.items():
            if reading.utilisation_pct is not None:
                util[k, column[link_id]] = reading.utilisation_pct
            if reading.error_count is not None:
                errors[k, column[link_id]] = float(reading.error_count)
        if (k + 1) % 1440 == 0:
            log(f"warm-up day {(k + 1) // 1440} done")
    keep = ~np.isnan(times)
    return WarmUp(times[keep], util[keep], errors[keep], np.array(prefix), congested)


def probe(world: EmulatedNetwork, surge: Surge, link_ids: list[int]) -> None:
    """Choose the surge's multiplier: the smallest on the ladder that takes some link to 95 % within
    ramp + hold minutes in a fork of the world."""
    for multiplier in LADDER:
        fork = copy.deepcopy(world)
        fork.add_surge(surge.zone, surge.cls, multiplier, surge.ramp_minutes, surge.hold_minutes, 0.0)
        peak, where = -1.0, None
        for _ in range(surge.ramp_minutes + surge.hold_minutes):
            u = emulator_cycle(fork)
            if u.max() > peak:
                peak, where = float(u.max()), link_ids[int(np.argmax(u))]
        surge.tries.append((multiplier, round(peak, 3), where))
        if peak >= PROBE_PEAK_PCT:
            surge.multiplier, surge.target_link = multiplier, where
            return


def plan(net: EmulatedNetwork, surges: list[Surge], cycles: int, link_ids: list[int]) -> np.ndarray:
    """The planning pass: run a copy of the world through the experiment, choosing and adding each
    surge in turn (no forecasting). Returns its ground truth (cycles, L) for the determinism check."""
    world = copy.deepcopy(net)
    truth = np.zeros((cycles, len(link_ids)))
    pending = sorted(surges, key=lambda s: s.t0)
    for k in range(cycles):
        while pending and pending[0].t0 <= world.t.timestamp() + 1e-6:
            surge = pending.pop(0)
            probe(world, surge, link_ids)
            if surge.injected:
                world.add_surge(surge.zone, surge.cls, surge.multiplier, surge.ramp_minutes, surge.hold_minutes, 0.0)
            log(f"planned {surge.id} {surge.ramp_class} {surge.zone}/{surge.cls} at "
                f"{surge.start:%a %H:%M}: x{surge.multiplier} (peak {surge.tries[-1][1]:.1f} % on link {surge.tries[-1][2]})")
        truth[k] = emulator_cycle(world)
    return truth


# ------------------------------------------------------------------ protocol
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(path: Path) -> str:
    """SHA-256 of a text file with line endings normalised to LF (git may check it out with CRLF)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def link_name(topo: Topology, link_id: int) -> str:
    lk = topo.links[link_id - 1]
    return f"{lk.a} - {lk.b}"


def wat(epoch: float | None) -> str:
    return "" if epoch is None else datetime.fromtimestamp(epoch, UTC).astimezone(WAT).strftime("%a %d %b %H:%M")


def model_manifest(model_dir: Path) -> list[dict]:
    active = json.loads((model_dir / "active.json").read_text(encoding="utf-8"))
    out = []
    for kind, version in sorted(active.items()):
        meta = json.loads((model_dir / version / "meta.json").read_text(encoding="utf-8"))
        out.append({"kind": kind, "version": version, "model_sha256": sha256_file(model_dir / version / "model.joblib"),
                    "warning_threshold": meta["rows"].get("warning_threshold"), "window": meta["window"],
                    "features": "with same-time-yesterday" if meta["spec"]["full"] else "short history"})
    return out


def write_registration(path: Path, *, quick: bool, config: dict, surges: list[Surge], topo: Topology,
                       models: list[dict], leftovers: list[dict]) -> str:
    if quick:
        kind = "**QUICK RUN: a pipeline check, not for Chapter 4.**"
    elif config.get("deviation_from_plan"):
        kind = f"**Full run with a deviation from the protocol:** {config['deviation_from_plan']}"
    else:
        kind = "**Full run, as the protocol sets it.**"
    lines = [
        "# E3 Early warning: run registration", "",
        kind, "",
        f"Registered {datetime.now(UTC).isoformat(timespec='seconds')} (wall clock), before any prediction "
        f"of this run. The protocol is {PROTOCOL.relative_to(ROOT).as_posix()} (SHA-256 {PROTOCOL_SHA256}); its "
        "definitions, target and reporting rules apply unchanged. Code version "
        f"{config['code_version']}; code SHA-256: "
        + ", ".join(f"{name} {digest[:16]}..." for name, digest in config["code_sha256"].items())
        + ". The SHA-256 of this file is stored in registration.json and results.json.",
        "", "## World", "",
        f"- Topology {CAMPUS.relative_to(ROOT).as_posix()} (SHA-256 {config['topology_sha256'][:16]}...), "
        f"reality gap preset \"default\"; random link/device failures on; data-quality faults on.",
        f"- Emulator seed {WORLD_SEED} (training history: 7). Warm-up flash crowds drawn with seed "
        f"{FLASH_CROWD_SEED} (training: {config['training_flash_crowd_seed']}).",
        f"- World starts {config['world_start']}; warm-up of {config['warmup_days']} days with normal "
        "behaviour (flash crowds on), every cycle through the twin's ingest path into the history buffer; "
        "no forecasts during the warm-up.",
        f"- Experiment {config['experiment_start']} to {config['experiment_end']} ({config['experiment_hours']} h, "
        f"{config['experiment_cycles']} cycles). Random flash crowds switched off at the start: no new ones are "
        "drawn (the lab switch), and those already drawn for the day that had not started yet are removed: "
        + ("; ".join(f"{s['zone']}/{s['cls']} x{s['multiplier']} at {s['start']}"
                     for s in config["flash_crowds_cancelled_at_start"]) or "none") + ".",
        "- Flash crowds already running at the experiment start (they run to their end; their onsets count as "
        "natural): " + ("; ".join(f"{s['zone']}/{s['cls']} x{s['multiplier']} {s['start']} to {s['end']}"
                                  for s in leftovers) if leftovers else "none."),
        "- Training flash-crowd templates (zone/class, weight): "
        + ", ".join(f"{t.zone}/{t.cls} ({t.weight:g})" for t in topo.random_surges.templates) + ".",
        "", "## Models (var/models/active.json, served as runtime/forecasting.py ForecastService)", "",
    ]
    for m in models:
        lines.append(f"- {m['kind']}: {m['version']} ({m['features']}), warning threshold {m['warning_threshold']}, "
                     f"model.joblib SHA-256 {m['model_sha256'][:16]}..., training window {m['window']['train_start']} "
                     f"to {m['window']['test_end']}.")
    lines += [
        f"- Choice as in the engine: the full model once the buffer holds more than one day, else the short "
        f"model. History buffer {config['buffer_cycles']} cycles (HISTORY_DAYS = {config['history_days']}). "
        f"Critical threshold {config['critical_pct']:g} %, alert hysteresis: clear below "
        f"{config['clear_below_pct']:g} % for {config['clear_cycles']} cycles.",
        "", "## Injection schedule", "",
        f"Ramp classes: {', '.join(f'{n} {r} min' for n, r in RAMP_CLASSES)}; hold {HOLD_MINUTES} min; ramp-down "
        f"as the ramp-up. Multiplier: the smallest of {', '.join(f'{m:g}' for m in LADDER)} that takes some link to "
        f">= {PROBE_PEAK_PCT:g} % within ramp + hold in a fork of the world (planning pass, no forecasts). "
        "A surge with no such multiplier is not injected and is kept out of the detection statistics.", "",
        "| Surge | Time (WAT) | Ramp class | Zone / class | Multiplier | Probe peak | Link | Tried (multiplier: peak %) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in surges:
        peak = s.tries[-1][1] if s.tries else None
        link = link_name(topo, s.tries[-1][2]) if s.tries and s.tries[-1][2] else ""
        tried = ", ".join(f"{m:g}: {p:.1f}" for m, p, _ in s.tries)
        lines.append(f"| {s.id} | {s.start:%a %d %b %H:%M} | {s.ramp_class} ({s.ramp_minutes} min) | {s.zone} / {s.cls} | "
                     f"{'x' + format(s.multiplier, 'g') if s.injected else 'not congesting'} | {peak} | {link} | {tried} |")
    lines += [
        "", "## Definitions (as in the protocol)", "",
        f"- **Onset**: the first of two consecutive ground-truth cycles at or above {ONSET_PCT:g} % on a link, after at "
        f"least {REARM_CYCLES} consecutive cycles below {REARM_BELOW_PCT:g} % on that link. Onset time = the end of that "
        f"cycle. The detector's state at the start comes from the last {ARMING_PREFIX} warm-up cycles.",
        f"- **Detected**: a warning (any horizon) on that link at a cycle {DETECT_MIN_MINUTES}-{DETECT_MAX_MINUTES} min "
        "before the onset.",
        "- **Lead time**: onset time minus the first warning of the episode containing the last warning in that "
        "window (flagged when that episode started more than 35 min before the onset).",
        f"- **False alarm** (the plan's definition, the headline figure): an alert episode with no onset on its link "
        f"from its start to {FALSE_ALARM_MINUTES} min after it. Episodes that start while the link is still congested "
        "are also shown separately as **late alarms**. Episodes whose 35-minute window runs past the end are unscored.",
        f"- **Attribution**: an onset belongs to a surge if its time is within [start, start + ramp + hold + "
        f"{ATTRIBUTION_MARGIN_MINUTES} min] of an injected surge; all other onsets are **natural** and reported "
        "separately (also those in the window of a surge that was not injected).",
        "- **Unit**: each injected surge's first onset (ties: higher utilisation, then lower link id); all injected "
        "onsets as a secondary view.",
        "- **Predicted problem time error**: Episode.predicted_time - onset (min), at the episode's first warning "
        "and at the last warning before the onset.",
        "- **Most lead possible** (context, not a criterion): the onset minus (the surge's start + one cycle), "
        "the first reading that contains the surge.",
        f"- **Per-class false alarms**: false-alarm episodes starting in [surge start, end of ramp-down + "
        f"{ATTRIBUTION_MARGIN_MINUTES} min]; the rest are outside surges. Totals per day and per episode.",
        "- **Calibration**: Random Forest warnings on links below 90 % now, by confidence bin "
        f"({', '.join(f'{a:g}-{b:g}' for a, b in zip(CONFIDENCE_BINS[:-1], CONFIDENCE_BINS[1:], strict=True))}), "
        "against the share followed by an onset on that link within the warning's horizon (and the share reaching "
        "90 %); for all warnings, per horizon and per ramp class.",
        "- **Comparison**: the linear-trend alarm (15-cycle slope projected to each horizon reaches 90 %) on the same "
        "buffer, with its own AlertTracker of the same settings, scored the same way.",
        "", "## Target", "",
        f"Median lead time >= {TARGET_LEAD_MINUTES:g} min: Random Forest, detected primary onsets of injected surges, "
        "all ramp classes together. Reported with the detection rate and with misses counted as 0 min.",
        "", "## Example event chart", "",
        "The first medium-ramp surge in time order with an onset (otherwise the first surge with an onset).", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return sha256_file(path)


# ------------------------------------------------------------------ prediction run
@dataclass
class RunData:
    truth: np.ndarray               # (N, L) ground truth
    twin_util: np.ndarray           # (N, L) the twin's readings
    now: np.ndarray                 # (N, L) gap-filled current utilisation the predictor used
    pred: np.ndarray                # (N, L, H) Random Forest forecast
    conf: np.ndarray                # (N, L, H) confidence
    warn: np.ndarray                # (N, L, H) Random Forest warning
    trend: np.ndarray               # (N, L, H) linear-trend projection
    trend_warn: np.ndarray          # (N, L, H)
    episodes: dict                  # method -> [EpisodeRec]
    model_cycles: dict              # model version -> cycles served
    predict_ms: list
    missing_polls: int
    first_prediction_at: str
    faults: list


def run_experiment(twin: Twin, service, surges: list[Surge], cycles: int, start: float, horizons: tuple[int, ...],
                   link_ids: list[int], critical: float, clear_below: float, clear_cycles: int) -> RunData:
    from digital_twin.runtime import forecasting

    net = twin.net
    n_links, n_h = len(link_ids), len(horizons)
    shape = (cycles, n_links, n_h)
    data = RunData(np.zeros((cycles, n_links)), np.full((cycles, n_links), np.nan), np.full((cycles, n_links), np.nan),
                   np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32), np.zeros(shape, bool),
                   np.full(shape, np.nan, np.float32), np.zeros(shape, bool), {m: [] for m in METHODS}, {}, [], 0, "",
                   [])
    column = {link_id: i for i, link_id in enumerate(link_ids)}
    h_index = {h: j for j, h in enumerate(horizons)}
    trend_spec = FeatureSpec(service.cycle_seconds, tuple(horizons), full=False)
    trend_tracker = AlertTracker(critical, clear_below, clear_cycles)
    live = {m: {} for m in METHODS}                  # id(Episode) -> (Episode, EpisodeRec)
    event_seq = net.event_seq
    pending = sorted((s for s in surges if s.injected), key=lambda s: s.t0)
    with mock.patch.object(forecasting.persistence, "write_predictions", lambda rows: None):
        for k in range(cycles):
            while pending and pending[0].t0 <= net.t.timestamp() + 1e-6:
                surge = pending.pop(0)
                with net.lock:                         # as POST /lab/surge
                    net.add_surge(surge.zone, surge.cls, surge.multiplier, surge.ramp_minutes, surge.hold_minutes, 0.0)
            twin.step_cycle()
            clean = twin.ingest()
            data.truth[k] = truth_util(net)
            if clean is None:
                data.missing_polls += 1
                continue
            moment = clean.timestamp.timestamp()
            if abs(moment - (start + (k + 1) * service.cycle_seconds)) > 1.0:
                raise RuntimeError(f"cycle {k} has timestamp {clean.timestamp}, expected the end of the cycle")
            if clean.capacity_changes:
                service.refresh_static(twin.model)
            began = time.perf_counter()
            rows, started, ended = service.on_cycle(clean)          # buffer -> Predictor -> AlertTracker
            data.predict_ms.append((time.perf_counter() - began) * 1000)
            if not data.first_prediction_at:
                data.first_prediction_at = datetime.now(UTC).isoformat(timespec="seconds")
            for r in rows:
                i, j = column[r.link_id], h_index[r.horizon_minutes]
                data.pred[k, i, j], data.conf[k, i, j], data.warn[k, i, j] = (
                    r.predicted_utilisation, r.confidence_score, r.is_warning)
            if rows:
                version = rows[0].model_version
                data.model_cycles[version] = data.model_cycles.get(version, 0) + 1
            for link_id, reading in clean.links.items():
                if reading.utilisation_pct is not None:
                    data.twin_util[k, column[link_id]] = reading.utilisation_pct
            _track(live["rf"], data.episodes["rf"], "rf", started, ended)

            # the linear-trend alarm on the same buffer
            times, util, errors = service.buffer.arrays()
            projection, now = trend_projection(times, util, errors, service.static, trend_spec)
            data.now[k] = now
            data.trend[k] = projection
            forecasts = {}
            for i, link_id in enumerate(link_ids):
                if np.isnan(now[i]):
                    continue
                forecasts[link_id] = [Forecast(h, float(projection[i, j]), 1.0, bool(projection[i, j] >= critical))
                                      for j, h in enumerate(horizons)]
                data.trend_warn[k, i] = projection[i] >= critical
            util_now = {link_id: r.utilisation_pct for link_id, r in clean.links.items()}
            t_started, t_ended = trend_tracker.update(clean.timestamp, forecasts, util_now)
            _track(live["trend"], data.episodes["trend"], "trend", t_started, t_ended)
            if (k + 1) % 120 == 0:
                log(f"prediction cycle {k + 1}/{cycles}, median {statistics.median(data.predict_ms):.0f} ms per forecast")
    data.faults = [e for e in net.events_after(event_seq) if e["type"].endswith("_down")]
    return data


def _track(live: dict, records: list[EpisodeRec], method: str, started: list[Episode], ended: list[Episode]) -> None:
    for episode in started:
        rec = episode_record(method, episode)
        live[id(episode)] = (episode, rec)
        records.append(rec)
    for episode in ended:
        _, rec = live.pop(id(episode))
        rec.end = episode.ended_at.timestamp()


# ------------------------------------------------------------------ analysis
def analyse(data: RunData, prefix: np.ndarray, surges: list[Surge], start: float, cycle: int,
            horizons: tuple[int, ...], link_ids: list[int]) -> dict:
    n_cycles = data.truth.shape[0]
    times = start + (np.arange(n_cycles) + 1) * cycle
    full = np.vstack([prefix, data.truth])
    found, congested = find_onsets(full)
    congested = congested[len(prefix):]
    onsets = []
    for row, col in found:
        k = row - len(prefix)
        if k < 0:
            continue
        surge = next((s for s in surges if s.injected and s.t0 <= times[k] + 1e-6 <= s.attribution_end + 2e-6), None)
        onsets.append({"k": k, "time": float(times[k]), "link_id": link_ids[col], "col": col,
                       "util_pct": float(data.truth[k, col]), "surge": surge.id if surge else "",
                       "ramp_class": surge.ramp_class if surge else "", "natural": surge is None})

    fault_times = [datetime.fromisoformat(f["time"]).timestamp() for f in data.faults]
    for onset in onsets:
        surge = next((s for s in surges if s.id == onset["surge"]), None)
        onset["fault_in_surge_window"] = bool(surge and any(surge.t0 <= t <= surge.attribution_end for t in fault_times))

    warn_any = {"rf": data.warn.any(axis=2), "trend": data.trend_warn.any(axis=2)}
    earliest = {}
    for method, warn in (("rf", data.warn), ("trend", data.trend_warn)):
        table: dict[int, dict[float, int]] = {}
        ks, cols = np.nonzero(warn.any(axis=2))
        for k, col in zip(ks, cols, strict=True):
            j = int(np.argmax(warn[k, col]))
            table.setdefault(int(col), {})[float(times[k])] = horizons[j]
        earliest[method] = table
    by_link = {m: {} for m in METHODS}
    for method in METHODS:
        for ep in data.episodes[method]:
            by_link[method].setdefault(ep.link_id, []).append(ep)

    for onset in onsets:
        col = onset["col"]
        for method in METHODS:
            warn_times = times[warn_any[method][:, col]]
            score = score_onset(onset["time"], warn_times, by_link[method].get(onset["link_id"], []),
                                earliest[method].get(col, {}))
            surge = next((s for s in surges if s.id == onset["surge"]), None)
            # a warning at the surge's start was made from a reading without the surge (amendment 5)
            score["warning_before_surge"] = bool(score["detected"] and surge and score["first_warning"] <= surge.t0 + 1e-6)
            onset[method] = score

    last_scorable = float(times[-1]) - cycle         # an onset needs the next cycle too
    onset_times = {}
    for onset in onsets:
        onset_times.setdefault(onset["link_id"], []).append(onset["time"])
    for method in METHODS:
        for ep in data.episodes[method]:
            k = int(round((ep.start - start) / cycle)) - 1
            ep.category = classify_episode(ep, np.asarray(onset_times.get(ep.link_id, []), dtype=float),
                                           bool(congested[k, link_ids.index(ep.link_id)]), last_scorable)
            surge = next((s for s in surges if s.injected and s.t0 <= ep.start + 1e-6 <= s.window_end + 2e-6), None)
            ep.surge, ep.ramp_class = (surge.id, surge.ramp_class) if surge else ("", "")

    primaries = {}
    for surge in surges:
        mine = [o for o in onsets if o["surge"] == surge.id]
        if mine:
            primaries[surge.id] = min(mine, key=lambda o: (o["k"], -o["util_pct"], o["link_id"]))

    # calibration (Random Forest warnings on links below 90 % now)
    steps = [h * 60 // cycle for h in horizons]
    onset_mask = np.zeros_like(data.truth, dtype=bool)
    for o in onsets:
        onset_mask[o["k"], o["col"]] = True
    conf, followed, reached, horizon_of, class_of = [], [], [], [], []
    ks, cols, js = np.nonzero(data.warn)
    for k, col, j in zip(ks, cols, js, strict=True):
        if k + steps[j] >= n_cycles or not (data.now[k, col] < ONSET_PCT):
            continue
        conf.append(float(data.conf[k, col, j]))
        followed.append(bool(onset_mask[k + 1:k + 1 + steps[j], col].any()))
        reached.append(bool((data.truth[k + 1:k + 1 + steps[j], col] >= ONSET_PCT).any()))
        horizon_of.append(horizons[j])
        surge = next((s for s in surges if s.injected and s.t0 <= times[k] + 1e-6 <= s.window_end + 2e-6), None)
        class_of.append(surge.ramp_class if surge else "outside")
    conf_a, followed_a, reached_a = np.array(conf), np.array(followed, dtype=bool), np.array(reached, dtype=bool)
    calibration = {"all": reliability(conf_a, followed_a, reached_a)}
    for h in horizons:
        mask = np.array(horizon_of) == h
        calibration[str(h)] = reliability(conf_a[mask], followed_a[mask], reached_a[mask])
    for name in ("slow", "medium", "fast", "outside"):          # amendment 6
        mask = np.array(class_of) == name
        calibration[f"class:{name}"] = reliability(conf_a[mask], followed_a[mask], reached_a[mask])
    excluded_critical = int(sum(1 for k, col, j in zip(ks, cols, js, strict=True) if data.now[k, col] >= ONSET_PCT))
    return {"onsets": onsets, "primaries": primaries, "calibration": calibration, "times": times,
            "calibration_excluded_critical_now": excluded_critical, "calibration_warnings": len(conf)}


def class_metrics(analysis: dict, data: RunData, surges: list[Surge], hours: float, cycle: int) -> list[dict]:
    rows = []
    primaries, onsets = analysis["primaries"], analysis["onsets"]
    for method in METHODS:
        episodes = [e for e in data.episodes[method] if e.category != "unscored"]
        for cls in ("slow", "medium", "fast", "all"):
            mine = [s for s in surges if cls in ("all", s.ramp_class)]
            injected = [s for s in mine if s.injected]
            scored = [primaries[s.id] for s in injected if s.id in primaries]
            from_start = [(primaries[s.id]["time"] - s.t0) / 60.0 for s in injected if s.id in primaries]
            possible = [m - cycle / 60.0 for m in from_start]            # amendment 5
            detected = [o for o in scored if o[method]["detected"]]
            leads = [o[method]["lead_min"] for o in detected]
            misses_as_zero = leads + [0.0] * (len(scored) - len(detected))
            secondary = [o for o in onsets if o["surge"] and (cls == "all" or o["ramp_class"] == cls)]
            in_class = episodes if cls == "all" else [e for e in episodes if e.ramp_class == cls]
            false = [e for e in in_class if e.category in ("false", "late")]       # the plan's definition
            false_not_late = [e for e in in_class if e.category == "false"]
            flagged = [o for o in detected if o[method]["early_episode"] or o[method]["warning_before_surge"]]
            unflagged_leads = [o[method]["lead_min"] for o in detected if o not in flagged]
            errors_first = [o[method]["predicted_error_first_min"] for o in detected]
            errors_last = [o[method]["predicted_error_last_min"] for o in detected
                           if o[method]["predicted_error_last_min"] is not None]
            summary = lead_summary(leads)
            rows.append({
                "method": method, "ramp_class": cls, "surges_scheduled": len(mine), "surges_injected": len(injected),
                "surges_not_congesting": len(mine) - len(injected), "surges_with_onset": len(scored),
                "detected": len(detected), "detection_rate": len(detected) / len(scored) if scored else None,
                "lead_median_min": summary["median"], "lead_p10_min": summary["p10"], "lead_min_min": summary["min"],
                "lead_max_min": summary["max"],
                "lead_median_misses_as_0_min": float(np.median(misses_as_zero)) if misses_as_zero else None,
                "surge_start_to_onset_median_min": float(np.median(from_start)) if from_start else None,
                "most_lead_possible_median_min": float(np.median(possible)) if possible else None,
                "lead_median_without_flagged_min": float(np.median(unflagged_leads)) if unflagged_leads else None,
                "detected_with_episode_started_over_35_min_before": sum(o[method]["early_episode"] for o in detected),
                "detected_with_warning_before_surge_start": sum(o[method]["warning_before_surge"] for o in detected),
                "all_injected_onsets": len(secondary),
                "all_injected_onsets_detected": sum(o[method]["detected"] for o in secondary),
                "predicted_time_error_first_median_min": float(np.median(errors_first)) if errors_first else None,
                "predicted_time_abs_error_first_median_min": float(np.median(np.abs(errors_first))) if errors_first else None,
                "predicted_time_error_last_median_min": float(np.median(errors_last)) if errors_last else None,
                "episodes": len(in_class),
                "false_alarms": len(false),
                "false_alarms_per_episode": len(false) / len(in_class) if in_class else None,
                "false_alarms_per_day": len(false) / (hours / 24.0) if cls == "all" else None,
                "false_alarms_excluding_late": len(false_not_late),
                "late_alarms": sum(e.category == "late" for e in in_class),
                "true_alarms": sum(e.category == "true" for e in in_class),
                "false_alarms_outside_surges": sum(e.category in ("false", "late") and not e.surge for e in episodes)
                if cls == "all" else None,
                "injected_onsets_with_fault_in_window": sum(o.get("fault_in_surge_window", False) for o in secondary),
            })
    return rows


# ------------------------------------------------------------------ charts
def chart_lead_times(results: Results, analysis: dict, surges: list[Surge], cycle: int) -> list[dict]:
    classes = [name for name, _ in RAMP_CLASSES]
    ramps = dict(RAMP_CLASSES)
    primaries = analysis["primaries"]
    rows = []
    figure, axes = chart(6.6, 3.8)
    top = TARGET_LEAD_MINUTES
    labels = []
    # third series: the most lead possible, from the first reading that contains the surge to the onset
    series = (*METHODS, "available")
    series_labels = {**METHOD_LABELS, "available": "Most lead possible"}
    for c, cls in enumerate(classes):
        scored = [s for s in surges if s.ramp_class == cls and s.id in primaries]
        counts = []
        for j, method in enumerate(series):
            if method == "available":
                values = [(primaries[s.id]["time"] - s.t0 - cycle) / 60.0 for s in scored]
                style = {"facecolors": "none", "edgecolors": SERIES[j], "linewidths": 1.4}
            else:
                values = [primaries[s.id][method]["lead_min"] for s in scored if primaries[s.id][method]["detected"]]
                counts.append(f"{len(values)}/{len(scored)}")
                style = {"color": SERIES[j], "alpha": 0.85, "edgecolors": "white", "linewidths": 0.6}
            x = c + (j - 1) * 0.28
            offsets = np.linspace(-0.06, 0.06, len(values)) if len(values) > 1 else np.zeros(len(values))
            axes.scatter(x + offsets, values, s=26, zorder=3, label=series_labels[method] if c == 0 else None,
                         **style)
            if values:
                median = float(np.median(values))
                axes.plot([x - 0.11, x + 0.11], [median, median], color=SERIES[j], linewidth=3.0,
                          solid_capstyle="butt", zorder=4)
                top = max(top, max(values))
            if method == "available":
                rows += [{"series": method, "ramp_class": cls, "surge": s.id, "detected": None, "minutes": v}
                         for s, v in zip(scored, values, strict=True)]
            else:
                rows += [{"series": method, "ramp_class": cls, "surge": s.id,
                          "detected": primaries[s.id][method]["detected"], "minutes": primaries[s.id][method]["lead_min"]}
                         for s in scored]
        labels.append(f"{CLASS_LABELS[cls]} ramp ({ramps[cls]} min)\ndetected: RF {counts[0]}, trend {counts[1]}")
    axes.plot([], [], color=INK_2, linewidth=3.0, solid_capstyle="butt", label="Median")
    axes.axhline(TARGET_LEAD_MINUTES, color=INK_2, linestyle=(0, (4, 3)), linewidth=1.1,
                 label=f"Target: median {TARGET_LEAD_MINUTES:g} min", zorder=1)
    axes.set_xticks(range(len(classes)), labels)
    axes.set_xlim(-0.6, len(classes) - 0.4)
    axes.set_ylim(0, top * 1.15 + 1)
    axes.set_ylabel("Minutes before onset")
    legend(axes, ncol=3)
    results.save_chart(figure, "e3_lead_time_by_class.png")
    return rows


def chart_detection(results: Results, metrics: list[dict]) -> list[dict]:
    groups = ["slow", "medium", "fast", "all"]
    figure, axes = chart(6.4, 3.4)
    x = np.arange(len(groups))
    rows = []
    for j, method in enumerate(METHODS):
        values, labels = [], []
        for g in groups:
            row = next(r for r in metrics if r["method"] == method and r["ramp_class"] == g)
            rate = row["detection_rate"]
            values.append(100.0 * rate if rate is not None else 0.0)
            labels.append(f"{row['detected']}/{row['surges_with_onset']}")
            rows.append({"method": method, "ramp_class": g, "detected": row["detected"],
                         "surges_with_onset": row["surges_with_onset"],
                         "detection_rate_pct": 100.0 * rate if rate is not None else None})
        positions = x + (j - 0.5) * 0.38
        axes.bar(positions, values, width=0.35, color=SERIES[j], label=METHOD_LABELS[method], zorder=2)
        for pos, value, label in zip(positions, values, labels, strict=True):
            axes.text(pos, value + 1.5, label, ha="center", va="bottom", fontsize=7.5, color=INK_2)
    axes.set_xticks(x, [CLASS_LABELS[g] for g in groups])
    axes.set_ylim(0, 112)
    axes.set_yticks([0, 20, 40, 60, 80, 100])
    axes.set_ylabel("Surges detected 1-35 min before onset (%)")
    legend(axes, ncol=2)
    results.save_chart(figure, "e3_detection_rate_by_class.png")
    return rows


def example_surge(surges: list[Surge], primaries: dict) -> Surge | None:
    for s in sorted(surges, key=lambda s: s.t0):
        if s.ramp_class == "medium" and s.id in primaries:
            return s
    return next((s for s in sorted(surges, key=lambda s: s.t0) if s.id in primaries), None)


def chart_example(results: Results, analysis: dict, data: RunData, surges: list[Surge], horizons: tuple[int, ...],
                  topo: Topology, cycle: int) -> tuple[list[dict], dict]:
    surge = example_surge(surges, analysis["primaries"])
    if surge is None:
        return [], {}
    onset = analysis["primaries"][surge.id]
    times, col, k_on = analysis["times"], onset["col"], onset["k"]
    lo = max(0, int(round((surge.t0 - times[0]) / cycle)) - 30)
    hi = min(len(times), k_on + 61)
    rel = (times[lo:hi] - onset["time"]) / 60.0
    rows = []
    for idx, k in enumerate(range(lo, hi)):
        rows.append({"minutes_from_onset": rel[idx], "time_wat": wat(times[k]), "truth_pct": data.truth[k, col],
                     "twin_pct": data.twin_util[k, col],
                     **{f"rf_forecast_{h}min": data.pred[k, col, j] for j, h in enumerate(horizons)},
                     "rf_warning": bool(data.warn[k, col].any()), "trend_warning": bool(data.trend_warn[k, col].any())})
    figure, axes = chart(7.2, 3.6)
    axes.plot(rel, data.truth[lo:hi, col], color=SERIES[0], linewidth=2.2, label="Utilisation (ground truth)", zorder=3)
    score = onset["rf"]
    episode = None
    first_k = None
    eps = [e for e in data.episodes["rf"] if e.link_id == onset["link_id"]]
    if score["detected"]:
        episode = covering_episode(eps, score["episode_start"])
    else:
        later = [e for e in eps if e.start >= times[lo]]
        episode = later[0] if later else None
    if episode is not None:
        first_k = int(round((episode.start - times[0]) / cycle))
        end = episode.end if episode.end is not None else times[hi - 1]
        axes.axvspan((episode.start - onset["time"]) / 60.0, (min(end, times[hi - 1]) - onset["time"]) / 60.0,
                     color=SERIES[1], alpha=0.12, lw=0, label="Alert episode (Random Forest)", zorder=0)
        fx = [(times[first_k] - onset["time"]) / 60.0] + [(times[first_k] - onset["time"]) / 60.0 + h for h in horizons]
        fy = [data.now[first_k, col]] + [float(data.pred[first_k, col, j]) for j in range(len(horizons))]
        axes.plot(fx, fy, color=SERIES[1], linestyle=(0, (5, 3)), linewidth=1.8, marker="o", markersize=3.5,
                  label="Forecast at the first warning", zorder=4)
    threshold_lines(axes)
    axes.axvline(0, color=INK, linewidth=1.0, zorder=2)
    axes.text(0.5, 3, "Onset", color=INK, fontsize=8, ha="left", va="bottom")
    axes.axvline((surge.t0 - onset["time"]) / 60.0, color=MUTED, linewidth=1.0, zorder=2)
    axes.text((surge.t0 - onset["time"]) / 60.0 - 0.5, 3, "Surge starts", color=INK_2, fontsize=8, ha="right",
              va="bottom")
    axes.set_ylim(0, 105)
    axes.set_xlim(rel[0], rel[-1])
    axes.set_xlabel(f"Minutes from onset ({link_name(topo, onset['link_id'])}, surge {surge.id}: "
                    f"{surge.ramp_class} ramp, {surge.zone} {surge.cls} x{surge.multiplier:g}, {surge.start:%a %H:%M} WAT)")
    axes.set_ylabel("Link utilisation (%)")
    legend(axes, ncol=3)
    results.save_chart(figure, "e3_example_event.png")
    info = {"surge": surge.id, "link": link_name(topo, onset["link_id"]), "onset": wat(onset["time"]),
            "rf_detected": score["detected"], "rf_lead_min": score["lead_min"],
            "first_warning_cycle": wat(times[first_k]) if first_k is not None else None}
    return rows, info


def chart_calibration(results: Results, calibration: list[dict]) -> None:
    figure, axes = chart(5.4, 3.6)
    axes.plot([0, 1], [0, 100], color=MUTED, linewidth=1.0, label="Perfect calibration", zorder=1)
    series = (("share_followed_by_onset", "Followed by an onset within the horizon"),
              ("share_reaching_90", "Reached 90 % within the horizon"))
    # the second series is thinner with hollow markers, so both stay visible where they coincide
    styles = ({"linewidth": 2.4, "marker": "o", "markersize": 5},
              {"linewidth": 1.2, "marker": "o", "markersize": 9, "markerfacecolor": "none", "markeredgewidth": 1.4})
    for j, (key, label) in enumerate(series):
        points = [(r["mean_confidence"], 100.0 * r[key]) for r in calibration if r["warnings"]]
        if points:
            xs, ys = zip(*points, strict=True)
            axes.plot(xs, ys, color=SERIES[j], label=label, zorder=3 + j, **styles[j])
    for r in calibration:
        if r["warnings"]:
            axes.text(r["mean_confidence"], -9, f"n={r['warnings']}", ha="center", va="top", fontsize=7, color=INK_2)
    axes.set_xlim(0, 1)
    axes.set_ylim(-16, 105)
    axes.set_yticks([0, 20, 40, 60, 80, 100])
    axes.set_xlabel("Warning confidence (mean of the bin; bins 0-0.4, 0.4-0.6, 0.6-0.8, 0.8-1)")
    axes.set_ylabel("Warnings (%)")
    legend(axes, ncol=1)
    results.save_chart(figure, "e3_calibration.png")


# ------------------------------------------------------------------ main
def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django
    django.setup()


def _r(value, digits: int = 3):
    if isinstance(value, dict):
        return {k: _r(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_r(v, digits) for v in value]
    if isinstance(value, float | np.floating):
        return None if np.isnan(value) else round(float(value), digits)
    return value


def run(args) -> None:
    # scikit-learn's forests warn on every parallel prediction that the joblib workers were not
    # started through its own Parallel; harmless here (no scikit-learn configuration is set)
    warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*", category=UserWarning)
    quick = args.quick
    start_dt = QUICK_START if quick else EXPERIMENT_START
    hours = args.hours or (QUICK_HOURS if quick else EXPERIMENT_HOURS)
    warmup_days = args.warmup_days or (QUICK_WARMUP_DAYS if quick else WARMUP_DAYS)
    if sha256_text(PROTOCOL) != PROTOCOL_SHA256:
        raise SystemExit(f"{PROTOCOL.relative_to(ROOT)} differs from the registered protocol "
                         f"(SHA-256 {sha256_text(PROTOCOL)}, registered {PROTOCOL_SHA256}): E3 does not run on a changed "
                         "protocol. Restore it, or, before the full run only, add an amendment and register its new hash.")
    deviation = None
    if not quick and (hours != EXPERIMENT_HOURS or warmup_days != WARMUP_DAYS):      # amendment 9
        deviation = (f"a {hours:g}-hour experiment with a {warmup_days}-day warm-up, instead of the protocol's "
                     f"{EXPERIMENT_HOURS} hours and {WARMUP_DAYS} days")
    setup_django()
    from django.conf import settings

    from digital_twin.runtime import forecasting

    twin_cfg = settings.TWIN
    cycle = int(twin_cfg["CYCLE_SECONDS"])
    critical = float(twin_cfg["CRITICAL_THRESHOLD_PCT"])
    if critical != ONSET_PCT:
        raise SystemExit(f"the critical threshold is {critical} %, but E3's onset is defined at {ONSET_PCT} %")
    if not quick and warmup_days != forecasting.HISTORY_DAYS:
        log(f"note: warm-up {warmup_days} days differs from the engine's buffer of {forecasting.HISTORY_DAYS} days")
    model_dir = Path(twin_cfg["MODEL_DIR"])
    cycles = int(hours * 3600 // cycle)
    start = start_dt.timestamp()
    end = start + cycles * cycle
    surges = build_schedule(start_dt.date(), 1 if quick else len(LOCATIONS), SLOT_HOURS[:3] if quick else SLOT_HOURS)
    dropped = [s for s in surges if s.window_end > end]
    surges = [s for s in surges if s.window_end <= end]

    topo = e3_topology()
    training_topo = load_topology(CAMPUS)
    templates = {(t.zone, t.cls) for t in training_topo.random_surges.templates}
    assert not any((s.zone, s.cls) in templates for s in surges), "a surge uses a training flash-crowd template"
    link_ids = list(range(1, len(topo.links) + 1))
    world_start = start_dt - timedelta(days=warmup_days)
    net = EmulatedNetwork(topo, world_start, cycle_seconds=cycle, seed=WORLD_SEED, history_cycles=TRUTH_KEEP)
    twin = Twin(topo, net, cycle_seconds=cycle)
    clear_below, clear_cycles = 85.0, 5                     # ForecastService defaults (D22)
    buffer_cycles = forecasting.HISTORY_DAYS * 86400 // cycle + 60
    config = {
        "quick": quick, "seed": WORLD_SEED, "warmup_flash_crowd_seed": FLASH_CROWD_SEED,
        "training_flash_crowd_seed": training_topo.random_surges.seed, "topology": CAMPUS.relative_to(ROOT).as_posix(),
        "topology_sha256": sha256_file(CAMPUS), "reality_gap": "default",
        "world_start": world_start.isoformat(), "warmup_days": warmup_days,
        "experiment_start": start_dt.isoformat(), "experiment_end": datetime.fromtimestamp(end, WAT).isoformat(),
        "experiment_hours": hours, "experiment_cycles": cycles, "cycle_seconds": cycle,
        "ramp_classes_min": dict(RAMP_CLASSES), "hold_min": HOLD_MINUTES, "slots_wat": list(SLOT_HOURS),
        "ladder": list(LADDER), "probe_peak_pct": PROBE_PEAK_PCT, "onset_pct": ONSET_PCT,
        "rearm_below_pct": REARM_BELOW_PCT, "rearm_cycles": REARM_CYCLES,
        "detect_window_min": [DETECT_MIN_MINUTES, DETECT_MAX_MINUTES], "false_alarm_window_min": FALSE_ALARM_MINUTES,
        "attribution_margin_min": ATTRIBUTION_MARGIN_MINUTES, "confidence_bins": list(CONFIDENCE_BINS),
        "critical_pct": critical, "clear_below_pct": clear_below, "clear_cycles": clear_cycles,
        "warning_probability_setting": twin_cfg["WARNING_PROBABILITY"], "history_days": forecasting.HISTORY_DAYS,
        "buffer_cycles": buffer_cycles, "random_faults": net.random_faults,
        "surges_dropped_past_end": [s.id for s in dropped], "code_version": git_commit(),
        "code_sha256": {name: sha256_text(Path(__file__).parent / name)
                        for name in ("e3_early_warning.py", "twin.py", "common.py")},
        "protocol": PROTOCOL.relative_to(ROOT).as_posix(), "protocol_sha256": PROTOCOL_SHA256,
        "deviation_from_plan": deviation,
    }
    results = Results("E3", "Early warning (G2, UC2)", config)
    for stale in results.folder.glob("*"):
        if stale.suffix in (".csv", ".png", ".md", ".json"):
            stale.unlink()

    log(f"warm-up: {warmup_days} days from {world_start:%a %d %b %H:%M} WAT ({warmup_days * 86400 // cycle} cycles)")
    warm = warm_up(twin, warmup_days * 86400 // cycle, link_ids)
    cancelled = switch_off_flash_crowds(net)
    leftovers = surge_list(net)
    config["flash_crowds_cancelled_at_start"] = cancelled
    log(f"experiment starts {net.t.astimezone(WAT):%a %d %b %H:%M} WAT; flash crowds off; leftover: {len(leftovers)}")

    log("planning pass (no forecasts): choosing each surge's multiplier by probing a fork")
    planned_truth = plan(net, surges, cycles, link_ids)
    models = model_manifest(model_dir)
    config.update(models=models, leftover_flash_crowds=leftovers, warmup_cycles=len(warm.times),
                  warmup_congested_cycles=warm.congested_cycles)
    registration = results.folder / "REGISTRATION.md"
    sha = write_registration(registration, quick=quick, config=config, surges=surges, topo=topo, models=models,
                             leftovers=leftovers)
    registered = datetime.now(UTC).isoformat(timespec="seconds")
    config.update(registration_sha256=sha, registered_at=registered)
    # results.json is written only at the end: an interrupted run must not look like a finished one
    results.write_json("registration.json", {"protocol": config["protocol"], "protocol_sha256": PROTOCOL_SHA256,
                                             "registration_sha256": sha, "registered_at": registered,
                                             "quick": quick, "deviation_from_plan": deviation,
                                             "code_sha256": config["code_sha256"]})
    log(f"run registered: REGISTRATION.md SHA-256 {sha}")
    results.write_csv("schedule.csv", [{
        "surge": s.id, "day_time_wat": f"{s.start:%a %d %b %H:%M}", "start_utc": s.start.astimezone(UTC).isoformat(),
        "ramp_class": s.ramp_class, "ramp_min": s.ramp_minutes, "hold_min": s.hold_minutes, "zone": s.zone,
        "traffic_class": s.cls, "multiplier": s.multiplier, "injected": s.injected,
        "probe_peak_pct": s.tries[-1][1] if s.tries else None,
        "probe_link": link_name(topo, s.tries[-1][2]) if s.tries and s.tries[-1][2] else None} for s in surges])
    results.write_csv("probes.csv", [{"surge": s.id, "multiplier": m, "peak_pct": p,
                                      "peak_link": link_name(topo, lk) if lk else None, "chosen": m == s.multiplier}
                                     for s in surges for m, p, lk in s.tries])

    # ---- prediction run
    service = forecasting.ForecastService(twin.model, cycle_seconds=cycle, critical_pct=critical,
                                          warning_probability=twin_cfg["WARNING_PROBABILITY"],
                                          model_dir=str(model_dir), clear_below_pct=clear_below,
                                          clear_cycles=clear_cycles)
    loaded = {kind: m.version for kind, m in service.predictor.models.items()}
    if loaded != {m["kind"]: m["version"] for m in models}:
        raise SystemExit(f"the loaded models {loaded} differ from the protocol")
    if any(m.link_ids != link_ids for m in service.predictor.models.values()):
        raise SystemExit("the models were trained on different link ids")
    for i in range(len(warm.times)):                         # as seed_from_database at start-up
        service.buffer.append(datetime.fromtimestamp(warm.times[i], UTC),
                              dict(zip(link_ids, warm.util[i].tolist(), strict=True)),
                              dict(zip(link_ids, warm.errors[i].tolist(), strict=True)))
    horizons = tuple(service.predictor.models["full"].spec.horizons_minutes)
    log(f"prediction run: {cycles} cycles with {', '.join(loaded.values())}")
    data = run_experiment(twin, service, surges, cycles, start, horizons, link_ids, critical, clear_below, clear_cycles)
    twin.close()
    determinism = float(np.abs(data.truth - planned_truth).max())
    log(f"prediction run done; ground truth vs planning pass: max difference {determinism:.6f} pts")

    # ---- analysis
    analysis = analyse(data, warm.prefix, surges, start, cycle, horizons, link_ids)
    metrics = class_metrics(analysis, data, surges, hours, cycle)
    results.write_csv("metrics_by_class.csv", [_r(r, 4) for r in metrics])
    onset_rows = []
    for o in analysis["onsets"]:
        row = {"onset_wat": wat(o["time"]), "onset_utc": datetime.fromtimestamp(o["time"], UTC).isoformat(),
               "link": link_name(topo, o["link_id"]), "link_id": o["link_id"], "util_pct": o["util_pct"],
               "surge": o["surge"], "ramp_class": o["ramp_class"], "natural": o["natural"],
               "primary": any(p is o for p in analysis["primaries"].values())}
        surge = next((s for s in surges if s.id == o["surge"]), None)
        row["minutes_from_surge_start"] = (o["time"] - surge.t0) / 60.0 if surge else None
        row["most_lead_possible_min"] = (o["time"] - surge.t0 - cycle) / 60.0 if surge else None
        row["fault_in_surge_window"] = o.get("fault_in_surge_window", False)
        for method in METHODS:
            score = o[method]
            row.update({f"{method}_detected": score["detected"], f"{method}_lead_min": score["lead_min"],
                        f"{method}_first_warning_wat": wat(score["first_warning"]),
                        f"{method}_predicted_error_first_min": score["predicted_error_first_min"],
                        f"{method}_predicted_error_last_min": score["predicted_error_last_min"],
                        f"{method}_episode_started_over_35_min_before": score["early_episode"],
                        f"{method}_warning_before_surge_start": score["warning_before_surge"]})
        onset_rows.append(_r(row, 4))
    results.write_csv("onsets.csv", onset_rows, list(onset_rows[0]) if onset_rows else ["onset_wat"])
    surge_rows = []
    for s in surges:
        p = analysis["primaries"].get(s.id)
        k0 = int(round((s.t0 - start) / cycle))
        k1 = int(round((s.peak_end - start) / cycle))
        window = data.truth[k0:k1]
        surge_rows.append(_r({
            "surge": s.id, "day_time_wat": f"{s.start:%a %d %b %H:%M}", "ramp_class": s.ramp_class, "zone": s.zone,
            "traffic_class": s.cls, "multiplier": s.multiplier, "injected": s.injected,
            "run_peak_pct": float(window.max()) if len(window) else None,
            "run_peak_link": link_name(topo, link_ids[int(window.max(axis=0).argmax())]) if len(window) else None,
            "onset_links": "; ".join(link_name(topo, o["link_id"]) for o in analysis["onsets"] if o["surge"] == s.id),
            "primary_onset_wat": wat(p["time"]) if p else None,
            "primary_link": link_name(topo, p["link_id"]) if p else None,
            "minutes_surge_start_to_onset": (p["time"] - s.t0) / 60.0 if p else None,
            "most_lead_possible_min": (p["time"] - s.t0 - cycle) / 60.0 if p else None,
            "fault_in_surge_window": p.get("fault_in_surge_window", False) if p else None,
            "rf_detected": p["rf"]["detected"] if p else None, "rf_lead_min": p["rf"]["lead_min"] if p else None,
            "rf_predicted_error_first_min": p["rf"]["predicted_error_first_min"] if p else None,
            "trend_detected": p["trend"]["detected"] if p else None,
            "trend_lead_min": p["trend"]["lead_min"] if p else None}, 4))
    results.write_csv("surges.csv", surge_rows)
    episode_rows = [_r({"method": e.method, "link": link_name(topo, e.link_id), "link_id": e.link_id,
                        "start_wat": wat(e.start), "end_wat": wat(e.end),
                        "duration_min": (e.end - e.start) / 60.0 if e.end else None,
                        "category": e.category, "surge_window": e.surge, "ramp_class": e.ramp_class,
                        "first_horizon_min": e.horizon, "first_confidence": e.confidence,
                        "critical_now_at_start": e.critical_now,
                        "predicted_problem_wat": wat(e.predicted)}, 4)
                    for method in METHODS for e in data.episodes[method]]
    results.write_csv("episodes.csv", episode_rows, list(episode_rows[0]) if episode_rows else ["method"])
    calibration_rows = [{"group": h if h.startswith("class:") or h == "all" else f"horizon {h} min", **_r(r, 4)}
                        for h, table in analysis["calibration"].items() for r in table]
    results.write_csv("calibration.csv", calibration_rows)
    results.write_csv("faults.csv", data.faults or [], ["seq", "time", "type", "element", "detail"])
    results.write_csv("lead_time_by_class.csv", [_r(r, 4) for r in chart_lead_times(results, analysis, surges, cycle)])
    results.write_csv("detection_rate_by_class.csv", [_r(r, 4) for r in chart_detection(results, metrics)])
    example_rows, example_info = chart_example(results, analysis, data, surges, horizons, topo, cycle)
    results.write_csv("example_event_timeline.csv", [_r(r, 4) for r in example_rows],
                      list(example_rows[0]) if example_rows else ["minutes_from_onset"])
    chart_calibration(results, analysis["calibration"]["all"])

    # ---- summary
    def pick(method: str, cls: str) -> dict:
        return next(r for r in metrics if r["method"] == method and r["ramp_class"] == cls)

    rf_all, trend_all = pick("rf", "all"), pick("trend", "all")
    median_lead = rf_all["lead_median_min"]
    natural = [o for o in analysis["onsets"] if o["natural"]]
    protocol_unchanged = sha256_text(PROTOCOL) == PROTOCOL_SHA256
    registration_unchanged = sha256_file(registration) == sha
    active_unchanged = [m["version"] for m in model_manifest(model_dir)] == [m["version"] for m in models]
    valid = protocol_unchanged and registration_unchanged and active_unchanged and determinism == 0.0
    days = {}
    for method in METHODS:                                     # amendment 8: per day (WAT)
        for e in data.episodes[method]:
            if e.category in ("false", "late"):
                day = datetime.fromtimestamp(e.start, UTC).astimezone(WAT).strftime("%a %d %b")
                days.setdefault(method, {}).setdefault(day, 0)
                days[method][day] += 1
    results.summary = {
        "target": f"median lead time >= {TARGET_LEAD_MINUTES:g} min (Random Forest, detected primary onsets, all classes)",
        "median_lead_min": _r(median_lead),
        "target_met": bool(valid and median_lead is not None and median_lead >= TARGET_LEAD_MINUTES),
        "run_valid": valid, "deviation_from_plan": deviation,
        "median_lead_without_flagged_min": _r(rf_all["lead_median_without_flagged_min"]),
        "detected_with_episode_started_over_35_min_before": rf_all["detected_with_episode_started_over_35_min_before"],
        "detected_with_warning_before_surge_start": rf_all["detected_with_warning_before_surge_start"],
        "most_lead_possible_median_min": _r(rf_all["most_lead_possible_median_min"]),
        "detection_rate": _r(rf_all["detection_rate"]), "detected": rf_all["detected"],
        "surges_with_onset": rf_all["surges_with_onset"], "surges_injected": rf_all["surges_injected"],
        "surges_not_congesting": rf_all["surges_not_congesting"],
        "median_lead_misses_as_0_min": _r(rf_all["lead_median_misses_as_0_min"]),
        "by_class": {cls: {"surge_start_to_onset_median_min": _r(pick("rf", cls)["surge_start_to_onset_median_min"]),
                           "most_lead_possible_median_min": _r(pick("rf", cls)["most_lead_possible_median_min"]),
                           **{m: {k: _r(pick(m, cls)[k]) for k in ("detected", "surges_with_onset", "detection_rate",
                                                                    "lead_median_min", "lead_p10_min",
                                                                    "lead_median_without_flagged_min", "false_alarms",
                                                                    "false_alarms_per_episode", "late_alarms",
                                                                    "detected_with_episode_started_over_35_min_before",
                                                                    "detected_with_warning_before_surge_start",
                                                                    "predicted_time_error_first_median_min")}
                              for m in METHODS}} for cls in ("slow", "medium", "fast")},
        "surge_start_to_onset_median_min": _r(rf_all["surge_start_to_onset_median_min"]),
        "false_alarms": {m: {"definition": "plan: an episode with no onset on its link within 35 min (late alarms included)",
                             "count": pick(m, "all")["false_alarms"], "per_day": _r(pick(m, "all")["false_alarms_per_day"]),
                             "per_episode": _r(pick(m, "all")["false_alarms_per_episode"]),
                             "episodes_scored": pick(m, "all")["episodes"], "late_alarms": pick(m, "all")["late_alarms"],
                             "excluding_late": pick(m, "all")["false_alarms_excluding_late"],
                             "outside_surges": pick(m, "all")["false_alarms_outside_surges"],
                             "by_day": days.get(m, {})} for m in METHODS},
        "injected_onsets_with_fault_in_window": rf_all["injected_onsets_with_fault_in_window"],
        "predicted_time_error_first_median_min": _r(rf_all["predicted_time_error_first_median_min"]),
        "predicted_time_abs_error_first_median_min": _r(rf_all["predicted_time_abs_error_first_median_min"]),
        "trend_alarm": {k: _r(trend_all[k]) for k in ("detected", "detection_rate", "lead_median_min", "lead_p10_min",
                                                      "false_alarms", "false_alarms_per_day")},
        "calibration_all_horizons": analysis["calibration"]["all"],
        "calibration_by_class": {k.split(":", 1)[1]: v for k, v in analysis["calibration"].items() if k.startswith("class:")},
        "calibration_warnings": analysis["calibration_warnings"],
        "calibration_excluded_critical_now": analysis["calibration_excluded_critical_now"],
        "all_injected_onsets": {"count": rf_all["all_injected_onsets"], "rf_detected": rf_all["all_injected_onsets_detected"],
                                "trend_detected": trend_all["all_injected_onsets_detected"]},
        "natural_onsets": {"count": len(natural), "rf_detected": sum(o["rf"]["detected"] for o in natural),
                           "trend_detected": sum(o["trend"]["detected"] for o in natural),
                           "rf_leads_min": [_r(o["rf"]["lead_min"]) for o in natural if o["rf"]["detected"]]},
        "faults_during_experiment": len(data.faults),
        "example_event": example_info,
        "determinism_max_difference_pts": determinism, "determinism_passed": determinism == 0.0,
        "protocol_sha256": PROTOCOL_SHA256, "protocol_unchanged": protocol_unchanged,
        "registration_sha256": sha, "registration_unchanged": registration_unchanged, "registered_at": registered,
        "first_prediction_at": data.first_prediction_at, "active_models_unchanged": active_unchanged,
        "models_served_cycles": data.model_cycles, "missing_polls": data.missing_polls,
        "forecast_ms_median": _r(statistics.median(data.predict_ms)) if data.predict_ms else None,
        "warmup_congested_cycles": warm.congested_cycles,
    }
    path = results.finish()
    log(f"wrote {path}")
    print(f"median lead {median_lead} min (target {TARGET_LEAD_MINUTES:g}): met {results.summary['target_met']}; "
          f"detected {rf_all['detected']}/{rf_all['surges_with_onset']} surges (trend {trend_all['detected']}); "
          f"false alarms RF {rf_all['false_alarms']}, trend {trend_all['false_alarms']}; "
          f"natural onsets {len(natural)}; determinism passed {determinism == 0.0}")


# ------------------------------------------------------------------ self-test
def _selftest() -> None:
    # onsets: two consecutive cycles >= 90 after 5 below 85; a single spike does not count
    u = np.array([[50, 50, 50, 50, 50, 91, 60, 92, 93, 95, 88, 86, 92, 92, 80, 80, 80, 80, 80, 91, 91]], float).T
    onsets, congested = find_onsets(u)
    assert onsets == [(7, 0), (19, 0)], onsets          # 12-13 is not a new onset: the link never re-armed
    assert congested[7:14, 0].all() and not congested[18, 0] and not congested[6, 0]
    assert find_onsets(np.array([[88, 92, 93, 94]], float).T)[0] == []           # never armed
    assert find_onsets(np.array([[80, 80, 80, 80, 92, 93]], float).T)[0] == []   # only 4 calm cycles
    assert find_onsets(np.array([[80] * 5 + [92]], float).T)[0] == []            # unconfirmed at the end

    # detection window 1-35 min, lead from the covering episode, predicted-time errors
    onset = 10_000.0
    ep = EpisodeRec("rf", 1, onset - 12 * 60, None, onset - 2 * 60, 10, 0.7, False)
    warn = np.array([onset - 12 * 60, onset - 11 * 60, onset - 60])
    s = score_onset(onset, warn, [ep], {onset - 60: 5})
    assert s["detected"] and s["lead_min"] == 12.0 and s["predicted_error_first_min"] == -2.0
    assert s["predicted_error_last_min"] == 4.0 and not s["early_episode"]
    assert not score_onset(onset, np.array([onset]), [ep])["detected"]                 # 0 min: too late
    assert not score_onset(onset, np.array([onset - 36 * 60]), [ep])["detected"]       # too early
    old = EpisodeRec("rf", 1, onset - 50 * 60, None, onset, 30, 0.5, False)
    s = score_onset(onset, np.array([onset - 50 * 60, onset - 20 * 60]), [old])
    assert s["detected"] and s["lead_min"] == 50.0 and s["early_episode"]

    # episode categories
    onsets_t = np.array([onset])
    assert classify_episode(ep, onsets_t, False, 1e9) == "true"
    assert classify_episode(old, onsets_t, False, 1e9) == "false"                      # 50 min before the onset
    assert classify_episode(EpisodeRec("rf", 1, onset + 120, None, 0, 5, 1, True), onsets_t, True, 1e9) == "late"
    assert classify_episode(EpisodeRec("rf", 1, onset + 120, None, 0, 5, 1, False), onsets_t, False,
                            onset + 600) == "unscored"
    assert classify_episode(EpisodeRec("rf", 1, onset, None, 0, 5, 1, True), onsets_t, True, 1e9) == "true"
    assert sha256_text(PROTOCOL) == PROTOCOL_SHA256, "the protocol file differs from the registered hash"

    # reliability bins: the top bin includes 1.0
    table = reliability(np.array([0.3, 0.5, 0.55, 0.9, 1.0]), np.array([0, 1, 0, 1, 1], bool),
                        np.array([1, 1, 0, 1, 1], bool))
    assert [r["warnings"] for r in table] == [1, 2, 0, 2]
    assert table[1]["share_followed_by_onset"] == 0.5 and table[3]["share_reaching_90"] == 1.0
    assert lead_summary([4.0, 8.0, 12.0])["median"] == 8.0 and lead_summary([])["median"] is None

    # trend alarm: a straight line rising 2 points a cycle projects 10 points ahead at +5 min
    spec = FeatureSpec(60, (5, 10, 15, 30), full=False)
    rows = TREND_TAIL + 10
    times = 1_800_000_000 + 60.0 * np.arange(rows)
    line = (20.0 + 0.5 * np.arange(rows))[:, None].astype(np.float32)
    projection, now = trend_projection(times, line, np.zeros_like(line), np.zeros((1, 6), np.float32), spec)
    assert abs(now[0] - line[-1, 0]) < 1e-4 and abs(projection[0, 0] - (line[-1, 0] + 2.5)) < 1e-3, projection

    # schedule: 6 per class, each class once per slot, starts 3 h apart, no training template
    surges = build_schedule(EXPERIMENT_START.date(), len(LOCATIONS))
    assert len(surges) == 18
    for name, _ in RAMP_CLASSES:
        mine = [s for s in surges if s.ramp_class == name]
        assert len(mine) == 6 and sorted(s.start.hour for s in mine) == sorted(SLOT_HOURS)
    starts = sorted(s.t0 for s in surges)
    assert min(np.diff(starts)) >= 3 * 3600 and surges[0].start.weekday() == 0
    assert all(s.window_end <= EXPERIMENT_START.timestamp() + EXPERIMENT_HOURS * 3600 for s in surges)
    templates = {(t.zone, t.cls) for t in load_topology(CAMPUS).random_surges.templates}
    assert not any((s.zone, s.cls) in templates for s in surges)
    quick = build_schedule(QUICK_START.date(), 1, SLOT_HOURS[:3])
    assert [s.ramp_class for s in quick] == ["slow", "medium", "fast"]

    # a fork stays identical to the original (same random demand and faults), with and without a surge
    topo = e3_topology()
    net = EmulatedNetwork(topo, EXPERIMENT_START + timedelta(hours=11), seed=WORLD_SEED, history_cycles=TRUTH_KEEP)
    fork = copy.deepcopy(net)
    for n in (net, fork):
        n.add_surge("ICT", "web", 4.0, 2, 2, 0.0)
    a = [emulator_cycle(net) for _ in range(4)]
    b = [emulator_cycle(fork) for _ in range(4)]
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))

    # switching flash crowds off removes the day's flash crowds that have not started, and draws no more
    net = EmulatedNetwork(topo, datetime(2026, 11, 1, 23, 59, tzinfo=WAT), seed=WORLD_SEED, history_cycles=TRUTH_KEEP)
    emulator_cycle(net)                                    # the step onto Monday 00:00 draws Monday's flash crowds
    assert net.t == datetime(2026, 11, 2, 0, 0, tzinfo=WAT)
    assert sum(s.start.astimezone(WAT).day == 2 for s in net.traffic.surges) == topo.random_surges.per_day
    cancelled = switch_off_flash_crowds(net)
    assert len(cancelled) == topo.random_surges.per_day and all(s.start <= net.t for s in net.traffic.surges)
    net.traffic.offered(datetime(2026, 11, 3, 0, 0, 10, tzinfo=WAT), 10.0)     # Tuesday: nothing new is drawn
    assert all(s.start <= net.t for s in net.traffic.surges)
    print("selftest passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="pipeline check (about 5-12 minutes), not for Chapter 4")
    parser.add_argument("--hours", type=float, default=None, help="experiment length (default 78, quick 9)")
    parser.add_argument("--warmup-days", type=int, default=None, help="warm-up before the experiment (default 7, quick 2)")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return
    run(args)


if __name__ == "__main__":
    main()
