# E3 Early warning: pre-registered protocol

This protocol fixes E3's definitions, thresholds, injection rule, target and reporting rules before the full run. The module `backend/evaluation/e3_early_warning.py` checks this file's SHA-256 at start-up and refuses to run if the file has changed. The SHA-256 is taken over the text with line endings normalised to LF. Each run then writes its own registration (`results/E3/REGISTRATION.md`) before the first prediction. The registration holds the chosen surge sizes, the model versions and hashes, and the flash crowds cancelled at the start. The hashes of both files are recorded in `results.json`.

The protocol follows the plan (`docs/PROJECT_PLAN.md` §11, E3). Where the plan is silent or ambiguous, the rule chosen is listed under **Amendments before the full run** at the end.

## Question

Are problems flagged before they reach critical levels (Abstract, gap G2, UC2)?

## World

- **Network:** the emulated campus `data/topologies/campus.yaml`, with reality-gap preset "default". Random link and device failures and data-quality faults stay on, as in normal operation.
- **Seeds:** the emulator uses seed 2026 (the training history used 7). Warm-up flash crowds are drawn with seed 2026 (training used campus.yaml's seed 11).
- **Warm-up:**
  - The world starts 7 days before the experiment, matching the engine's 7-day history buffer, `runtime/forecasting.py` HISTORY_DAYS.
  - It runs a warm-up week of normal behaviour, with flash crowds on.
  - Every cycle passes through the twin's own ingest path into the history buffer: `evaluation/twin.py`, the production adapter, preprocessing and network model.
  - No forecast is made during the warm-up.
- **Experiment window:** Monday 2 November 2026, 00:00 WAT, to Thursday 5 November 2026, 06:00 WAT, 78 hours. This is after the models' training window (network time 14–28 October 2026).
- **Flash crowds at the start:**
  - Random flash crowds are switched off: none are drawn for later days.
  - Those already drawn for Monday that have not started are removed.
  - One already in progress runs to its end, and its onsets are natural.

## Models

- The ACTIVE models in `var/models` are served exactly as the Digital Twin Engine serves them (`runtime/forecasting.py` ForecastService, with only its database write removed).
- Model choice: the full model once the buffer holds more than one day of history.
- Warning rule: the classification forest, with the threshold chosen at training time.
- Confidence: as the engine computes it.
- Alert episodes: the engine's AlertTracker. An episode starts at the first warning on a link. It ends after 5 consecutive cycles in which every horizon and the current utilisation are below 85 %.
- **Comparison method:** the linear-trend alarm. The 15-cycle least-squares slope from the same buffer and feature function is continued to each horizon (`models.baseline_predictions` "linear_trend"). It warns when the projection reaches 90 % at any horizon, and it has its own AlertTracker with the same settings.

## Injected surges

- **Ramp classes:** slow (demand ramps up over 30 min), medium (15 min) and fast (5 min). Each surge holds its peak for 30 minutes, then ramps down at the same rate.
- **Times:** 18 surges, 6 per class, at 08:00, 11:00, 14:00, 17:00, 20:00 and 23:00 WAT, Monday to Wednesday. The class is (slot + day) mod 3, so each class meets each time of day exactly once.
- **Locations:** zones and traffic classes that never had a flash crowd in training.

  | Day | 08:00 | 11:00 | 14:00 | 17:00 | 20:00 | 23:00 |
  |---|---|---|---|---|---|---|
  | Monday | SOT video | ICT web | SCI web | LIB web | HOSTEL e-learning | HOSTEL portal |
  | Tuesday | SCI web | ENG video | ICT video | SOT video | HOSTEL portal | HOSTEL e-learning |
  | Wednesday | ENG video | ADMIN web | SOT video | SCI web | HOSTEL e-learning | HOSTEL portal |

  No surge is placed between 01:00 and 07:00. In those hours only hostel video, which was a training flash crowd, can congest a link. Those hours still count for false alarms.
- **Size:**
  - A surge multiplies the zone's demand for the traffic class.
  - The multiplier is the smallest value on the ladder 1.5, 2, 3, 4, 6, 8, 12, 16, 24 for which some link reaches 95 % or more (ground truth, one-minute average) within ramp + hold minutes, in a fork of the world taken at the surge's start.
  - The fork is a deep copy, so it has the same random demand and faults.
  - A surge with no such multiplier is not injected, and is reported.
  - The multipliers are chosen in a planning pass with no forecasting. The prediction run replays the same world with them, and its ground truth must equal the planning pass's exactly. This determinism check is reported.

## Definitions

- **Onset:** the first of two consecutive ground-truth cycles at or above 90 % on a link, after at least 5 consecutive cycles below 85 % on that link. The onset time is the end of that cycle. The detector's state at the start comes from the last 60 warm-up cycles.
- **Detected:** the method warned on that link (any horizon) at a cycle 1 to 35 minutes before the onset.
- **Lead time:** the onset time minus the first warning of the alert episode that contains the last warning in the 1–35 minute window.
- **False alarm (the plan's definition, the headline figure):** an alert episode with no onset on its link from its start to 35 minutes after its start.
- **Attribution:** an onset belongs to an injected surge when its time lies between the surge's start and start + ramp + hold + 10 minutes. Every other onset is natural and is reported separately.
- **Unit:** each injected surge's first onset is scored. Ties go to the link with the higher utilisation, then the lower link id. All injected onsets are also scored, as a secondary view.
- **Predicted problem time error:** the episode's predicted problem time (generated_at + the earliest warning horizon) minus the onset time, in minutes. It is taken at the episode's first warning, and at the last warning before the onset.
- **Per-class false alarms:** false-alarm episodes that start between a surge's start and the end of its ramp-down + 10 minutes count against that surge's class. The rest are "outside surges". Totals are given per day and per episode.
- **Calibration:**
  - Covers every Random Forest warning on a link below 90 % now, which are the classifier's warnings.
  - Warnings are binned by confidence: 0–0.4, 0.4–0.6, 0.6–0.8 and 0.8–1.0.
  - Each bin is compared with the share followed by an onset on that link within the warning's horizon. The share that merely reached 90 % within the horizon is shown beside it.
  - Reported for all warnings, per horizon and per ramp class.

## Target

A median lead time of 10 minutes or more: the median over the detected primary onsets of all injected surges, all ramp classes together, for the Random Forest. The detection rate is reported beside it, and so is the median with every miss counted as 0 minutes.

The run is valid only if all four of these hold:
- this protocol is unchanged;
- the run's registration is unchanged;
- the active models are unchanged;
- the determinism check passes.

An invalid run does not meet the target.

## Example event chart

By a rule fixed in advance, the chart shows the first medium-ramp surge in time order that has an onset. If none has, it shows the first surge with an onset.

## Quick mode

`--quick` is a pipeline check, not for Chapter 4:
- 2 days of warm-up;
- a 9-hour experiment, Monday 07:00 to 16:00 WAT;
- one surge per class: 08:00 slow, 11:00 medium, 14:00 fast.

## Amendments before the full run

These were fixed after the first quick runs (pipeline checks) and before the full run, on 23 October 2026. None was chosen by looking at a lead time, detection rate or false-alarm figure.

1. **Re-arming.** The plan does not say when a link can have a new onset. A link must have 5 consecutive cycles below 85 % (the alert hysteresis level) before it can have another onset, so one congestion counts as one onset.
2. **Late alarms.** An episode that starts while its link is still congested (after an onset, before re-arming) warns about a problem already under way. Under the plan's definition it is a false alarm, and the headline false-alarm figures count it as one. It is also reported separately as a "late alarm", and false alarms without the late ones are given as context.
3. **Lead from the covering episode.** The lead time is taken from the episode that covers the last warning in the 1–35 minute window, so it can exceed 35 minutes. Such cases are flagged and counted. The median without the flagged leads is reported beside the target median, which stays as defined.
4. **Unscored episodes.** Episodes that start less than 36 minutes before the end of the run cannot be scored. They are reported as unscored and kept out of the false-alarm counts.
5. **The most lead possible.** A surge is added at the start of the cycle that begins at its start time, so the first reading that contains it is one cycle later. The most lead a method can have from the surge itself is therefore the onset time minus (the surge start + 1 cycle). It is reported per surge and class, and drawn on the lead-time chart. A detection whose episode started at or before the surge's start is flagged as "before the surge".
6. **Per-class calibration.** Calibration is also reported per ramp class. These are warnings at cycles inside each class's surge windows (start to the end of the ramp-down + 10 minutes), plus an "outside surges" group, with the warning count in each bin.
7. **Faults inside surge windows.** Onsets are attributed by time alone. An onset whose surge window also contains a random link or device failure is flagged, and the number of such onsets is reported.
8. **Daily repetition.** The surge times repeat every day. So from Tuesday on, the full model's same-time-yesterday features contain the previous day's injected surge. False alarms are therefore reported per day (Monday separately from Tuesday and Wednesday).
9. **Reduced runs.** A full-mode run with a shorter experiment or warm-up than set above is recorded as a deviation from this protocol, in the registration and in `results.json`.
10. **Registration.** The run-specific registration (multipliers tried and chosen, model versions and file hashes, cancelled and leftover flash crowds, code hashes) is written to `results/E3/REGISTRATION.md` and hashed before the first prediction.
