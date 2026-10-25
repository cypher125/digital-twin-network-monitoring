# E3 Early warning: run registration

**Full run, as the protocol sets it.**

Registered 2026-10-25T20:34:53+00:00 (wall clock), before any prediction of this run. The protocol is docs/evaluation/E3_PROTOCOL.md (SHA-256 3bcc5537a4bfcc93cb199ba6516b7b05dd6e242666eb2240484cbe0b4fd73584); its definitions, target and reporting rules apply unchanged. Code version 8651550+uncommitted; code SHA-256: e3_early_warning.py d12f4e97008d40b3..., twin.py 9782682562916b42..., common.py 534ab8f6d0e7a2e1.... The SHA-256 of this file is stored in registration.json and results.json.

## World

- Topology data/topologies/campus.yaml (SHA-256 a70d07bca35b5d87...), reality gap preset "default"; random link/device failures on; data-quality faults on.
- Emulator seed 2026 (training history: 7). Warm-up flash crowds drawn with seed 2026 (training: 11).
- World starts 2026-10-26T00:00:00+01:00; warm-up of 7 days with normal behaviour (flash crowds on), every cycle through the twin's ingest path into the history buffer; no forecasts during the warm-up.
- Experiment 2026-11-02T00:00:00+01:00 to 2026-11-05T06:00:00+01:00 (78 h, 4680 cycles). Random flash crowds switched off at the start: no new ones are drawn (the lab switch), and those already drawn for the day that had not started yet are removed: HOSTEL/video x2.185 at 2026-11-02T20:48+01:00; HOSTEL/web x1.766 at 2026-11-02T21:31+01:00; SOT/web x2.069 at 2026-11-02T15:31+01:00; HOSTEL/video x1.709 at 2026-11-02T21:37+01:00.
- Flash crowds already running at the experiment start (they run to their end; their onsets count as natural): HOSTEL/video x1.797 2026-11-01T23:08+01:00 to 2026-11-02T00:49+01:00
- Training flash-crowd templates (zone/class, weight): HOSTEL/video (4), HOSTEL/web (1), SOT/web (1), SCI/video (1), ENG/web (1), LIB/video (1).

## Models (var/models/active.json, served as runtime/forecasting.py ForecastService)

- full: rf-full-20261019T014146984670Z (with same-time-yesterday), warning threshold 0.2, model.joblib SHA-256 f9523d33b1132faa..., training window 2026-10-15T01:33:00+00:00 to 2026-10-28T01:03:00+00:00.
- short: rf-short-20261019T015325555480Z (short history), warning threshold 0.25, model.joblib SHA-256 0087f048910a045d..., training window 2026-10-14T02:33:00+00:00 to 2026-10-28T01:02:00+00:00.
- Choice as in the engine: the full model once the buffer holds more than one day, else the short model. History buffer 10140 cycles (HISTORY_DAYS = 7). Critical threshold 90 %, alert hysteresis: clear below 85 % for 5 cycles.

## Injection schedule

Ramp classes: slow 30 min, medium 15 min, fast 5 min; hold 30 min; ramp-down as the ramp-up. Multiplier: the smallest of 1.5, 2, 3, 4, 6, 8, 12, 16, 24 that takes some link to >= 95 % within ramp + hold in a fork of the world (planning pass, no forecasts). A surge with no such multiplier is not injected and is kept out of the detection statistics.

| Surge | Time (WAT) | Ramp class | Zone / class | Multiplier | Probe peak | Link | Tried (multiplier: peak %) |
|---|---|---|---|---|---|---|---|
| S01 | Mon 02 Nov 08:00 | slow (30 min) | SOT / video | x4 | 97.512 | ISP-B-GW - EDGE-RTR-01 | 1.5: 78.1, 2: 82.0, 3: 89.8, 4: 97.5 |
| S02 | Mon 02 Nov 11:00 | medium (15 min) | ICT / web | x8 | 99.972 | ISP-B-GW - EDGE-RTR-01 | 1.5: 81.1, 2: 82.6, 3: 85.6, 4: 88.5, 6: 94.4, 8: 100.0 |
| S03 | Mon 02 Nov 14:00 | fast (5 min) | SCI / web | x4 | 96.768 | ISP-B-GW - EDGE-RTR-01 | 1.5: 78.6, 2: 81.8, 3: 89.2, 4: 96.8 |
| S04 | Mon 02 Nov 17:00 | slow (30 min) | LIB / web | x12 | 100.0 | ISP-B-GW - EDGE-RTR-01 | 1.5: 59.6, 2: 59.7, 3: 61.9, 4: 66.1, 6: 75.1, 8: 84.2, 12: 100.0 |
| S05 | Mon 02 Nov 20:00 | medium (15 min) | HOSTEL / elearning | x8 | 96.757 | DIST-HOSTEL - AP-HOSTEL-02 | 1.5: 72.4, 2: 74.2, 3: 78.0, 4: 81.7, 6: 89.2, 8: 96.8 |
| S06 | Mon 02 Nov 23:00 | fast (5 min) | HOSTEL / portal | x12 | 100.0 | DIST-HOSTEL - AP-HOSTEL-01 | 1.5: 72.6, 2: 73.2, 3: 74.3, 4: 76.1, 6: 82.8, 8: 90.1, 12: 100.0 |
| S07 | Tue 03 Nov 08:00 | medium (15 min) | SCI / web | x6 | 100.0 | ISP-B-GW - EDGE-RTR-01 | 1.5: 72.4, 2: 76.0, 3: 83.3, 4: 90.6, 6: 100.0 |
| S08 | Tue 03 Nov 11:00 | fast (5 min) | ENG / video | x4 | 95.821 | ISP-B-GW - EDGE-RTR-01 | 1.5: 81.9, 2: 84.7, 3: 90.2, 4: 95.8 |
| S09 | Tue 03 Nov 14:00 | slow (30 min) | ICT / video | x12 | 100.0 | ISP-B-GW - EDGE-RTR-01 | 1.5: 74.0, 2: 74.6, 3: 76.4, 4: 79.1, 6: 84.4, 8: 89.8, 12: 100.0 |
| S10 | Tue 03 Nov 17:00 | medium (15 min) | SOT / video | x16 | 95.76 | ISP-B-GW - EDGE-RTR-01 | 1.5: 58.6, 2: 59.9, 3: 62.4, 4: 65.0, 6: 70.1, 8: 75.2, 12: 85.5, 16: 95.8 |
| S11 | Tue 03 Nov 20:00 | fast (5 min) | HOSTEL / portal | x12 | 100.0 | DIST-HOSTEL - AP-HOSTEL-01 | 1.5: 68.8, 2: 70.6, 3: 74.4, 4: 78.1, 6: 85.6, 8: 93.4, 12: 100.0 |
| S12 | Tue 03 Nov 23:00 | slow (30 min) | HOSTEL / elearning | x16 | 100.0 | DIST-HOSTEL - AP-HOSTEL-02 | 1.5: 71.9, 2: 72.0, 3: 72.3, 4: 72.6, 6: 75.0, 8: 79.9, 12: 93.4, 16: 100.0 |
| S13 | Wed 04 Nov 08:00 | fast (5 min) | ENG / video | x8 | 95.326 | ISP-B-GW - EDGE-RTR-01 | 1.5: 66.5, 2: 68.7, 3: 73.1, 4: 77.6, 6: 86.5, 8: 95.3 |
| S14 | Wed 04 Nov 11:00 | slow (30 min) | ADMIN / web | x8 | 95.072 | ISP-B-GW - EDGE-RTR-01 | 1.5: 79.8, 2: 81.0, 3: 83.4, 4: 85.7, 6: 90.4, 8: 95.1 |
| S15 | Wed 04 Nov 14:00 | medium (15 min) | SOT / video | x6 | 100.0 | ISP-B-GW - EDGE-RTR-01 | 1.5: 77.0, 2: 80.4, 3: 87.3, 4: 94.1, 6: 100.0 |
| S16 | Wed 04 Nov 17:00 | fast (5 min) | SCI / web | x16 | 100.0 | ISP-B-GW - EDGE-RTR-01 | 1.5: 60.0, 2: 61.6, 3: 64.9, 4: 68.2, 6: 74.9, 8: 81.5, 12: 94.7, 16: 100.0 |
| S17 | Wed 04 Nov 20:00 | slow (30 min) | HOSTEL / elearning | x8 | 97.335 | DIST-HOSTEL - AP-HOSTEL-02 | 1.5: 75.4, 2: 77.0, 3: 80.4, 4: 83.8, 6: 90.5, 8: 97.3 |
| S18 | Wed 04 Nov 23:00 | medium (15 min) | HOSTEL / portal | x12 | 98.907 | DIST-HOSTEL - AP-HOSTEL-01 | 1.5: 71.0, 2: 71.0, 3: 71.3, 4: 72.3, 6: 78.5, 8: 85.4, 12: 98.9 |

## Definitions (as in the protocol)

- **Onset**: the first of two consecutive ground-truth cycles at or above 90 % on a link, after at least 5 consecutive cycles below 85 % on that link. Onset time = the end of that cycle. The detector's state at the start comes from the last 60 warm-up cycles.
- **Detected**: a warning (any horizon) on that link at a cycle 1-35 min before the onset.
- **Lead time**: onset time minus the first warning of the episode containing the last warning in that window (flagged when that episode started more than 35 min before the onset).
- **False alarm** (the plan's definition, the headline figure): an alert episode with no onset on its link from its start to 35 min after it. Episodes that start while the link is still congested are also shown separately as **late alarms**. Episodes whose 35-minute window runs past the end are unscored.
- **Attribution**: an onset belongs to a surge if its time is within [start, start + ramp + hold + 10 min] of an injected surge; all other onsets are **natural** and reported separately (also those in the window of a surge that was not injected).
- **Unit**: each injected surge's first onset (ties: higher utilisation, then lower link id); all injected onsets as a secondary view.
- **Predicted problem time error**: Episode.predicted_time - onset (min), at the episode's first warning and at the last warning before the onset.
- **Most lead possible** (context, not a criterion): the onset minus (the surge's start + one cycle), the first reading that contains the surge.
- **Per-class false alarms**: false-alarm episodes starting in [surge start, end of ramp-down + 10 min]; the rest are outside surges. Totals per day and per episode.
- **Calibration**: Random Forest warnings on links below 90 % now, by confidence bin (0-0.4, 0.4-0.6, 0.6-0.8, 0.8-1), against the share followed by an onset on that link within the warning's horizon (and the share reaching 90 %); for all warnings, per horizon and per ramp class.
- **Comparison**: the linear-trend alarm (15-cycle slope projected to each horizon reaches 90 %) on the same buffer, with its own AlertTracker of the same settings, scored the same way.

## Target

Median lead time >= 10 min: Random Forest, detected primary onsets of injected surges, all ramp classes together. Reported with the detection rate and with misses counted as 0 min.

## Example event chart

The first medium-ramp surge in time order with an onset (otherwise the first surge with an onset).
