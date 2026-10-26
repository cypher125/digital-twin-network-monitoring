# As-built notes

This is the running record of where the software extends, refines or differs from the design in Chapter 3. Chapter 4 should describe the system as built, so each note says what Chapter 3 says, what was built, and why. Decision numbers (D1–D28) refer to `docs/PROJECT_PLAN.md`.

*Last updated: 19 October 2026. The second design review's fixes and the later code and dashboard review fixes are included.*

---

## 1. Database (§3.5, Figure 3.3, Tables 3.2–3.3)

**Six application tables, as designed.**

| Chapter 3 entity | Django model | Database table |
|---|---|---|
| NetworkDevice | `NetworkDevice` | `network_device` |
| NetworkLink | `NetworkLink` | `network_link` |
| MonitoringRecord | `MonitoringRecord` | `monitoring_record` |
| Prediction | `Prediction` | `prediction` |
| SimulationScenario | `SimulationScenario` | `simulation_scenario` |
| SimulationResult | `SimulationResult` | `simulation_result` |

All principal fields of Table 3.2 exist with the same names. The foreign-key column of SimulationScenario is literally `created_by`, as in Figure 3.3.

**Extra (non-principal) fields.** Table 3.2 lists "principal fields", so additions are allowed:

| Table | Field | Why |
|---|---|---|
| NetworkDevice | `configuration` (JSON) | FR1 requires "configuration for nodes". It holds the role, zone, diagram position and internet-egress flag, with room for ACL and QoS settings. |
| NetworkLink | `routing_cost` | The routing-change scenario and the twin's routing need a cost. If it is empty, the cost is 10,000 ÷ capacity (OSPF auto-cost). |
| MonitoringRecord | `status` | Availability history: whether the element was up or down at that time. |
| MonitoringRecord | `received_at` | The wall-clock time the adapter received the data, used to measure NFR1 (five seconds). |
| Prediction | `model_version` | Which trained model produced the forecast. |
| SimulationResult | `status`, `run_by`, `requested_at` | The run queue (queued → running → completed or failed) and the audit trail of who ran what. |

**Tables outside the six.**
- User accounts live in Django's built-in authentication tables (`auth_user`, `auth_group` and related). `created_by` points there, which completes Figure 3.3's missing user entity.
- Sessions use `django_session`.
- The engine's runtime status (D27) uses the cache table `dt_runtime_cache`.

These are all framework tables, not application data.

**Rules enforced by the database:**
- A MonitoringRecord row describes exactly one device or exactly one link (check constraint `monitoringrecord_device_xor_link`). Table 3.3's "each record belongs to one device" and "one link" therefore read as "each device-level record belongs to one device; each link-level record belongs to one link".
- No duplicate readings: (link, timestamp) and (device, timestamp) are unique, so re-ingesting a cycle is harmless.
- Utilisation and CPU must lie between 0 and 100; capacity must be positive; confidence must lie between 0 and 1.
- A link cannot connect a device to itself, and there is at most one link per pair of devices.
- No history is ever deleted by accident: every foreign key uses PROTECT. Devices and links are retired with status `decommissioned`.

**Units and conventions:**
- Traffic is in Mbps; percentages run from 0 to 100; all times are stored in UTC and shown in West Africa Time.
- On a link row, `traffic_out` is source → destination and `traffic_in` is destination → source, as seen from the source device's interface.
- `utilisation_pct` is the busier direction ÷ capacity.

**Indexes for the time series.** The partial unique indexes on (link, timestamp) and (device, timestamp) double as lookup indexes, with BRIN indexes on the timestamps.

## 2. The "real network" (§3.6)

Section 3.6 says a data simulator generates realistic monitoring data. It was built as a separate program, the network emulator (`backend/netemu`), with no code shared with the twin. Two automated import rules enforce that separation.

**Topology.** `data/topologies/campus.yaml` describes an illustrative YCT-style campus (not the real YCT network) with 34 devices and 43 links:
- two ISP uplinks of 300 and 200 Mbps;
- an edge router and a firewall;
- two core switches;
- a data centre with six servers;
- eight distribution zones;
- access switches and Wi-Fi access points.

**Traffic model.** Zone populations × daily and weekly activity profiles × eight traffic classes × semester growth × scheduled events (CBT exam sessions, a registration rush, a software-update day) × random noise.

**Realism.** It includes:
- random link and device failures with repair times;
- reboots that reset counters;
- CPU load that rises with throughput;
- error counts that rise above 85 % utilisation;
- data-quality faults (missing samples, bogus counter values).

There is also a deliberate reality gap, so the twin's model is never trivially perfect:
- uneven multipath hashing;
- 3 % protocol overhead;
- noise;
- flow records sampled 1:100 and exported one cycle late, as real NetFlow is. The twin has to *estimate* demand from sampled, delayed data rather than read it exactly.

Three presets (off, default, high) let E1 and E4 show how accuracy changes as the gap widens. The emulator's `--reality-gap` option selects one.

**Flash crowds.** Four seeded flash crowds a day put congestion ramps into the history the models learn from. Each is drawn from weighted templates, for example a live football match on the hostel Wi-Fi in the evening (the most likely), a lecture video in a school, or a portal rush. They can be switched off in the lab, and E3 switches them off and injects its own.

**Special events.** The software-update day is day 11, inside the held-out test days, so forecasting is tested on an event the model never saw.

**Calibration.** Over a simulated fortnight on the default settings:
- the 200 Mbps ISP uplink reaches the yellow band (≥ 70 %) on weekday mornings, and red only on the scheduled software-update day;
- the 100 Mbps hostel access points reach yellow on busy evenings;
- the campus LAN stays lightly loaded.

`python -m netemu.calibrate --days 14` reproduces these figures.

**Read-only feed used by the twin:**
- `/v1/snapshot`: SNMP-style counters such as ifHCInOctets, ifHCOutOctets, ifOperStatus, ifInErrors, sysUpTime and CPU. They are taken exactly at each cycle boundary, as a poller on a fixed schedule would read them.
- `/v1/flows`: NetFlow-style flow records per cycle.
- `/v1/events`: trap-style up/down notifications.

**Lab interface.** A separate, token-protected interface is used only by the test harness and the demo. It steps the clock, injects surges and failures, applies "real" configuration changes, and exposes ground truth for the evaluation.
- **Token:** created at random on first start (`var/netemu/lab_token`, never in git). There is no default.
- **Logging:** every lab call is logged with its caller.
- **Separation:** the tools that use the lab live in the `lab` Django app and the `evaluation` package. An import contract forbids the twin's code from importing them, and a test checks that no twin source file mentions the lab interface.

**Clock.** Network time and the cycle number are saved after every cycle, and a restart resumes from there, so time never goes back (D26). Demo mode runs network time faster than the wall clock (for example 20×). On Windows the save can fail for a moment while another program has the file open (a virus scanner, or someone reading it); this once stopped a history run. The save now retries briefly and otherwise skips that cycle's save with a warning, and a failing cycle observer can never stop the network. A test covers both.

**Traffic calendar across restarts** (fixed on 25 October 2026, found while designing E9).

The bug:
- Growth (1 % a week) and the day-numbered events (the registration rush on days 2–3, the software-update day 11) count from the emulator's start.
- A resumed emulator used to start that calendar again.
- So the stored 14-day history, which was generated in two emulator runs, has its growth clock reset part-way through, and its first-days events happened twice.
- E2 found the related symptom: the software-update day never fell in its test period.

The fix:
- The saved clock now also holds the calendar's `origin`, and a resumed emulator keeps it, so growth and events carry on.
- A unit test covers it.

The existing history is unchanged. Chapter 4 should describe its growth as not a clean 1 % a week. E9 measures growth on worlds with a continuous calendar.

## 3. Data collection layer (Figure 3.2, Figure 3.4 processes 1.0–2.0)

**Read-only by design.** The adapter interface (`describe`, `poll`, `events`) has no operation that writes to devices. Unit tests check this, and an import rule prevents the simulation engine from reaching the adapters at all.

**Flow telemetry is an extension.** Chapter 3 names "device status and interface traffic data"; the build also collects NetFlow-style flow records. They give the twin a traffic demand matrix, which the simulation engine needs to "run traffic through the modified model" (§3.7). Figure 3.2's "telemetry feed" covers it, but §3.4, §3.6 and Figure 3.4 should mention it (see CHAPTER3_FIXES).

**Preprocessing rules** (process 2.0):
- Counters become rates: Mbps = Δoctets × 8 ÷ Δt ÷ 10⁶.
- 64-bit wrap-around is handled.
- A counter that drops means the device rebooted: that interval is discarded and the reset is counted.
- A rate above 105 % of the interface speed is a bogus reading. It is rejected, and the last good reading is kept as the baseline.
- Utilisation between 100 % and 105 % is clipped to 100 % and counted.
- Timestamps come from the source's own clock. A cycle polled twice is ignored, and a clock that goes backwards stops ingestion with a visible error.
- **Capacity drift** (added after a test exposed the gap): if the devices report an interface speed different from the stored capacity, the twin adopts the new capacity and updates the Topology Store. The replica's configuration therefore follows real upgrades, which Table 3.1 G1 implies. Without this, utilisation after an upgrade was computed against the old capacity.
- Every cycle produces a data-quality report: interfaces expected, received and missing, spikes rejected, counter resets, values clipped, unknown elements, capacity changes.

**Source restarts.** Flow records and events are read with a cursor (the last number seen). If the source restarts and numbers its records from the start again, its latest number is behind the cursor; the adapter notices this and reads the new records instead of waiting for the old numbers to come round again. Found while restarting the emulator during a history run; covered by a test.

## 4. Network model (Figure 3.2, Figure 3.4 process 3.0)

**Structure.** A NetworkX graph with devices as nodes and links as edges (FR1).
- Node attributes: type, configuration, status, CPU, traffic and errors.
- Edge attributes: link id, which end is the source, capacity, routing cost, status, traffic in each direction, utilisation and errors.
- The model also holds the current traffic demand matrix.

**Updates.**
- Periodic: from each validated cycle.
- Event-driven: from up/down notifications, applied immediately (FR2).

**Bottleneck identification** (Table 3.5):
- load bottlenecks: links at or above 90 %;
- structural bottlenecks: single points of failure (bridges and articulation points) and the most-used links (edge betweenness).

**The twin's routing** is written independently of the emulator's:
- shortest paths by routing cost, with traffic split equally across equal-cost paths;
- a virtual INTERNET node sits behind the two internet gateways.

## 5. Simulation engine (Figure 3.4 process 5.0, UC3, gap G3)

**Scenario types:** traffic increase, link failure, device failure, routing change, reroute traffic, capacity change, access-control rule and QoS policy (all Must), plus add-link (Could). Each has plain-language help, a guided form, and validation that returns clear messages.

**How a run works.**
1. A deep copy of the live model is taken. The live model is never modified, and a unit test checks this after every scenario type.
2. The baseline is routed on the copy.
3. The change is applied to a second copy and routed again.
4. Results cover every link before and after, bottlenecks created and relieved, devices cut off, traffic that can no longer be delivered, and a plain-language summary.

**Calibration.** The median of measured ÷ modelled utilisation over busy links, clamped to 0.8–1.25, is applied to both baseline and change. It absorbs systematic gaps such as protocol overhead; on the campus network it settles at about 1.03, matching the emulator's 3 % overhead.

**Offered load can exceed 100 %.** Predicted utilisation is the load offered to a link. Values above 100 % are reported as "overloaded" (traffic would be dropped) rather than cut off at 100 %.

**Forecast-state option.** To build the load for a future time, each demand is scaled by predicted ÷ current utilisation of the busiest link on its path. This is an approximation; E4 checks it.

**Early evidence for E4.** In `tests/unit/test_sim_vs_reality.py`, the twin predicted each change and the same change was then applied to the emulator's "real network". On the campus network at a busy hour, across link failure, capacity change, traffic increase, routing change and access-control rule:
- mean absolute error ≈ 0.24 percentage points;
- busy links ≈ 0.5 points;
- maximum 2.1 points.

The full E4 will report these properly.

## 5a. Recommendations (§3.2 "insights and recommendations", the "Optimization" in the title)

For a link forecast to congest, the engine builds candidate fixes and tests each one on a detached copy against the forecast load:
- raise the link's routing cost;
- reroute the largest flow crossing it;
- limit its largest traffic class to 70 % of its current load on the link (QoS);
- upgrade it to the next capacity tier.

**Filtering.** Candidates are discarded if they:
- create a new bottleneck;
- cut a device off;
- drop traffic;
- or, for an immediate fix, leave the link at 90 % or more.

**Ranking.** Immediate fixes (routing, reroute, QoS) are ranked by least disruption. A capacity upgrade always relieves a link, so it is shown separately as planning advice rather than competing with them. Nothing is applied automatically.

## 5b. Prediction engine (Figure 3.4 process 4.0, FR3, gap G2)

**One feature function** is shared by training, live forecasting and evaluation. Tests check that it never looks ahead and that offline and online features match to 1e-6. Features:
- current utilisation;
- lags of 1–5, 10, 15, 30 and 60 minutes;
- rolling mean, standard deviation and maximum over 5, 15 and 60 minutes;
- 5- and 15-minute slopes;
- "now + slope × horizon" projections for each horizon;
- recent errors;
- time of day and day of week, and a weekend flag;
- link capacity and tier;
- full model only: the same time "yesterday", each target time "yesterday", yesterday's change over each horizon, and the gap between today and yesterday at each target time.

The last two were added after the first end-to-end training run, where the same-time-yesterday baseline beat the forest at 30 minutes: the forest predicts the change, so it needs yesterday's *change* as a feature, not only yesterday's level.

**"Yesterday" is the previous day of the same type.** For Monday that is Friday, and for Saturday the previous Sunday; every other day uses the day before. If that day is not in the history yet, the features say "no change" rather than guessing. This came from watching the live system: on a Monday morning a link climbed steadily from 10 % to 68 % over three hours, yet the model forecast a fall to 60 %, because "yesterday" was a quiet Sunday. With the same-type day, held-out error at +30 min fell from 0.95 to 0.60 points, and on that Monday from 1.29 to 0.27. The engine keeps 7 days of history in memory so that it always has the reference day.

**Predicting the change.** The Random Forest predicts the change u(t+h) − u(t) rather than the level, and adds it to the current value. A tree can only average the targets it was trained on, so a level forecast could never exceed levels seen before. Predicting the change lets a ramping link be flagged before its first crossing. Found in the second design review; checked by the P3 exit test.

**Random Forest settings.**
- 100 trees, depth at most 14, at least 15 samples per leaf;
- each tree trained on 20 % of the rows, 2 parallel jobs;
- one model forecasts all four horizons (5, 10, 15 and 30 minutes).

The model must be under 100 MB.

**Two forests, two jobs.**
- The **regression forest** forecasts utilisation; it feeds the chart and `predicted_utilisation`.
- A **classification forest** decides warnings. For each horizon it predicts whether the link will reach 90 % at any point within that horizon. It is trained only on moments when the link is below 90 %, and it uses the short-history features only. Flash crowds start at random times, so yesterday's values say nothing about them and only add noise.
- A warning is raised when its probability reaches a **threshold chosen during training**. A classifier is fitted on the first 80 % of the training period. The threshold with the best F1 score on the last 20 % is kept and stored with the model, so the test period is never used for the choice. The System page shows each model's threshold.
- **No class re-weighting.** The first version used scikit-learn's "balanced" class weights. On a forest with four outputs (one per horizon) those weights multiply, so the 24 training moments that were positive at every horizon carried 100 % of the weight. Without weights, the probability stays close to how often similar past moments really congested (on held-out data, warnings with p ≥ 0.8 congested 82 % of the time instead of 59 %). Rarity is handled by the tuned threshold instead.

**Why a classifier.** The P3 exit test showed that the regression forest, which minimises average error, learns to distrust slopes: in ordinary traffic they are mostly noise. So it reacted only 3 minutes before a real ramp crossed 90 %. "Will it congest within h?" is a classification question. The classifier meets the exit criterion: at least 10 minutes' warning for a ramp from 60 % to 95 % over about 20 minutes. This follows the classification approach to performance-degradation prediction cited from Ahmed et al. (§2.4). Both are scikit-learn Random Forests, as Figures 3.1 and 3.2 say.

**Confidence (D5)** is the share of the deciding forest's trees that agree with the verdict: the classifier's probability for a warning, or 1 − that for no warning. For a link already at or above 90 %, it is the share of regression trees agreeing. Because the warning threshold can be below 0.5, a warning can carry low confidence; the dashboard then says so ("Low confidence").

**Training history must be consistent (D20).** The first end-to-end history mixed two emulator configurations: the traffic was recalibrated part-way through, so only the last few days had real evening congestion. That left 8 congestion events to train on, and the 10/14 split put the whole weekend in the test period. The models are therefore trained on 14 days generated with the final configuration, with weekends on both sides of the split.

**What can and cannot be predicted.** Flash crowds start at random times. From the start of a surge to the link reaching 90 % takes a median of 22 minutes, and 30 minutes before onset the link usually sits at its normal evening level. No method can warn 30 minutes ahead of such an event; the realistic lead is about 10–20 minutes. E3 measures whether the median reaches its target of 10 minutes.

**Training report.** Training also reports how well warnings would work if they were taken from the regression forecast or from the linear trend instead. That is evidence for the choice above.

**Two models (D6).** The full model uses the same-time-yesterday features. A short-history model without them serves the first day, from one hour of history onwards. The predictor switches between them automatically.

**Comparison (Table 3.5).** Gradient boosting (HistGradientBoosting, one per horizon) is trained alongside, and three baselines are reported: persistence, linear trend, same time yesterday.

**Registry.** Every trained model is saved with its metadata: training window, rows, metrics, feature and permutation importance, size and library versions. A new model is promoted only if its test error is no worse; versions never collide.

**Alerts (D22)** use hysteresis. An episode starts at the first warning and ends after 5 consecutive calm cycles below 85 %. The same code rebuilds alert history from stored Prediction rows, so live alerts and history agree.

## 6. Engine runtime (§3.2, §3.6)

**The cycle.** One cycle runs collect → validate → update the twin → store. Each step is timed, and the timings appear on the System Status page and in the evidence pack.

**Scheduling.** The engine polls just after each cycle boundary of the source's clock (network time).

**Publish first, then housekeeping** (fixed on 26 October 2026, found by E5).
- The hourly retention delete and the model-reload check used to run inside the cycle, before the cycle was published.
- So every 60th cycle reached the dashboard 4–10 s late, which breached NFR1 at both 1× and 10×.
- They now run after the publish. After the fix, E5 at 10× measured a maximum of 3.7 s, down from 10.1 s.
- A test covers the order.

**Late polls are counted, not hidden.** If a cycle takes longer than the time to the next boundary, the network has moved on when the engine polls again. Like a real SNMP poller, the twin cannot read a boundary afterwards. Such missed cycles are counted, logged as warnings and shown on the System page. Readings bridge the gap: the next counter difference covers the whole interval, and short gaps (up to 5 cycles) are forward-filled for forecasting. This mattered at the 20× demo speed (one cycle every 3 s): on the 2-core laptop, with model training and a browser running, about a quarter of the cycles were missed at first. Two changes reduce it:
- the dashboard is told about a cycle as soon as its data and forecasts are stored;
- the fixes for a new alert are worked out on a separate worker thread instead of inside the cycle. The worker starts work only while the main loop is waiting for the next boundary: Python runs one thread at a time, so a busy worker during a cycle would still slow it (one cycle took 8.9 s when five alerts started together during a test).

**Demo speed.** Choose a speed at which the laptop keeps up, so that the System page shows no missed cycles; 20× needs a quiet machine.

**Recovery (NFR2).** If the data source or the database is unreachable, the engine reports it and retries with back-off. No manual step is needed.

**Status.** Engine status goes to the database cache table (D27): heartbeat, state, last cycle, timings, data quality, recent events.

**Topology changes need a restart.** The engine loads the Topology Store only when it starts. Any change to devices or links other than a map position (a dashboard edit, an import through the dashboard, or `manage.py import_topology`) moves a shared counter in the same cache table. The engine compares it with the value it started with, and its status reports `topology_changed` until it is restarted; the System page then asks for the restart. Map positions are read straight from the store by the dashboard, so moving devices on the map needs no restart, and neither does a save or an import that changes nothing.

**Retention (D19)** is measured in network time: 14 days of monitoring records and 2 days of predictions.

**Training history (D20).** `manage.py backfill_history` steps the emulator's clock through its lab interface. Every cycle passes through the same adapter, preprocessing and network model as live operation.

## 7. Security already in place (§3.8)

- **Passwords:** Argon2id with a unique salt per user, at 19 MiB memory, 2 passes and 1 lane (OWASP minimum, sized for a 4 GB laptop). Django's password validators require at least 10 characters.
- **Roles:** two groups. Senior Administrator has full access; Junior Administrator can only view. A disabled system account owns automatically generated recommendation scenarios.
- **Sessions:** HttpOnly, SameSite=Lax cookies.
  - A read-only dashboard may stay open for a working day (12 h).
  - Changes need activity within the last 30 minutes; automatic polls never count as activity.
  - After a longer absence, reading is allowed but changes stay locked until the password is confirmed. Otherwise someone finding an unattended screen could open one page (which counts as activity) and then make changes. Found while building the dashboard; covered by a test.
  - Sessions are cached in memory, so polls do not hit the database.
- **Admin site:** the six tables are view-only. Monitoring records, predictions and simulation results are evidence and cannot be edited there. The admin is used for users and roles.
  - Seniors can add and change accounts and give them the Senior or Junior Administrator role, but cannot tick "superuser", grant raw permissions, join other groups, or change superuser accounts. Django's default user admin allows all of that, which would let a senior give themselves more than the two roles. Accounts are deactivated rather than deleted, so their history and audit trail stay. Covered by tests.
- **API documentation:** the schema and Swagger pages need a login.
- **Password checks are rate-limited:** `auth/password` allows 10 attempts an hour per user. django-axes only guards the login form, so without this a stolen session could be used to guess the password.
- **Audit trail** (`var/log/audit.log`, 5 rotating files of 1 MB):
  - sign-ins, failed and refused sign-ins, sign-outs;
  - password changes and confirmations, and failed password checks;
  - scenarios created, changed, copied or deleted, and every simulation request;
  - device and link edits, and topology imports (including checks without saving).

  Each line carries the action, user, client address and time. Passwords are never written, and a test checks this.

## 8. Architecture rules checked automatically (NFR5)

`lint-imports` (import-linter) enforces five contracts, which currently pass 5 of 5:
1. The emulator does not import the twin.
2. The twin does not import the emulator; it reads it only over the network.
3. The simulation engine has no path to the network adapters (G3). This rule caught a hidden indirect dependency, which was removed by moving the raw-data types into a neutral module.
4. The twin never uses the lab client. Only the test harness may control the emulator (G3).
5. The engine core (data collection, network model, prediction, simulation) does not depend on Django.

**Extension points.** There are two registries:
- **Scenario types** (`simulation_engine/scenarios.py`). The dashboard builds its cards and forms from the registry, through `GET scenario-types`.
- **Network adapters** (`network_adapter/__init__.py`). `run_twin --adapter <key> --source <address>` picks one.

A worked example in [EXTENDING.md](EXTENDING.md) adds a "Link degradation" scenario type and a "snapshot-replay" adapter:
- 7 files, 123 lines added and 1 changed;
- no change to the engine, the API or the dashboard.

The example was tested on a copy of the repository and kept out of the delivered system, which stays as Chapter 3 describes. Its diff is in `docs/evidence/NFR5_extension_example.diff`.

## 8a. REST API (Figure 3.2 Django REST Backend, Figure 3.4 process 6.0)

All under `/api/v1/`, JSON. The live documentation is at `/api/v1/docs` (Swagger UI, login required).

**Authentication.**
- `auth/csrf` and `auth/login`: the login is CSRF-protected, and django-axes locks an account after 5 failures by username and address, for 15 minutes.
- `auth/logout`, `auth/me`, `auth/password` (change, or confirm to make changes again).

**Live view.**
- `live` is polled every second (`DASHBOARD_POLL_SECONDS`, default 1) and carries the state version (D28).
- `topology` returns every device and link with its latest readings, health colour, forecasts, warning, and single-point-of-failure and most-used flags, plus summary figures. It is cached per state version.

**Devices and links.**
- `devices` and `links`: list and detail; seniors can also create and update. There is no delete; retire with status `decommissioned`.
- A device's links must be retired before the device itself (400 otherwise, naming the links still in service). A link to a retired device cannot be saved in service, is skipped by an import (the report lists it under `links_skipped`), and is left out of `topology` and of the network model, so the map never draws a link to a missing device.
- `…/{id}/metrics`: raw cycles up to 6 h, 5-minute buckets up to 48 h, hourly beyond.
- `links/{id}/forecast`: history plus the predicted trajectory.

**Alerts.**
- `alerts/active`: episodes with predicted problem time, minutes until it, confidence band, trajectory and stored recommendations.
- `alerts/history`: rebuilt from the Prediction rows with the engine's own hysteresis code.

**Simulation.**
- `scenario-types`: the guided-form definitions and choices.
- `scenarios`: create with full validation and plain-language errors. A scenario that has results returns 409 if edited; copy it instead. `run` returns 202 and queues the run for the engine.
- `results`, and `results/{id}/compare?against=stored|live`.

**Trends and capacity.**
- `trends/links`: 24 h, 7 d or 14 d; per-link summary or one link's series.
- `trends/network`: the average and the busiest link across the network, for up to 336 hours (14 days): every cycle up to 6 h, 10-minute buckets up to 24 h, hourly buckets beyond. Periods over 24 hours are cached for 10 minutes.
- `trends/heatmap`: weekday × hour, over the last 14 days.
- `trends/capacity`: a linear fit of the daily 95th percentile over the last 14 days.
  - **Days used:** complete West Africa Time days only. Today is left out until it is over, and so is any day with less than 20 hours of readings.
  - **Fit:** each day of the week has its own level, so the fit is p95 = a + b·day + the level of that weekday. With 9 days or more the growth therefore compares each weekday with the same weekday a week earlier. With 5–8 days, Saturdays and Sundays share one level; with fewer days the fit is a plain line.
  - **Output:** the growth per week (b) and the projected date of reaching the critical threshold (90 %), counted from today. The projection starts from the busiest day's level. A crossing more than ten years ahead is not projected.
  - **Why the day-of-week levels (found by E9):** the original plain line was pulled by where the quieter days fall in the window. A window ending on a Sunday showed traffic falling fast on a growing network, and the sign of the error changed with the day of the week. A single weekend level was not enough, because the hostels make Saturday busy while Sunday is quiet. A test covers the fix.
- `trends/export.csv`.

**Administration.** `system/status` (engine, with `topology_changed`; models with their test accuracy; database size and row counts, exact for the small tables and PostgreSQL's estimate for the two large ones), `settings`, `users` (senior), `topology/import` (senior, with dry run; the report lists skipped links and says whether the engine needs a restart).

**Write rule.** Juniors may only read. A senior's change is refused with code `reauthenticate` (403) when there has been no non-poll activity for 30 minutes, or when the session has been idle that long since the password was last entered (the session is then "write-locked" until `auth/password` confirms it). The dashboard then asks for the password and sends the change again. Automatic polls carry `X-Poll: 1` and never count as activity. `auth/me` reports `write_allowed`.

**Error format.** Every error has a plain-language `detail` and a machine-readable `code`.

## 8b. Dashboard (Figure 3.2 presentation layer, §3.7, UC1–UC4)

**Technology.** Next.js 16 (React 19, TypeScript, Tailwind CSS 4) built as a **static site** (D14): `npm run build` writes plain HTML, CSS and JavaScript to `frontend/out`. Caddy serves it on the same origin as the API, so the session and CSRF cookies work without cross-origin rules. No server-side JavaScript runs in production, and the build needs no internet: no web fonts, icons drawn in the code. Libraries: TanStack Query (fetching and caching), Cytoscape.js (network map), Recharts (charts). Each was pinned to a release at least two weeks old.

**Pages.**
- **Sign in.**
- **Overview (UC1):** summary figures, the live network map, predictive alerts, the network trend and the busiest links.
- **Link and device detail:** history with the forecast drawn as a dashed projection, traffic, the forecast table, the alert with its recommendations, and configuration editing for seniors.
- **Alerts (UC2):** active alerts with their forecast and simulated recommendations, plus history.
- **Simulation (UC3):** a guided form built from the server's scenario types, saved scenarios, runs, and a result page with before/after comparison.
- **Trends (UC4):** long-term series, busiest links, weekly heatmap, capacity planning and CSV export.
- **System:** engine health and per-step timings, data quality, model accuracy against the no-change baseline, the database, settings, users, topology import, and password change.

The detail pages use query strings (`/link?id=5`) so the site can be fully static.

**Live updates (D28, NFR1).** One small request (`live`) is polled every second. Every other view is keyed by the engine's state version, so it is fetched again only after the twin stores a new cycle or applies an event. Between versions the previous data stays on screen, so nothing flashes. The map updates its colours in place, keeping zoom and pan.

**Activity and re-authentication (D8).** Automatic requests send `X-Poll: 1`. Real use of the page (a click or key press, at most one ping a minute) counts as activity. When a change is refused with `reauthenticate`, a dialog asks for the password and the change is sent again.

**Visual rules.**
- Status is always colour, icon and words together, never colour alone: green Normal, yellow Warning, red Critical, grey Down, plus orange "Congestion predicted".
- Every chart has a table view with the same numbers.
- Dashed lines are used only for thresholds and forecasts. There is one y-axis per chart, and a legend whenever there are two or more series.
- Light and dark themes follow the operating system, with a manual switch.
- The colours come from a palette checked for colour-blind separation and contrast.

**Known dependency advisory.** `npm audit` reports a denial-of-service issue in a glob-matching package used only by the development linter (`eslint-config-next` → `fast-glob` → `micromatch` → `braces`). It is not part of the built site.

## 8c. Deployment (P6, NFR2, NFR4, §12)

**Processes.** Four processes run on the laptop:
- the emulator (the stand-in network and its read-only feed, 127.0.0.1:9161);
- the API (Django on Waitress, 127.0.0.1:8000);
- the Digital Twin Engine;
- Caddy, the HTTPS front door on https://localhost, which serves the static dashboard and passes `/api` and `/admin` to Waitress.

Waitress trusts the forwarded headers only from 127.0.0.1, so Django sees the original HTTPS request.

**Supervisor** (`deploy/supervisor.py`, standard library only).
- It starts the four in order, each once the previous one answers, and logs each to `var/log/<name>.log`.
- It restarts anything that stops, after a growing pause; after 5 failures in 5 minutes it leaves that one stopped and reports it.
- It stops whole process trees. On Windows the virtual environment's `python.exe` is a launcher that runs the real interpreter as a child, so stopping only the launcher would leave the program running.
- It publishes what is running in `var/run/supervisor.json`.

`deploy/start.ps1` and `stop.ps1` wrap it. `setup.ps1` installs everything once (INSTALL.md).

**Measured recovery (NFR2).** With the system running at 10× speed, each service's process tree was killed abruptly in turn. The supervisor restarted each one, and the twin stored a new cycle again, with no manual step:
- engine, after 46.9 s (most of it reloading 7 days of history on the 2-core laptop);
- emulator, after 15.1 s;
- API, after 24.1 s.

The results are in `docs/evidence/P6_recovery.json`, written by `deploy/recovery_check.py`.

**Security headers (NFR4)**, checked on the running system and recorded in `docs/evidence/P6_security_headers.txt`:
- plain HTTP is redirected to HTTPS;
- HSTS with a short max-age, because on localhost a long one would lock development out of plain HTTP;
- a Content Security Policy allowing only the site itself. It permits inline scripts, which Next.js pages need; the walkthrough over HTTPS logged no policy violations;
- frame-ancestors none and X-Frame-Options DENY;
- no-sniff, same-origin referrer, and a permissions policy denying camera, microphone and location;
- no `Server` header;
- session and CSRF cookies marked Secure, HttpOnly (session) and SameSite=Lax.

**The production walkthrough** ran against the static build behind Caddy with production settings. It passed 14 of 14 steps, and the overview showed each new cycle at most 1.15 s after it was stored.

**Two Windows lessons, both fixed:**
- **Replacing a file fails while another program is reading it.** This hit the emulator's clock file during a history run, and the supervisor's own state file while `start.ps1` checked whether the system was ready. Both writers now retry briefly and otherwise skip one update, and the readers retry too; neither can stop the system any more.
- **Caddy installs its local root certificate the first time it serves HTTPS.** On Windows that opens a dialog, and Caddy waits until someone answers it. The Caddyfile now says `skip_install_trust`, and `setup.ps1` runs `caddy trust` once, at a moment when the user expects the question.

**Offline fallback** (Should, done). `start.ps1 -LocalDatabase` starts the local PostgreSQL (pgserver), runs everything on it, and stops it again. `deploy/localpg.py install-timezones` adds the time-zone data its Windows build lacks. pgserver picks a new random port at every start, so a database restarted while the system runs would never be found again. `localpg.py` therefore reuses its previous port (found while preparing the E6 database-outage fault). Its `stop` also did nothing: pgserver's `cleanup()` never stops a server that is meant to outlive the script. So the database had never been stopped, and the soak's scheduled database outage did not happen. `stop` now uses `pg_ctl`, and the outage was tested on its own (E6).

**Not yet verified:** `setup.ps1` end to end on a fresh Windows account with a real Neon project. The script asks for the connection string and the first password, so it cannot run unattended. The students' first installation is that test.

## 9. Differences from Chapter 3 figures (fixes listed in CHAPTER3_FIXES)

- **Figure 3.2 vs §3.4.** The code follows Figure 3.2: the Django REST backend is in the Application and Digital Twin layer, not the user-interface layer.
- **Figure 3.4.** The as-built data flow adds:
  - process 7.0 Manage topology and users;
  - store D5 Users;
  - D2 → 6.0 and D3 → 6.0;
  - 6.0 → D4 (queued runs);
  - 3.0 → 5.0 (model copy);
  - 4.0 → 5.0 (recommendations);
  - flow telemetry into 1.0.
