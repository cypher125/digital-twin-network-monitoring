# Project Plan — Digital Twin-Based Network Monitoring and Optimization System

| | |
|---|---|
| Version | 1.3 — your decisions (Neon database, 2-week deadline, Chapter 3 editable, demo on the students' Windows laptop) plus the fixes from both design reviews (§19) |
| Date | 18 October 2026 |
| Source of truth | `Digital_Twin_Network_Chapter1_3_REVISED.docx` (Chapters 1–3) and `figures/` (Figures 3.1–3.5) |
| Prepared by | Claude (lead software engineer and architect) |

This plan turns Chapters 1–3 into a buildable system. Chapters 4 and 5 will be written from what we build, so the plan has two goals that carry equal weight: build exactly what Chapter 3 designs, and make the system produce real evidence for every claim the write-up makes.

---

## 1. Purpose and scope

### 1.1 What we are building

A web-based digital twin of an institutional (campus) network that:

1. keeps a live virtual model of the network (a NetworkX graph) synchronised with monitoring data on every cycle (Objectives 1–2, FR1–FR2);
2. forecasts the utilisation of every link with machine learning and warns administrators before congestion happens (Objective 3, FR3);
3. lets administrators test proposed changes on a detached copy of the model, with no path to the real network, and proposes tested fixes (Objective 4, FR4);
4. presents all of this on a secure Next.js dashboard backed by a Django REST API and PostgreSQL (Objective 5, FR5, NFR1–NFR5);
5. includes an evaluation harness that produces the results Chapter 4 will report (Objective 6).

### 1.2 What plays the "real network"

Section 3.6 says that "a data simulator was built that generates realistic monitoring data based on configurable network topology and traffic models". We build that as a separate program, the **network emulator** (`netemu`). It carries simulated traffic over a campus topology and exposes the same kinds of read-only interface that real equipment offers:

- SNMP-style interface counters;
- NetFlow-style flow records;
- trap-style up/down events.

The twin collects from it through a genuine data collection layer. Flow records go beyond Chapter 3's "device and interface metrics" and are logged as an as-built extension (D11). A read-only SNMP adapter for real devices is a should-have.

### 1.3 In scope and out of scope

**In scope:** everything Chapter 3 specifies, plus four features that Chapters 1–3 promise without designing:

- long-term trend and capacity analysis (weakness 3 in §3.1.1);
- recommendations (§3.2, and "Optimization" in the title);
- topology import (§1.4);
- user and role management (§3.8).

**Out of scope** (these become Chapter 5 future work):

- writing configuration to real devices (deliberately excluded by G3 and §3.8);
- carrier-grade or very large networks (§1.4);
- deep-learning models (LSTM, GNN) in production;
- email or SMS notifications;
- multi-site deployment.

### 1.4 What fits the 2-week deadline (target: 1 November 2026)

- **Must (built first):**
  - everything Chapter 3 specifies;
  - the emulator, plus the telemetry and file-import adapters;
  - all eight Must scenario types (D21), including the access-control and QoS changes named in §1.2;
  - simulations against the forecast state;
  - recommendations and the Trends & capacity page;
  - experiments E1–E5 and E7, a shortened E6, and the E8 materials.
- **Should (only after every Must passes):**
  - the SNMP adapter, with a trap receiver and a counter-only demand estimate (D11);
  - a "Retrain now" action on the Administration page;
  - an offline database fallback for the defence.
- **Could (Chapter 5 future work unless time remains):** the add_link scenario, alert acknowledgement, an MLPRegressor comparison, a thresholds form.
- **User and role management** uses Django's built-in admin site rather than a custom page.

---

## 2. Guiding principles

1. **Chapter 3 is the contract.** Code uses Chapter 3's names for tables, fields, components and use cases, so Chapter 4 can describe the system in the same terms. Anything the build adds or changes is logged in `docs/AS_BUILT_NOTES.md` for Chapter 4.
2. **Real evidence only.** Every claim in the Abstract and Chapters 1–3 is backed by a measured result. No number goes into Chapter 4 unless the evaluation harness produced it.
3. **Lean by design (G4).** The whole system must run on the development laptop: an Intel Celeron N4020 with 2 cores and 4 GB RAM. If it runs there, it runs on "standard server hardware", and that becomes Chapter 4 evidence for G4.
4. **Read-only towards the network.** Adapters only read. The simulation engine only touches copies. Automated tests enforce both rules.
5. **Modular (NFR5).** Engine packages do not depend on the web layer. Adapters and scenario types plug in through registries. Layering rules are checked automatically with import-linter.
6. **Build in the order of §1.5:** network modelling and simulation first, then machine learning, then the web application. Tests are written alongside the code.

---

## 3. Decisions that settle what Chapter 3 leaves open

Each decision below is stated once in settings and used everywhere. Chapter 4 should quote these values.

| ID | Topic | Decision | Reason |
|---|---|---|---|
| D1 | Health thresholds | Green below 70 %, yellow 70–89.9 %, red 90 % and above. Applies to link utilisation and device CPU. The dashboard colours, the warning rule and the bottleneck rule all read the same values. | §2.2 treats 70 % as "headroom available"; the 80 % example in §1.1 falls in "approaching a threshold". |
| D2 | Monitoring cycle | One cycle per 60 s of network time. Demo mode runs network time faster: by default 20×, i.e. one cycle every 3 s. | 60 s is standard SNMP polling granularity. Demo mode makes daily patterns and alerts visible within a defence presentation. |
| D3 | Forecast horizons | 5, 10, 15 and 30 minutes, with one Prediction row per link per horizon per cycle. | Together the horizons form the "predicted future trajectory" in UC2; 30 min is the longest horizon cited in §2.4. |
| D4 | Warning rule | For a link below 90 %, `is_warning` comes from a **Random Forest classifier** that predicts whether the link will reach 90 % within each horizon. A warning is raised when its probability is 0.5 or more (configurable). A link already at 90 % or more is "critical now"; its warning follows the regression forecast. The predicted time of the problem = `generated_at` + the earliest warning horizon. `predicted_utilisation` always comes from the **regression forest**. | Delivers UC2's "when the problem is predicted to occur". A regressor trained to minimise average error learns to distrust slopes, which in ordinary traffic are mostly noise, and so it reacts late to real ramps. "Will it congest?" is a classification question. Ahmed et al. (§2.4) cite classifiers for predicting performance degradation, and both models are scikit-learn Random Forests (Figures 3.1 and 3.2). |
| D5 | Confidence score | The share (0–1) of the deciding forest's trees that agree with the row's verdict. For a warning, that is the classifier's probability of congestion; for no warning, 1 − that probability. For a "critical now" link it is the share of regression trees agreeing. Shown as High (≥ 0.8), Medium (0.6–0.8) or Low. | Easy to explain, comes from the model itself, and its calibration is measured in E3. |
| D6 | Minimum history | 60 cycles (one hour) before the first forecast. Until then the panel shows "Collecting history (n/60)". The first forecasts use a short-history model without the same-time-yesterday feature; after a day of history the full model takes over automatically, and the dashboard shows which model is active. At start-up the engine reloads its history buffer from the database. | The 60-minute lag features need an hour of history (UC2 precondition), and a fresh deployment should not wait a whole day for its first forecast. |
| D7 | Roles | Two groups. **Senior Administrator** can do everything. **Junior Administrator** has read-only access and cannot run simulations, import topology, change settings or manage users. | §3.8 says "read-only views". Running a simulation writes records, so it counts as a write. |
| D8 | Authentication | Django session login with HttpOnly, Secure, SameSite cookies and CSRF protection. Passwords hashed with Argon2 (19 MiB memory, 2 passes, 1 lane: OWASP's minimum, sized for a 4 GB laptop) and checked by Django's password validators. Login lockout by username and address (django-axes), covering both the dashboard login and the admin. A read-only dashboard may stay open for a working day (absolute session limit 12 h), so passive alerting works. Any change (a write) needs activity within the last 30 minutes, measured by a last-activity stamp that automatic polls never update. Polls never rewrite the session; sessions are cached in memory in front of the database. | §3.8. The dashboard is served from the same origin as the API, which makes sessions the simplest secure option. |
| D9 | Data sources | (a) Network emulator over an HTTP telemetry feed — used for the demo and the evaluation. (b) Read-only SNMP adapter (should-have). (c) CSV/JSON import of topology and historical data. | Fig 3.2 "SNMP polling / telemetry feed"; §1.4; §3.6. |
| D10 | Where simulations run | Inside the Digital Twin Engine, on a deep copy of the live model. The API submits a run (a SimulationResult with status `queued`); the engine executes it within about a second and stores the result. | Fig 3.2 puts the simulation engine inside the twin engine, and §3.4 says the backend "submit[s] simulation scenarios". |
| D11 | Traffic model inside the twin | A demand matrix (source, destination, traffic class, Mbps) built from flow telemetry. Demands are routed on shortest paths using an OSPF-style cost of 10,000 ÷ `capacity_mbps`, with traffic split equally across equal-cost paths. Link utilisation = the busier direction ÷ capacity. Flow records are an as-built extension beyond Chapter 3's "device and interface metrics". They are a standard monitoring feed (NetFlow/IPFIX), but they are logged in the as-built notes and the DFD. With SNMP-only sources (Should), a counter-only estimate is used instead: each access device's measured traffic is shared across destinations in proportion to their observed load (a gravity model). | Needed to run traffic "through the modified model" (§3.7). |
| D12 | User accounts | Django's built-in authentication tables, kept outside the six application tables. `created_by` points to the auth user. | Keeps §3.5's "six tables" true for application data. |
| D13 | Extra fields | Allowed, because Table 3.1 lists only "principal fields". Added: `NetworkDevice.configuration` (JSON), `NetworkLink.routing_cost`, `MonitoringRecord.status` and `received_at`, `Prediction.model_version`, `SimulationResult.status` and `run_by`. Each one is logged in the as-built notes. | FR1 needs device configuration, NFR1 needs a receipt time, and the audit trail needs run status. |
| D14 | Frontend delivery | Next.js (App Router) with TypeScript and Tailwind, pre-rendered to a static build served by Caddy. Pages use query strings (`/device?id=12`) instead of dynamic `[id]` routes, because a static export cannot generate pages for IDs created at runtime. Live data follows D28. | No Node server is needed at runtime, which is lighter on low-end hardware (G4). Table 3.4 gives "server-side rendering" as a reason for choosing Next.js; §15 note 15 covers that wording. |
| D15 | HTTPS | Caddy reverse proxy with its own local certificate authority (`tls internal`), HTTP→HTTPS redirect and HSTS. | Table 3.4 row 7. Caddy is a single small binary on Windows. |
| D16 | Process model | Four programs on the laptop: network emulator, Digital Twin Engine, API server (Waitress) and Caddy. The database is on Neon (D24). A small supervisor starts the four programs and restarts any that crash. | NFR2. |
| D17 | Versions (checked 18 Oct 2026) | Python 3.13, Django 5.2 LTS (5.2.18) with DRF 3.18, NetworkX 3.7, scikit-learn 1.9, NumPy 2.5, pandas 3.0, psycopg 3.3, PostgreSQL 17 on Neon (D24), Node 22, Next.js 16.4, React 19, Tailwind 4, Cytoscape.js 3.34, Recharts 3. Everything is pinned with lock files (`uv.lock`, `package-lock.json`). | LTS where it matters: Django 5.2 receives security fixes until April 2028. |
| D18 | Time | Stored in UTC; displayed in Africa/Lagos time (WAT). | Avoids time-zone errors. |
| D19 | Retention | Raw monitoring records are kept for 14 days and predictions for 2 days by default; both are configurable. This keeps the database at about 350 MB, inside Neon's free-plan storage (0.5 GB, possibly 1 GB now). | Monitoring records add about 22 MB a day. Predictions add about 26 MB a day (45 links × 4 horizons × 1,440 cycles). |
| D20 | Training history | The emulator fast-forwards through 14 days of history, which passes through the normal collection pipeline into PostgreSQL. Models train on the first 10 days and are tested on the last 4. | §2.4: models trained on data generated by the digital twin simulator. 14 days fits the storage budget in D19. |
| D21 | Scenario types | **Must:** traffic_increase, link_failure, device_failure, routing_change, reroute_traffic, capacity_change, access_control_rule, qos_policy. **Could:** add_link. | Covers every change type named in Chapters 1 and 3: §1.2 names routing, access-control and QoS changes. capacity_change and qos_policy are also recommendation actions. |
| D22 | Alert lifecycle | An episode starts when a link gets a warning. It ends only after 5 consecutive cycles in which every horizon is below 85 %, so an alert hovering near 90 % does not flap on and off. The active alert shows the newest warning for its episode. Recommendations are computed once per episode, for at most one link per cycle, inside a time limit, so the next cycle always starts on time. Acknowledging alerts is a could-have. | Without hysteresis, a link near the threshold would raise a new alert, and new recommendations, every few cycles. E3 counts false alarms per episode. |
| D23 | Supported size | Tested at 40, 100 and 200 devices (up to 400 links). | §1.4 targets "small to medium" networks. |
| D24 | Database hosting | PostgreSQL 17 on Neon, a managed serverless PostgreSQL service, in region AWS Europe (Frankfurt), the closest Neon region to Lagos. Compute 0.25–1 CU; TLS required; connection details kept only in `backend/.env`. Separate Neon branches for development, tests and evaluation runs. Each API endpoint makes at most three queries, and a shared topology snapshot is cached for 1–2 s, so the network round trip stays well inside NFR1. | Your decision; it also suits the programme (Networking and Cloud Computing). The free plan gives 100 compute-hours a month — about 400 hours of running time at 0.25 CU — so the engine is stopped when not in use instead of running 24/7. |
| D25 | Backend framework | Django + Django REST Framework, as Chapter 3 specifies. | Built-in user accounts, salted password hashing, roles, sessions/CSRF, ORM with migrations, and an admin site cover §3.8 with well-tested code. FastAPI's async speed brings nothing at this load (a few administrators polling every 2 s), and switching would mean rewriting the abstract, §1.4, §1.7, §3.4, Figures 3.1–3.2 and Table 3.4. |
| D26 | Network time | The emulator's network clock is the only source of `timestamp`. It saves its clock and resumes from it, never rewinding, so history stays continuous across restarts and demo speed changes. The twin checks timestamps against the feed's own clock (never in the future, never out of order). If the source's clock goes backwards it stops ingesting and says so on the System Status page, rather than freezing silently. Retention and "minutes until" are measured in network time. `received_at` (wall clock) is used for staleness and NFR1. The dashboard shows network time and the demo speed. | In demo mode, network time runs ahead of the wall clock. Mixing the two would break the validity checks, retention and the unique timestamps. |
| D27 | Runtime status | The engine's heartbeat, cycle timings, data-quality report and active model are written each cycle to Django's database cache table (a framework table, like the session table) and read by `GET system/status`. Model metrics also live in the model registry files under `var/models/`. | Keeps runtime state out of the six application tables without inventing a seventh. A shared file is unreliable on Windows while another process holds it open. |
| D28 | Live updates | The dashboard polls a tiny `GET live` endpoint every second. It returns a state version that the engine bumps after each cycle's final commit and after each applied up/down event. Every payload carries the version it was built from, and the dashboard refetches until its data is at least as new as `live`, so event-driven failures also appear within a poll (§4.4). The topology snapshot cache is keyed on the version, not on time. Trend views load when a page opens and are cached for 10 minutes. Automatic requests carry an `X-Poll` header, so they never count as user activity (D8). | Keeps the database round trips to Neon low (D24) and leaves headroom for NFR1. |

---

## 4. Architecture

### 4.1 Runtime view

```
 Browser: Next.js dashboard (static build)
    |  HTTPS, JSON (checks for a new cycle every 1 s)
    v
 +-------------+   static files   +---------------------------+
 |   Caddy     |----------------->|  frontend build (out/)    |
 | TLS, proxy  |                  +---------------------------+
 +------+------+
        | /api/*  (HTTP on 127.0.0.1)
        v
 +----------------------+   read / write   +-------------------------------+
 | Django REST backend  |<---------------->| PostgreSQL on Neon (Frankfurt)|
 | (Waitress)           |                  | D1 topology   D2 monitoring   |
 | auth, roles, API     |                  | D3 predictions D4 scenarios   |
 +----------------------+                  | + Django authentication tables|
                                           +---------------^---------------+
                                                           | read / write
 +---------------------------------------------------------+---------------+
 | Digital Twin Engine (run_twin)                                          |
 |   network model (NetworkX) - prediction engine (RF) - simulation engine |
 |   ^ data collection layer: network adapter -> preprocessing module      |
 +---|---------------------------------------------------------------------+
     | read-only: telemetry poll every cycle + event stream
 +---+---------------------------+
 | Network emulator (netemu)     |  stand-in for the real network
 | topology, traffic, faults     |  (real devices: SNMP adapter, same interface)
 +-------------------------------+
```

### 4.2 How the code maps to Figure 3.2

| Figure 3.2 element | Package (under `backend/`) | Runs in |
|---|---|---|
| Real network | `netemu/` (network emulator), or real devices | netemu process |
| Network Adapter (SNMP polling / telemetry feed) | `data_collection/network_adapter/` | Twin engine process |
| Preprocessing Module (validate, clean, normalise) | `data_collection/preprocessing/` | Twin engine |
| Network Model (NetworkX graph: nodes, edges, state) | `digital_twin/network_model/` | Twin engine |
| Prediction Engine (scikit-learn Random Forest) | `digital_twin/prediction_engine/` | Twin engine |
| Simulation Engine (what-if scenario runner) | `digital_twin/simulation_engine/` | Twin engine |
| Django REST Backend (authentication, authorisation, API endpoints, input validation) | `config/`, `apps/accounts/`, `apps/api/` | API server (Waitress) |
| PostgreSQL Database | `apps/twin/models.py` (the six tables) | Neon (managed PostgreSQL 17) |
| Next.js Dashboard (topology visualisation, alert & prediction panel, simulation console) | `frontend/` | Browser, served by Caddy |
| REST API — JSON over HTTPS | Caddy → Waitress | Caddy |

### 4.3 One monitoring cycle (Figure 3.4 processes 1.0–6.0)

1. **1.0 Collect monitoring data.** The adapter polls the telemetry feed (interface counters, device statistics, flow summaries) and records `received_at`.
2. **2.0 Validate and transform.** Preprocessing checks fields and ranges, converts byte counters to Mbps and utilisation %, rejects or clips bad samples, and writes a data-quality report.
3. **3.0 Update the digital twin model.** The network model updates node and edge state and the demand matrix. Records are bulk-written to MonitoringRecord (D2), and status changes to NetworkDevice and NetworkLink (D1).
4. **4.0 Generate predictions.** Features are built from in-memory history. The Random Forest forecasts every link at 5, 10, 15 and 30 minutes, and Prediction rows (D3) are written with confidence scores and warning flags.
5. **5.0 Execute simulations** (between cycles). Queued runs, and recommendations for new alerts, execute on copies of the model. Results go to D4.
6. **6.0 Render the dashboard.** The browser checks `GET live` every second and refetches data only when a new cycle has been stored (D28). The API reads D1–D4.

**Timing budget:** on the development laptop, at most 2 s from data receipt to committed predictions. New data is then on screen within about 4.5 s in the worst case, inside NFR1's 5-second limit.

### 4.4 Event-driven updates (FR2)

The emulator streams link and device up/down events, playing the role of SNMP traps. The adapter's event listener applies each event to the model immediately and writes the status change. A failure therefore appears on the next dashboard poll, without waiting for the next cycle.

### 4.5 How the as-built data flow will differ from Figure 3.4

The as-built DFD will be derived from the code in P7. These changes are already known, and Figure 3.4 itself can be corrected because Chapter 3 is editable:

- **A new process, 7.0 Manage topology and users.** Imports and edits go administrator → 7.0 → D1, because DFD rules do not allow an external entity to write straight into a store.
- **A new store, D5 Users.** It holds Django's authentication tables.
- **D2 → 6.0:** trend data for the charts.
- **D3 → 6.0:** predictions and alerts.
- **6.0 → D4:** the API queues simulation runs.
- **3.0 → 5.0:** a copy of the current model for each simulation.
- **4.0 → 5.0:** alerts trigger recommendations.
- **Flow telemetry into 1.0:** alongside device and interface metrics (D11).
- **Flows through stores:** 3.0, 4.0 and 5.0 reach 6.0 through D1–D4 rather than directly.

---

## 5. Repository layout

```
Digital_Twin_Revised/
|-- Digital_Twin_Network_Chapter1_3_REVISED.docx / .pdf     (unchanged)
|-- figures/                                                (unchanged)
|-- README.md                       quick start
|-- docs/
|   |-- PROJECT_PLAN.md             this plan
|   |-- AS_BUILT_NOTES.md           every place the build extends or differs from Chapter 3
|   |-- DATA_DICTIONARY.md          tables, fields, types and units
|   |-- API.md                      endpoint reference (live OpenAPI docs at /api/docs)
|   |-- INSTALL.md, USER_GUIDE.md, DEMO_SCRIPT.md
|   `-- evidence/                   Chapter 4 evidence pack: results, screenshots, test reports
|-- backend/
|   |-- pyproject.toml, uv.lock, manage.py
|   |-- config/                     Django settings (base/dev/prod), urls, wsgi
|   |-- apps/
|   |   |-- twin/                   the six Chapter 3 models, admin, migrations
|   |   |-- api/                    serializers, views, permissions, filters, urls
|   |   `-- accounts/               login/logout, roles, user management
|   |-- data_collection/
|   |   |-- network_adapter/        base interface, telemetry_http, snmp, file_import
|   |   `-- preprocessing/          validators, counter conversion, data-quality report
|   |-- digital_twin/
|   |   |-- network_model/          NetworkModel, synchroniser, routing, health, bottlenecks
|   |   |-- prediction_engine/      features, training, model registry, predictor, alerts
|   |   |-- simulation_engine/      scenario registry, runner, results, recommendations
|   |   `-- runtime/                engine loop, simulation job queue, persistence, heartbeat
|   |-- netemu/                     network emulator: topology, traffic model, faults, feed, lab CLI
|   |-- evaluation/                 experiments E1-E8, plotting, report builder
|   `-- tests/                      unit/ and integration/
|-- frontend/                       Next.js app: app/, components/, lib/, types/, e2e/
|-- data/
|   |-- topologies/                 campus.yaml (default), small.yaml, scale_100.yaml, scale_200.yaml
|   `-- samples/                    CSV/JSON import templates
|-- deploy/                         setup.ps1, start.ps1, stop.ps1, supervisor.py, Caddyfile
`-- var/                            runtime data: logs, trained models, emulator ground truth (not in git)
```

---

## 6. Data model

Model and field names match Figure 3.3 and Table 3.1 exactly. Fields marked * are extra, non-principal fields (D13).

### 6.1 Application tables

**NetworkDevice** (table `network_device`) — nodes of the graph (D1 Topology Store)

| Field | Type | Notes |
|---|---|---|
| device_id (PK) | bigint | |
| name | varchar(100), unique | e.g. `CORE-SW-01` |
| device_type | choice | router, switch, firewall, server, access_point, wan_gateway |
| ip_address | inet, unique, nullable | management address |
| location | varchar(120) | building or zone |
| status | choice | up, down, unknown, decommissioned |
| configuration* | jsonb | role, zone, vendor/model, interface→link map, diagram position, ACL and QoS settings |

**NetworkLink** (table `network_link`) — edges of the graph (D1)

| Field | Type | Notes |
|---|---|---|
| link_id (PK) | bigint | |
| source_device_id (FK) | → NetworkDevice | |
| dest_device_id (FK) | → NetworkDevice | |
| capacity_mbps | double, > 0 | |
| status | choice | up, down, unknown, decommissioned |
| routing_cost* | double, nullable | empty means 10,000 ÷ capacity_mbps |

Constraints: source and destination must differ; at most one link per pair of devices.

**MonitoringRecord** (table `monitoring_record`) — the time series (D2)

| Field | Type | Notes |
|---|---|---|
| record_id (PK) | bigint | |
| device_id (FK) | nullable | exactly one of device_id and link_id is set (check constraint) |
| link_id (FK) | nullable | |
| timestamp | timestamptz | measurement time |
| traffic_in, traffic_out | double, Mbps | on a link: traffic_out = source→destination, traffic_in = destination→source; on a device: totals over its interfaces |
| utilisation_pct | double, 0–100 | link rows only: max(in, out) ÷ capacity |
| error_count | integer ≥ 0 | errors during the interval |
| cpu_util | double, 0–100 | device rows only |
| status* | choice | the element's status at that time (availability history) |
| received_at* | timestamptz | when the adapter received the data (used to measure NFR1) |

Indexes: (link_id, timestamp desc), (device_id, timestamp desc), BRIN on timestamp. Unique (link_id, timestamp) and (device_id, timestamp), so repeated ingestion never creates duplicates.

**Prediction** (table `prediction`) — forecasts (D3)

| Field | Type | Notes |
|---|---|---|
| prediction_id (PK) | bigint | |
| link_id (FK) | → NetworkLink | |
| generated_at | timestamptz | cycle time |
| horizon_minutes | smallint | 5, 10, 15 or 30 |
| predicted_utilisation | double, 0–100 | |
| confidence_score | double, 0–1 | D5 |
| is_warning | boolean | D4 |
| model_version* | varchar(64) | which trained model produced the row |

Unique (link_id, generated_at, horizon_minutes). Index (link_id, generated_at desc), plus a partial index on warning rows.

**SimulationScenario** (table `simulation_scenario`) — scenario definitions (D4)

| Field | Type | Notes |
|---|---|---|
| scenario_id (PK) | bigint | |
| created_by (FK) | → auth user | |
| scenario_name | varchar(120) | |
| scenario_type | choice | D21 |
| parameters | jsonb | validated against the type's schema |
| created_at | timestamptz | |

Rule: once a scenario has results it cannot be edited. To change it, the administrator copies it, so every result always matches the parameters that produced it.

**SimulationResult** (table `simulation_result`) — executions (D4)

| Field | Type | Notes |
|---|---|---|
| result_id (PK) | bigint | |
| scenario_id (FK) | → SimulationScenario | |
| executed_at | timestamptz | set when the run finishes |
| predicted_utilisation | jsonb | {link_id: %} for every link |
| bottleneck_links | jsonb | links at 90 % or more after the change |
| result_summary | jsonb | plain-language summary; baseline utilisation and bottlenecks; bottlenecks created and relieved; changes per link; undeliverable traffic; thresholds and parameters used |
| status* | choice | queued, running, completed, failed |
| run_by* | → auth user, nullable | who ran it (a system account for recommendations) |

### 6.2 Relationships

These are the five relationships in Table 3.2, plus two that Chapter 3 implies but does not draw:

- auth user 1 : N SimulationScenario (`created_by`);
- auth user 1 : N SimulationResult (`run_by`).

### 6.3 Conventions

- Deleting a referenced row is blocked (PROTECT). Devices and links are retired by setting their status to `decommissioned`, and users are deactivated, so history and the audit trail are never lost.
- Units: Mbps, percentages from 0 to 100, UTC timestamps. The full data dictionary goes in `docs/DATA_DICTIONARY.md` and is reused in Chapter 4.

---

## 7. Component design

### 7.1 Network emulator — the stand-in real network (`netemu`)

**Default topology** (`data/topologies/campus.yaml`): an illustrative campus modelled on a Nigerian polytechnic. It is not the real YCT network. About 35 devices and 45 links:

- two ISP gateways with 300 and 200 Mbps uplinks;
- an edge router and a firewall;
- two core switches joined at 10 Gb;
- a data-centre switch with six servers: portal, LMS, library, mail, DNS/DHCP and CBT;
- eight distribution switches (ICT, Library, Admin, Technology, Science, Engineering, Hostels, CBT centre), each dual-homed to both cores at 1 Gb;
- access switches and Wi-Fi access points in each zone.

**Traffic model.** For each zone and traffic class, demand = base rate × daily profile × weekly profile × semester growth × scheduled events × random noise. Traffic classes are web, video, e-learning, portal, email, library, CBT exam and bulk (updates and backups). Daily profiles differ by zone:

- academic zones peak 09:00–16:00 on weekdays;
- hostels peak in the evening and at weekends;
- backups run at night.

**Routing.** OSPF-style costs with equal-cost multipath. Traffic fails over when links or devices go down, with a convergence delay of about one cycle.

**Device behaviour.**

- CPU load rises with the traffic passing through a device.
- Error counts rise sharply above 85 % utilisation.
- A reboot resets the device's counters.

**Faults and events.**

- Random link and device failures, with configurable failure and repair times.
- Scheduled events: CBT exam sessions, registration week, a software-update day.
- Data-quality faults (missing samples, counter resets, spikes) so that preprocessing has real work to do.

**Reality gap.** Uneven multipath hashing, protocol overhead, micro-bursts and measurement jitter. These keep the twin from being trivially perfect, so the evaluation measures genuine model error.

**Interfaces.** The feed the twin reads is read-only:

- `GET /v1/snapshot` — counters and device statistics;
- `GET /v1/flows` — flow summaries;
- `GET /v1/events` — event stream.

A separate, token-protected lab interface can:

- inject events;
- change the speed;
- step the clock;
- read ground truth;
- apply configuration changes to the "real network": every Must scenario type and every recommendation action. This is what lets E4 compare the twin's prediction with what actually happens.

Only the command line (`python -m netemu lab ...`) and the evaluation harness use it; the twin never does. `netemu` and `digital_twin` never import each other, which an import-linter contract enforces, so E4 compares two separately written models rather than one codebase against itself.

**Modes:** real time (1×), accelerated (N×), and fast-forward for generating history.

### 7.2 Network adapters (Figure 3.4 process 1.0)

- **Common interface:** `poll()` returns a raw batch, `events()` returns a stream of raw events, and `describe()` reports the source. There is no method for sending commands to devices, and a test enforces this.
- **TelemetryHttpAdapter** (Must): reads the emulator feed.
- **FileImportAdapter** (Must): imports historical monitoring data from CSV or JSON.
- **SnmpAdapter** (Should): read-only SNMP v2c/v3 GET and BULKWALK of IF-MIB (`ifHCInOctets`, `ifHCOutOctets`, `ifOperStatus`, `ifInErrors`) and HOST-RESOURCES-MIB (`hrProcessorLoad`). Interfaces are mapped to links through `NetworkDevice.configuration`. It is tested against an SNMP simulator. Chapter 4 must say plainly that live SNMP was exercised only against that simulator, unless real equipment becomes available.

### 7.3 Preprocessing module (process 2.0)

- Checks required fields and types, and rejects unknown devices or interfaces.
- Computes counter deltas with 64-bit wrap handling. If a counter resets (device uptime went backwards), that interval is dropped and recorded as a gap.
- Converts rates: Mbps = Δoctets × 8 ÷ Δt ÷ 10⁶. Utilisation = max(in, out) ÷ capacity × 100 (§3.6).
- Range checks:
  - utilisation 0–100: values up to 105 are clipped and flagged; anything higher is rejected as a spike;
  - CPU 0–100;
  - errors ≥ 0;
  - timestamps must not be in the future or out of order.
- Drops duplicates, so writes are idempotent.
- Produces a data-quality report for each cycle (accepted, clipped, rejected, gaps). It goes to the logs and the System Status page, and becomes Chapter 4 evidence.

### 7.4 Network model and synchroniser (process 3.0)

- `NetworkModel` holds a NetworkX graph:
  - node attributes: type, role, zone, status, cpu_util, traffic, configuration;
  - edge attributes: link_id, capacity, cost, status, traffic in each direction, utilisation, errors;
  - the current demand matrix alongside the graph.
- It is built from D1 at start-up, seeded from the latest D2 rows, and reloaded when a topology is imported.
- Analytics:
  - a health colour for every element;
  - shortest paths;
  - load bottlenecks (links at 90 % or more);
  - structural bottlenecks: single points of failure (bridges and articulation points) and most-used links (edge betweenness). This delivers Table 3.4's "bottleneck identification". They are returned by `GET topology` and marked on the map with a "single point of failure" badge.
- `snapshot()` returns a deep copy for the simulation engine.

### 7.5 Prediction engine (process 4.0)

- **Task:** forecast the utilisation of every link 5, 10, 15 and 30 minutes ahead.
- **Features** for a link at time t, using past data only:
  - current utilisation;
  - lags of 1–5, 10, 15, 30 and 60 minutes;
  - rolling mean, standard deviation and maximum over 5, 15 and 60 minutes;
  - 15-minute slope;
  - the value at the same time yesterday (full model only; the day of the week is encoded directly, so no week-old lag is needed);
  - time of day and day of week (cyclic encoding), and a weekend flag;
  - link capacity and tier;
  - recent error count;
  - CPU of the two endpoint devices.
- **Models:**
  - RandomForestRegressor is the production model: one multi-output model covers all four horizons (Figures 3.1 and 3.2).
  - Gradient boosting (HistGradientBoostingRegressor, one per horizon) is the compared candidate (Table 3.4).
  - Three baselines: persistence, same time yesterday, and linear trend.
  - Could: MLPRegressor, a small neural network, to connect the results to the neural-network literature in §2.4.
- **One feature function.** Training, serving and E2 all call the same NumPy feature function over a per-link, time-indexed array. A parity test checks that offline and online features match to 1e-6, including gaps and counter resets.
- **Training:**
  - uses the twin-collected history, split by time: the first 10 days train the model and the last 4 days test it (D20);
  - reads history straight into float32 NumPy arrays (`values_list`), never as ORM objects;
  - **predicts the change from now**, u(t+h) − u(t), and adds it to the current utilisation. A tree can only output averages of what it saw in training; predicting the change lets a forecast rise above levels seen before, so a ramping link can be flagged before its first crossing;
  - includes ramp features (5-cycle slope, and "now + slope × horizon" projections for each horizon), and trains on a history that contains congestion ramps. The emulator adds a few seeded flash crowds a day; E3 switches these off and uses different seeds and locations;
  - uses fixed Random Forest settings so the model fits in memory: 100 trees, maximum depth 14, at least 15 samples per leaf, each tree trained on a 20 % sample, 2 parallel jobs. P3's exit check fails any model over 100 MB;
  - **P3 exit test:** a link ramping from about 60 % to about 95 % over 20 minutes must be warned at least 10 minutes before it crosses 90 %;
  - reports feature importance from the forest and permutation importance on a 50,000-row sample, which links to the feature-selection point from Ahmed et al.
- **Serving:**
  - keeps a ring buffer of the last 2 days per link in memory, reloaded from the database at start-up, and forecasts on every cycle;
  - computes confidence from the per-tree predictions (D5) and applies the warning rule (D4);
  - stores model files and their metadata (training window, features, test metrics) in a model registry, and writes `Prediction.model_version`.
- **Retraining:**
  - on demand with `manage.py train_models`, run as a separate low-priority process;
  - a "Retrain now" action on the Administration page (Should) queues the same job;
  - there is no automatic nightly retrain, because training next to the running stack does not fit in 4 GB RAM;
  - a new model is promoted only if its test error is no worse than the current one.

### 7.6 Simulation engine (process 5.0)

**How a run works:**

1. Deep-copy the live model.
2. Apply the proposed change.
3. Route the demand matrix and compute the utilisation of every link.
4. Compare with the baseline (the same copy without the change).
5. Store the result.

**Outputs:**

- utilisation of every link, before and after;
- bottlenecks created and relieved;
- the highest utilisation;
- isolated devices;
- traffic that can no longer be delivered;
- a plain-language summary, for example: "Failing CORE-SW-01↔DIST-LIB moves 410 Mbps onto CORE-SW-02↔DIST-LIB, which reaches 91 %: one new bottleneck."

**Comparison (UC3 extension):** against the baseline stored with the result (the default), or against the live state now.

**Forecast-state option** (Must, because the recommendations need it): run against the forecast load instead of the current load, answering "will this change survive the peak?".

- **How the forecast load is built:** each current demand is scaled by predicted ÷ current utilisation of the busiest link on its path, at the chosen horizon.
- **Logging and checking:** this approximation is logged in the as-built notes, and E4 checks the routed loads against the emulator's ground truth.

**Safety:**

- Runs work only on copies.
- The simulation package imports nothing from the adapters.
- Tests prove that the live model and the emulator are unchanged after a run.

**Speed target:** under 1 s at 40 devices, under 3 s at 200 devices.

| Type | Parameters | Effect on the copy | Tier |
|---|---|---|---|
| traffic_increase | scope (all, zone, device, traffic class, service) and percentage | scales matching demands | Must |
| link_failure | link | removes the link; traffic reroutes | Must |
| device_failure | device | removes the device and its links | Must |
| routing_change | new costs for one or more links | changes path selection | Must |
| reroute_traffic | source, destination, optional traffic class, and the path to use or links to avoid | moves matching traffic onto the chosen path | Must |
| capacity_change | link and new capacity | changes capacity | Must |
| access_control_rule | deny rule: source, destination, optional class | drops matching demand | Must |
| qos_policy | traffic class, limit (Mbps or %), one link or all | caps that class | Must |
| add_link | two devices and a capacity | adds a link | Could |

### 7.7 Recommendations — the "Optimization" half of the title (§3.2)

Recommendations are built in P3, because they depend on alert episodes and forecasts.

1. When a new alert episode starts (once per episode, D22), or when an administrator asks from a link's page, the engine builds candidate fixes for the affected link:
   - raise the link's routing cost to shift traffic elsewhere;
   - reroute the largest flows over the alternative path with the most headroom (NetworkX `shortest_simple_paths`);
   - cap bulk traffic with a QoS policy;
   - upgrade the link to the next capacity tier.
2. Each candidate runs through the simulation engine against the forecast load at the alert's predicted time, built as described under the forecast-state option in §7.6.
3. Candidates that create new bottlenecks or drop traffic are discarded.
4. The remaining **immediate fixes** (routing cost, reroute, QoS) are ranked by least disruption first, then by resulting peak utilisation. A **capacity upgrade** always relieves a link, so it is not ranked against them: it is shown separately as planning advice.
5. The top three immediate fixes and any upgrade advice are shown on the alert, with before/after figures and an "Open in Simulation Console" button. Nothing is ever applied automatically.
6. Recommendations are stored as SimulationScenario and SimulationResult rows owned by a system account, which keeps an audit trail within the six tables.
7. E4 checks them against "reality" with paired runs (§11), and reports the success rate for each action type.

### 7.8 REST API (Django REST Framework, prefix `/api/v1`)

| Area | Endpoints | Who can use them |
|---|---|---|
| Authentication | `POST auth/login`, `POST auth/logout`, `GET auth/me`, `POST auth/password` | everyone |
| Live updates | `GET live` — latest cycle number and network time; tiny, polled every second (D28) | all users |
| Topology | `GET topology` — devices, links, current state, colours, thresholds, structural bottlenecks, last synchronisation | all users |
| Devices and links | `GET/POST/PATCH devices`, `links`; `GET devices/{id}/metrics`, `links/{id}/metrics` (time range and bucket size); `GET links/{id}/forecast` | read: all; write: senior |
| Import | `POST topology/import` (dry run, then commit); `POST monitoring/import` | senior |
| Predictions and alerts | `GET predictions`, `GET alerts/active`, `GET alerts/history`, `GET alerts/{id}/recommendations` | all |
| Simulation | `GET scenario-types` (drives the forms); `GET/POST scenarios`; `POST scenarios/{id}/run`; `GET results/{id}` (polled until complete); `GET results/{id}/compare?against=stored\|live` | read: all; create and run: senior |
| Trends | `GET trends/links` (24 h, 7 d, 14 d, matching the retention in D19; hourly or daily average, 95th percentile, maximum); `GET trends/heatmap`; `GET trends/capacity` (growth rate, days until 90 %); `GET trends/export.csv` | all |
| System | `GET system/status` (engine heartbeat, cycle timings, data source, data quality, active model and its accuracy); `GET settings/thresholds` | all |
| Users | `GET/POST users`, `PATCH users/{id}` (role, active), `POST users/{id}/reset-password` | senior |
| Documentation | `GET schema`, `GET docs` (Swagger UI via drf-spectacular) | logged-in users |

**Input validation:**

- every input goes through a DRF serializer;
- each scenario type has its own parameter schema with bounds;
- uploads have size limits;
- database access goes through the ORM only, so queries are parameterised.

### 7.9 Dashboard (Next.js)

| Page | Contents | Use case |
|---|---|---|
| Login | username and password, clear errors, lockout message | Authenticate (log in) |
| Overview | KPI cards (devices up, links by colour, active warnings, average and peak utilisation); the topology map (colour-coded, with % labels and a legend); utilisation gauges; network trend for the last 60 min; latest alerts; data-source and "last synchronised" indicator, which turns amber when data is stale | UC1 Monitor network topology in real time |
| Device / link detail | side panel plus a full page: status, traffic in/out, utilisation or CPU gauge, errors, configuration (devices), recent trend (60 min, switchable to 6 h, 24 h or 7 d), forecast overlay (links) | UC1 extension: View device / link detail |
| Alerts & predictions | active alerts (link, predicted time, minutes until, confidence band) with recommended fixes; alert history; trend and forecast chart showing the predicted trajectory | UC2 and extension: View trend and forecast chart |
| Simulation console | choose a change type from plain-language cards, fill in a guided form, run it, and see the results: before/after table, bottlenecks created and relieved, a map of the changed network, a summary. Saved scenarios and past runs. Compare with the current state. | UC3 and extension: Compare scenario result with current state |
| Trends & capacity | utilisation over 24 h, 7 d and 14 d; busiest links; an hour-by-weekday heatmap showing quiet maintenance windows; growth rate and the projected date each link reaches 90 %; CSV export | Weakness 3: long-term trend analysis (E9) |
| System (`/system`; administration parts senior only) | engine health and per-step timings, data quality, model accuracy, database, settings; users and roles (managed in the Django admin site), topology import, password change. Named "System" so its path does not clash with Django's `/admin` | §3.8, §1.4 |

**UX rules (NFR3):**

- plain language, with tooltips for technical terms;
- colour is never the only cue: icons, labels and line styles back it up;
- every view has proper loading, empty and error states;
- read-only users never see write controls;
- the layout works at 1366×768, a typical laptop screen.

---

## 8. Security design (NFR4, §3.8)

**Authentication**
- Session login.
- Argon2 password hashing with a unique salt per user.
- Django password validators: minimum length, common-password check, similarity check.
- Login throttling, a 30-minute idle timeout, and logout.

**Authorisation**
- The two roles from D7.
- The rules are enforced by DRF permission classes on the server; the UI hides controls as a convenience only.
- A permission-matrix test covers every endpoint for every role.

**Transport**
- HTTPS through Caddy, with HTTP redirected to HTTPS. HSTS uses a short max-age, because on `localhost` a long one would also lock the development server out of plain HTTP.
- Waitress runs with `trusted_proxy=127.0.0.1` and trusted `X-Forwarded-Proto`/`X-Forwarded-Host`. Otherwise it drops those headers, and Django would think every request was plain HTTP.
- Secure, HttpOnly cookies with CSRF protection, including on the login itself:
  - `GET auth/csrf` sets the token cookie;
  - the login view is CSRF-protected;
  - the dashboard re-reads the token after login, because Django rotates it then;
  - a test checks that a POST without the token gets 403.
- Django's `SECURE_*` settings enabled.

**Admin site**
- The six tables are view-only in the admin: monitoring records, predictions and simulation results are evidence, so nobody can edit them there. The admin is used for users and roles only.
- `/admin` goes through Caddy like the API.
- API schema and documentation pages need a login.

**Lab interface (the emulator, not the twin)**
- The emulator generates a random lab token on first start; there is no built-in default.
- Every lab call is logged with its caller.
- Tests check that no part of the twin mentions the lab interface. An import-linter contract forbids the twin from using the lab client.

**Input**
- Serializer validation and scenario parameter schemas with bounds.
- Topology imports are validated before anything is written.
- ORM-only queries, so no SQL is built by string concatenation.
- React escapes all output; `dangerouslySetInnerHTML` is never used (the theme is set by a small static script file instead).
- A Content Security Policy header limits scripts to the site itself, plus the inline scripts that Next.js pages need. That trade-off is recorded in the as-built notes. It also sets `object-src 'none'` and `frame-ancestors 'none'`.
- Swagger UI assets are served locally (drf-spectacular-sidecar) rather than from a CDN.

**Read-only towards the network**
- Adapters have no write methods.
- SNMP access uses read-only credentials.
- The simulation engine is isolated from the adapters.
- Each of these points is checked by a test (evidence for G3 and §3.8's last sentence).

**Secrets**
- Kept in a `.env` file that is never committed.

**Audit**
- Logins, failed logins, logouts, imports and simulation runs are logged with the user and time.

**Dependencies**
- Pinned versions.
- `pip-audit` and `npm audit` reports go into the evidence pack.

---

## 9. Non-functional requirements — how each is met and measured

| NFR | How we meet it | How we prove it |
|---|---|---|
| NFR1 Responsiveness (≤ 5 s) | Cycle pipeline within 2 s; the 1-second `GET live` check (D28); covering indexes for "latest state" queries | E5: time from `received_at` to the browser showing that cycle's data, over at least 200 samples at both 1× and demo speed, with the full stack running on the Celeron laptop. The maximum must be ≤ 5 s; p50, p95 and the share within 5 s are reported too. Any breach is a defect to fix, not a statistic. |
| NFR2 Reliability | Supervisor auto-restart; adapter reconnect with backoff; each cycle isolated from errors in the others; database reconnect; idempotent writes | E6: 8–12 h soak test with injected faults — uptime, missed cycles, recovery time, no manual steps |
| NFR3 Usability | Administrator-first UI rules (§7.9) | E8: task-based test with the System Usability Scale. We provide the script and form. The students run it with at least five IT or network staff (for example from the college ICT unit) who have no data-science training, recording each one's role and experience. Participants do the UC1–UC3 tasks unaided. Any student participants are reported separately. |
| NFR4 Security | §8 | Security test suite and checklist results |
| NFR5 Modularity | Layered packages; adapter and scenario registries; engine independent of the web layer | import-linter layering contracts pass; a documented walkthrough of adding a new scenario type and a new adapter (files and lines touched) |

---

## 10. Testing strategy (§1.5: unit tests, integration tests)

**Unit tests (pytest)**
- Emulator: traffic shape, counters, events.
- Adapters: interface mapping and the no-write rule.
- Preprocessing: counter wrap and reset, validation rules.
- Network model: synchronisation, health colours, bottlenecks.
- Routing and loads: checked against hand-calculated cases.
- Every scenario type, and the ranking of recommendations.
- Features: a check that no feature uses future data.
- Predictor: output shapes, confidence and warning rules.
- Serializers and permissions.

**Integration tests (pytest-django against a PostgreSQL test database)**
- A full cycle from emulator to database to predictions.
- The event path.
- A simulation job from submission to stored result.
- The API with authentication and both roles.
- Topology import followed by a graph reload.

**Frontend tests**
- Vitest unit tests for the colour scale, number formatting and form validation.
- Playwright end-to-end tests:
  - UC1, UC2 and UC3, each with its extension;
  - login and logout;
  - junior-administrator restrictions.
- The Playwright tests also capture the screenshots for Chapter 4.

**Static checks:** ruff, eslint, TypeScript compiler, import-linter.

**Targets and outputs:** at least 80 % line coverage on the engine packages. JUnit XML and coverage reports are exported to `docs/evidence/` for the Chapter 4 test tables.

---

## 11. Evaluation plan — evidence for Chapter 4 (Objective 6)

The targets are goals. Chapter 4 reports whatever the measurements show.

| ID | What it shows | Method | Metrics | Target |
|---|---|---|---|---|
| E1 | The twin accurately replicates network state (Abstract, G1) | Compare the twin's per-link utilisation and status with the emulator's ground truth over at least 24 h of network time, at the reality-gap presets off (sanity check), default and high | mean and maximum absolute error, status agreement, synchronisation delay | error under 1 percentage point at the default gap; status agrees within one cycle |
| E2 | Forecast accuracy (FR3) | Random Forest vs gradient boosting vs the three baselines, at 5, 10, 15 and 30 min, on the held-out **last 4 days** (Thursday to Sunday). That window includes a weekend and the software-update day, an event the model has never seen. | MAE, RMSE, MAPE (on samples at 10 % utilisation or more), R²; per link tier and for samples at 70 % or more; block-bootstrap intervals by link and day; feature importance; training time; model size; inference time | beat every baseline at every horizon. Vinayakumar et al. is context only: their LSTM ran on real traffic, ours on synthetic data |
| E3 | Problems are flagged before they reach critical levels (Abstract, G2, UC2) | Pre-registered: injected surges in fixed ramp classes (slow, medium, fast), only after the training window, with flash crowds off and seeds and locations unlike training; natural peaks reported separately | **onset** = first of two consecutive ground-truth cycles at or above 90 %; **detected** = a warning on that link 1–35 min before onset; **lead time** = onset − first warning; **false alarm** = an episode with no onset within 35 min. Reported per ramp class: detection rate, lead time (median, 10th percentile), false alarms per episode, error of the predicted problem time, calibration of warning confidence; the linear-trend alarm as a comparison | median lead time of 10 min or more |
| E4 | Safe, accurate change testing (G3, UC3) and recommendations | **Paired runs:** the emulator is forked into identical branches (same random demand) with and without the change, compared at matched network time after routing converges, with at least 10 instances per scenario type, at reality-gap off, default and high, and once with the counter-only demand estimate. A recommendation **succeeds** when the no-action branch congests and the action branch does not. The unchanged check hashes the configuration (topology, costs, capacities, rules), not the traffic. | error per link; precision and recall of the bottleneck set; success rate per action type; unchanged-configuration check; lab-call log showing no call came from the twin | configuration always unchanged |
| E5 | NFR1 responsiveness | Playwright timing from `received_at` to the screen, at 1× and demo speed, with the full stack running | maximum, p50, p95, share within 5 s | maximum ≤ 5 s |
| E6 | NFR2 reliability | Soak test with a schedule of injected faults | uptime, missed cycles, recovery time | recovers with no manual steps |
| E7 | Deployable on modest hardware (G4) and scalability | CPU and RAM per process on the Celeron laptop; round-trip time to the Neon database; database growth per day; API p95 latency with several dashboards open; map render time and simulation time at 40, 100 and 200 devices. Run once with the local database fallback, so the whole system is measured on the laptop; otherwise Chapter 4 states that the database ran on Neon and gives its compute size and storage | resource and timing tables | runs within 4 GB RAM |
| E8 | Usability (NFR3) and functional acceptance | Functional test matrix (every FR and use-case step, pass/fail); SUS questionnaire with at least five IT or network staff without data-science training (§9) | pass rate; SUS score; task success and time | all FR and use-case steps pass |
| E9 | Long-term trend analysis and capacity planning (weakness 3) | The growth rate and "days until 90 %" projected on the Trends page, compared with the growth configured in the emulator (1 % a week) | projected vs configured growth, with an interval; projected vs actual date of crossing for ramped links | configured growth inside the interval |

Every experiment writes JSON, CSV and PNG chart files to `backend/evaluation/results/E*/`. `docs/evidence/CHAPTER4_EVIDENCE.md` collects the headline results in one place.

---

## 12. Environment and deployment

### 12.1 This laptop (development)

**Hardware:** Intel Celeron N4020 (2 cores), 3.8 GB RAM (about 0.2 GB free with the editor and browser open), 41 GB free disk, Windows 11 Home. There is no Docker and no WSL, and Docker is not practical on 4 GB RAM.

**Already installed:** Python 3.13 and 3.12, uv, Node 22.19, npm 11, pnpm, git.

**Still needed:**
- **A Neon project**, which you create (steps below). No local PostgreSQL install is needed.
- **Caddy**, installed through winget, in phase P6.

**Neon setup (one-off, done by you):**
1. Create a project at neon.com with Postgres 17, region AWS Europe (Frankfurt).
2. Set compute to 0.25–1 CU and keep the default scale-to-zero.
3. Copy the direct connection string into `backend/.env` as `DATABASE_URL`, following `backend/.env.example`. Never paste it into chat or commit it.

**Memory plan:**
- No local database server, which saves about 150 MB of RAM.
- Per-process RAM budgets:
  - Digital Twin Engine ≤ 300 MB;
  - API server ≤ 150 MB;
  - emulator ≤ 150 MB.

  A psutil script checks them at the P1, P3 and P5 exits.
- Heavy jobs (frontend builds, model training) run one at a time. Close browser tabs during builds.
- Playwright runs headless with one worker against the static build.

**Windows hygiene (every script and the supervisor):**
- **Encoding:** set `PYTHONUTF8=1`, so output is UTF-8 rather than cp1252.
- **Packages:** set `PYTHONNOUSERSITE=1`. This laptop's global user site holds old Django, pandas and NumPy versions that would otherwise shadow the lock file.
- **Interpreter:** always launch through `.venv\Scripts\python.exe` or `uv run`.
- **Addresses:** use `127.0.0.1` for every internal URL. `localhost` tries IPv6 first and adds delay.
- **Evidence:** `setup.ps1` writes the resolved package versions into the evidence pack.

### 12.2 The students' machine

- **Scripts:** `deploy/setup.ps1` checks prerequisites and then:
  - installs dependencies;
  - checks the connection to Neon and runs migrations;
  - creates the roles and the first senior administrator;
  - loads the topology;
  - generates 14 days of history;
  - trains the models;
  - builds the dashboard.
- **Start and stop:** `start.ps1` and `stop.ps1`. The system opens at `https://localhost`.
- **Minimum specification:** 2 cores, 4 GB RAM, 5 GB disk, Windows 10 or 11, and internet access, because the database is on Neon.
- **Offline fallback (Should):** a portable PostgreSQL on the laptop, switched on by one setting, in case the venue's internet fails during the defence.
- **Instructions:** step by step in `docs/INSTALL.md`.

### 12.3 Defence demo script (`docs/DEMO_SCRIPT.md`)

1. Log in as a senior administrator and walk through the Overview and topology map.
2. Click a link to show its detail and trend.
3. Trigger an exam surge in the emulator from the lab command line ("something is happening in the real network").
4. Show the warning appearing before the link actually congests.
5. Open the forecast chart and the recommended fix.
6. In the Simulation Console, run that fix plus a link-failure scenario, and compare each result with the current state.
7. Show the Trends & capacity page.
8. Log in as a junior administrator to show the read-only restrictions.

---

## 13. Delivery phases

The order follows §1.5. Sizes are relative: S (small), M (medium), L (large).

**Target schedule for the 2-week deadline:**

| Phase | Days |
|---|---|
| P0 | day 1 |
| P1 | days 1–4 |
| P2 | day 5 |
| P3 | days 6–7 |
| P4 | day 8 |
| P5 | days 9–11 |
| P6 | day 12 |
| P7 | days 13–14 |

Should items are attempted only once every Must passes.

| Phase | What gets built | Objectives | Exit criteria | Evidence produced | Size |
|---|---|---|---|---|---|
| **P0 Foundations** | git repository, folder layout, Python environment (uv), Neon database connected, Django project with the six models, migrations and admin, Next.js skeleton, lint and test tooling, settings for D1–D25, data dictionary | — | Tests run; Django works on Neon PostgreSQL; a Next.js page loads | Data dictionary; initial as-built notes | S |
| **P1 Data collection and network model** | Emulator (topology, traffic, faults, feed, lab command line, lab apply-change for every Must type, saved clock); telemetry and file-import adapters; preprocessing; network model and synchroniser; engine loop, event path and persistence; 14-day history | O1, O2 | The twin follows the emulator live; a failure event shows within one poll; RAM budgets met | E1 dry run; data-quality reports | L |
| **P2 Simulation** | Scenario registry with all eight Must types; routing and loads; forecast-state option; results and comparison | O4 | Hand-checked tests pass for every scenario type | E4 dry run against the emulator's apply-change | M–L |
| **P3 Prediction and recommendations** | One feature function with a parity test; training (Random Forest with fixed size limits, gradient boosting, baselines); short-history and full models; model registry; forecasts every cycle; alerts and episodes with hysteresis; recommendations | O3, O4 | Forecasts every cycle within the time budget; model ≤ 100 MB; RAM budgets met | E2 and E3 dry runs; recommendation check | M–L |
| **P4 REST API** | Endpoints including `GET live`, sessions with the poll-aware idle timeout, roles, validation, OpenAPI documentation (self-hosted Swagger assets); Caddy with the final Caddyfile from this phase on, so cookies, CSRF and HTTPS are tested early | O5 (back end) | API tests and the permission matrix pass through Caddy | API reference | M |
| **P5 Dashboard** | All pages in §7.9 | O5 | The Playwright walkthrough of UC1–UC3 and their extensions passes | Screenshots; first NFR1 measurement | L |
| **P6 Hardening and deployment** | HTTPS (Caddy); security settings and tests; supervisor and recovery; setup and start scripts; install and user guides; SNMP adapter (Should); offline database fallback (Should) | NFR2, NFR4 | A fresh install on a new Windows user account works end to end; security tests pass | Security test report; INSTALL.md | M |
| **P7 Evaluation and evidence pack** | Full runs of E1–E8; screenshots; test and coverage reports; as-built ERD, DFD and architecture diagrams; final as-built notes; Chapter 4 evidence summary; outlines for Chapters 4 and 5 | O6 | Every claim in the ledger is either backed by evidence or flagged | Everything Chapter 4 needs | M |

---

## 14. Traceability matrix

| Requirement (source) | Built by | Phase | Verified by |
|---|---|---|---|
| O1 / FR1 — topology as a dynamic graph with node and edge attributes | Network model, six tables, configuration field | P0, P1 | Unit tests; E1 |
| O2 / FR2 — periodic and event-driven synchronisation | Adapter, preprocessing, synchroniser, event listener | P1 | Integration tests; E1 |
| O3 / FR3 — trends, forecasts, lead-time warnings | Prediction engine, alerts | P3 | E2, E3 |
| O4 / FR4 — safe what-if testing, bottlenecks created or relieved | Simulation engine, scenario registry | P2 | Unit tests; E4 |
| O5 / FR5 — web dashboard with a live topology view | API and Next.js pages | P4, P5 | Playwright UC tests; E5 |
| O6 — evaluation | Evaluation harness | P7 | E1–E8 |
| NFR1–NFR5 | §9 | P3–P6 | E5, E6, E8, security suite, import-linter |
| UC1 + View Device / Link Detail | Overview, map, detail panel | P5 | Playwright UC1, UC1-ext |
| UC2 + View Trend and Forecast Chart | Alerts & predictions page, forecast chart | P3, P5 | Playwright UC2, UC2-ext; E3 |
| UC3 + Compare Scenario Result with Current State | Simulation console | P2, P5 | Playwright UC3, UC3-ext; E4 |
| Authenticate (log in) «include» | Login, sessions | P4, P5 | Security suite |
| G1 — live replica | Network model and synchronisation | P1 | E1 |
| G2 — forecasts bound to links, with alerts | Prediction rows per link, alerts | P3 | E3 |
| G3 — detached copy, no write path | Simulation engine isolation | P2 | E4 safety check; static test |
| G4 — affordable, open source, administrator-first | Lean stack, setup scripts, UI rules | all | E7, E8 |
| Weakness 3 — long-term trend analysis | Trends & capacity page | P4, P5 | Playwright; screenshots |
| "Optimization" / recommendations (§3.2) | Recommendation engine | P2, P3 | E4 recommendation check |
| Tables 3.1 and 3.2 | Django models, constraints | P0 | Schema conformance test |
| Figure 3.4 processes 1.0–6.0, stores D1–D4 | §4.3 | P1–P5 | As-built DFD in Chapter 4 |

---

## 15. Notes on the write-up (for the student)

These do not block the build; the software handles each one. Chapter 3 is still editable, so `docs/CHAPTER3_FIXES.md` will give the exact corrections (replacement text and figure changes) for the student to apply.

1. **Use cases vs weaknesses (§3.7).** The text says the three use cases match the three weaknesses, but long-term trend analysis (weakness 3) has no use case. UC1 answers G1 instead. We build a Trends & capacity page. Optionally, add an "Analyse historical trends" use case to Figure 3.5.
2. **"Six tables" (§3.5).** Users and roles also need storage, and `created_by` has no parent table in Figure 3.3. Django's built-in authentication tables cover this; say so in Chapter 4.
3. **MonitoringRecord (Tables 3.1 and 3.2).** Each row holds either a device or a link, but Table 3.2 reads as if it holds both. Implemented as "exactly one of the two".
4. **§3.4 prose vs Figure 3.2.** The prose places the Django backend in the "user interface layer". The figure places it in the "Application and Digital Twin Layer". The code follows the figure.
5. **Figure 3.4.** Several flows are missing, a process and a store need adding, and one flow breaks DFD rules (§4.5 of this plan).
6. **Undefined values.** Thresholds, cycle length, horizons, confidence and minimum history are fixed in §3 of this plan. Chapter 4 must state them.
7. **"Optimization" and "recommendations".** Promised in the title and §3.2 but not designed in Chapter 3. Delivered by §7.7.
8. **Abstract.** It already reports evaluation results in the past tense. Once E1–E4 are done, replace words like "accurately" with the measured figures.
9. **LSTM vs Random Forest.** §2.5 says LSTM performs best, but the system uses Random Forest. Chapter 4 should justify the choice (light enough for G4, no GPU) using E2's comparison.
10. **Random Forest vs "Random Forest and gradient boosting".** Figures 3.1 and 3.2 name only Random Forest; Table 3.4 names both. Random Forest is the production model and gradient boosting the compared candidate.
11. **FR3 says "performance problem".** UC2 and the Prediction table cover link congestion only. Predictive alerts stay link-level; device problems are shown as current state.
12. **Spelling.** Both "utilization" and "utilisation" are used. The tables use British spelling, so use it throughout.
13. **References — please check before submission.**
    - Almasan et al. (2022) exists in IEEE Communications Magazine 60(11), pp. 22–27, but its real title is "Network Digital Twin: Context, Enabling Technologies, and Opportunities", not "...and open research challenges". Check the author list against the paper as well.
    - I could not find Adeyemi and Salami (2010) or Shi et al. (2021) as cited.
    - The "below five percent" MAPE figure attributed to Vinayakumar et al. (2017) should be checked against the paper before Chapter 4 uses it as a benchmark.
14. **Changes from this plan that Chapter 3 should mention.**
    - PostgreSQL is hosted on Neon: affects §3.5, Table 3.4 row 6 and Figure 3.2.
    - The six tables gain the extra fields in D13.
    - There is a fourth use-case area, trend analysis.
    - Flow telemetry (NetFlow-style) joins device and interface metrics as an input (D11): affects §3.4, §3.6 and Figures 3.2 and 3.4.
15. **Table 3.4 row 5.** The reason given for choosing Next.js is "server-side rendering", but the build pre-renders pages to static files and polls the API for live data (D14), to suit modest hardware (G4). Reword the reason to "pre-rendered pages and efficient handling of frequently updating data", or explain the difference in Chapter 4.

---

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| The development laptop is very low-spec (2-core Celeron, 4 GB RAM, about 0.2 GB free) | Slow builds and training; memory pressure | Lean architecture (static frontend, four small processes); float32 data with sampling for training; heavy jobs run one at a time; and this becomes the G4 evidence |
| The database is on Neon, so the system needs internet | The demo fails if the venue's internet fails | Offline fallback database (Should); rehearse at the venue; keep a recorded demo video as a last resort |
| Neon free-plan limits (100 compute-hours a month; 0.5–1 GB storage) | Compute or storage runs out | Retention settings (D19); stop the engine when not in use; watch usage in the Neon console; upgrade the plan if needed |
| Round trip from Lagos to Frankfurt (about 100–150 ms per query, to be measured) | Slower API responses | Few queries per endpoint, bulk writes, a short-lived snapshot cache; E5 and E7 measure the effect |
| 2-week deadline | Features cut | Must / Should / Could tiers (§1.4); evaluation time protected in P7 |
| Version compatibility (Next.js 16, TypeScript, Tailwind 4, React 19) | Build errors | Use the versions create-next-app pins; lock files; upgrades are opt-in only |
| Forecast accuracy falls short of the literature | Weaker Chapter 4 | Strong features, baselines and honest reporting. Weaker results are written up as analysis, never hidden. |
| The twin's traffic model differs from the emulator | Simulation errors | E4 measures it; the reality-gap knobs keep the evaluation honest |
| Scope creep | Late delivery | Must / Should / Could tiers. Should and Could items are built only after all Musts pass. |
| Demo mode's accelerated time is misunderstood | Questions at the defence | The dashboard labels demo mode clearly; the evaluation reports both modes |
| Windows-specific issues (paths, process signals, firewall prompts) | Setup friction | Test on a fresh Windows user account; scripts check prerequisites |
| The students' machine is unknown | Demo failure | Document a minimum spec; the development laptop is itself a worst-case test; provide a rehearsal checklist |
| Agent tooling is slow on this machine (two agents at a time, long answers time out) | Slower reviews | Keep review tasks small and focused; I build sequentially |

---

## 17. Decisions and open items

| # | Question | Answer |
|---|---|---|
| Q1 | Where will the students run the system for the defence? | Their own Windows laptop, installed natively with `setup.ps1` |
| Q2 | Database? | Neon (D24) |
| Q3 | Is Chapter 3 frozen? | No, it is editable; exact fixes go in `docs/CHAPTER3_FIXES.md` |
| Q4 | Deadline for the software? | Within 2 weeks: target 1 November 2026 (§1.4) |
| Q5 | Label the demo network as an illustrative Yabatech-style campus? | Yes, clearly marked "illustrative" (default; say if you prefer a generic name) |
| Q6 | Django or FastAPI? | Django (D25), unless you decide otherwise |
| Q7 | Neon project and `backend/.env` | Your action, needed before the end of P0 (§12.1) |

---

## 18. How we will work

- I build phase by phase in the order above. Each phase ends with passing tests and a short check-in with you, showing what works and what changed.
- Small review agents check each phase against this plan and the write-up. They are kept small because this machine runs only two agents at a time and long agent answers time out.
- Git: a local repository only, with commits at phase checkpoints after your OK. Nothing is pushed anywhere.
- Anything that changes scope comes back to you first. Everything else follows this plan, and deviations are logged in `docs/AS_BUILT_NOTES.md`.

---

## 19. Changes after the design review (v1.2)

Three independent critics reviewed v1.1: fidelity to the write-up, feasibility on this laptop, and evaluation and security. I checked every finding before applying it.

| Finding | Change |
|---|---|
| E4 needs changes applied to the "real network", but the lab could only inject events | Lab apply-change for every Must type and recommendation action (already built in `netemu`); import-linter keeps `netemu` and `digital_twin` apart (§7.1) |
| Simulation depends on flow telemetry that Chapter 3 does not list | Flows logged as an as-built extension; counter-only gravity estimate for SNMP sources (D11, §15 note 14) |
| Access-control and QoS changes are named in §1.2 but were only Should | Promoted to Must (D21) |
| NFR1 is absolute, but E5 accepted the 95th percentile | E5 now passes only if the maximum is ≤ 5 s (§9, §11) |
| Recommendations had no defined forecast load and depended on P3 | Forecast-load rule defined; recommendations moved to P3; forecast-state option promoted to Must (§7.6, §7.7, §13) |
| Retraining and status had no home in the dashboard | System status through D27; "Retrain now" (Should) (§7.5) |
| Structural bottlenecks never reached the screen | Returned by `GET topology` and badged on the map (§7.4, §7.8) |
| As-built DFD list incomplete and partly against DFD rules | Process 7.0 and store D5 added; flows routed through stores (§4.5) |
| Table 3.4 credits server-side rendering, which a static build does not use | §15 note 15; query-string routes (D14) |
| Unbounded Random Forest would need gigabytes of RAM | Fixed size limits, model cap 100 MB, no automatic nightly retrain (§7.5) |
| Demo-speed network time would break validity checks and retention | Network clock is the only timestamp source, resumes and never rewinds (D26) |
| Alerts near the threshold would flap and flood the engine with recommendations | Hysteresis and time-limited recommendations (D22) |
| Polling everything every 2 s is heavy, and polls reset the idle timeout | `GET live` with refetch on change, cached trend views, `X-Poll` header (D28, D8) |
| A static export needs one origin for cookies, and Next.js inline scripts clash with a strict CSP | Caddy from P4; CSP allows inline scripts, with the trade-off logged (§13) |
| Default Argon2 uses 100 MiB per login | 19 MiB, 2 passes, 1 lane (D8) |
| Windows encoding, old global packages and IPv6 `localhost` | Windows hygiene rules (§12.1) |
| Training and serving features could drift apart | One feature function and a parity test (§7.5) |
| A week-old lag feature makes new deployments wait a week | Weekly lag dropped; short-history model (D6) |
| SUS participants might not be the administrators NFR3 names | Recruit IT and network staff (§9, §11) |

**Second review (evaluation and security), applied in v1.3:**

| Finding | Change |
|---|---|
| E1 and E4 were nearly circular: flow records gave every demand's exact traffic | Flows are now sampled 1:100 and exported one cycle late, as real NetFlow is. Results are reported at reality-gap off, default and high. Chapter 4 calls E1 and E4 verification against a reference model, not proof of real-network accuracy |
| A Random Forest cannot forecast levels it never saw, so warnings might never fire | The models predict the change from now; ramp features added; congestion ramps in the training history; P3 exit test for a 10-minute lead (§7.5) |
| Event-driven failures could wait a whole cycle to appear on screen | A state version, bumped after every cycle and every event, drives refetches (D28) |
| E3's terms were undefined | Onset, detection, lead time and false alarm pre-registered; ramp classes fixed; injected surges kept apart from training (§11) |
| E4 mixed model error with demand drift, and counted false alarms as successes | Paired with- and without-change branches on identical demand; success needs the no-action branch to congest; capacity upgrades shown separately (§7.7, §11) |
| The idle timeout would log out a dashboard left watching, and polls rewrote the session row | 12 h read-only session; writes need recent activity; polls never touch the session (D8) |
| Waitress drops proxy headers; login had no CSRF protection; HSTS on localhost breaks development | Trusted-proxy settings, CSRF-protected login, short HSTS (§8) |
| Seniors could edit evidence tables in the admin; API docs were public | Admin view-only for the six tables; docs need login; django-axes lockout (§8) |
| Weakness 3 had no experiment, and a 30-day view could never fill | Trend views 24 h / 7 d / 14 d; new experiment E9 checks the growth projection |
| E2's test window and events did not match the plan | Last 4 days (Thursday to Sunday) with the software-update day moved inside them |
| E7 did not count the database's resources | Run once with the local fallback, or state Neon's size explicitly |
| The lab token had a fixed default | Random token created at first start, every lab call logged, a fifth import contract (§8) |

**Found while building P3 (v1.3):**

| Finding | Change |
|---|---|
| The P3 exit test failed: a ramp to congestion was warned only 3 minutes ahead | Diagnosed minute by minute. The ramp was visible after about 4 minutes, but the regression forest forecast almost no change, because in ordinary traffic a slope is usually noise. Warnings now come from a Random Forest classifier with balanced class weights, trained on "reaches 90 % within h" labels. Training history has 4 flash crowds a day. The exit test now passes with at least 10 minutes' lead (D4, D5) |

**Found while building P5 and checking the first end-to-end run (v1.4):**

| Finding | Change |
|---|---|
| Next.js 16 "Cache Components" cannot be combined with a static export (the build stops at export) | Cache Components and Partial Prefetching are switched off; the dashboard fetches everything in the browser anyway (D14) |
| The dashboard used the `src/` folder layout | Standard Next.js layout at the frontend root (`app/`, `components/`, `lib/`), as the user asked |
| After 30 minutes away, anyone could open one page (activity) and then make changes | Reading is allowed, but changes stay locked until the password is confirmed; covered by a test (D8) |
| `auth/password` could be used to guess a password with a stolen session (django-axes guards only the login form) | Rate-limited to 10 checks an hour per user (§8) |
| The audit trail in §8 had not been built | Sign-ins (and failures), sign-outs, password checks, topology edits and imports, scenario changes and simulation requests go to `var/log/audit.log`; passwords are never written (§8) |
| A theme script used `dangerouslySetInnerHTML`, which §8 rules out | Replaced by a small static script file |
| The first training history mixed two emulator configurations and only 7 days: 8 congestion events to learn from, and the whole weekend in the test period | Regenerate 14 consistent days with the final configuration before training (D20) |
| "Same time yesterday" compared Monday with Sunday and Saturday with Friday, so a Monday-morning ramp was forecast to fall | "Yesterday" is the previous day of the same type (Monday → Friday, Saturday → previous Sunday); the engine keeps 7 days in memory (D6) |
| Balanced class weights on the 4-output classifier multiplied, putting all the weight on 24 samples; probabilities were poorly calibrated | No class weights; the warning threshold is chosen on the last 20 % of the training period and stored with the model (D4, D5) |
| About a quarter of live cycles were missed at 20× speed on the busy laptop, silently | Missed cycles are counted, logged and shown; a cycle is published before recommendations, which now run on a worker thread (§4.3) |
| The engine had no automated test | Integration test with an in-process emulator behind its real HTTP feed: storage, state version, missed cycles, recommendations off the cycle (§10) |

**Found while building P6 (v1.4, continued):**

| Finding | Change |
|---|---|
| Django's default user admin lets anyone who may change users tick "superuser" | Seniors give accounts the two roles only; superuser, raw permissions, other groups and superuser accounts are out of their reach (§8) |
| On Windows, replacing a file fails while another program reads it: this stopped a history run (emulator clock) and the supervisor (its state file) | Writers retry and otherwise skip one update; readers retry; neither can stop the system |
| After an emulator restart its numbering started again, so the adapter would wait for numbers that never came | The emulator resumes its cycle numbers; the adapter notices a restart and reads the new records |
| Caddy's automatic trust install opens a Windows dialog and holds Caddy until it is answered | `skip_install_trust`; `setup.ps1` runs `caddy trust` once |
| A CPU-heavy recommendation thread still slows the cycle (Python runs one thread at a time) | Recommendations are worked out only between cycles |

**Found while preparing the evaluation (P7, v1.5):**

| Finding | Change |
|---|---|
| The traceability matrix promised a schema conformance test for Tables 3.1 and 3.2, but there was none | `tests/integration/test_schema.py` reads the live PostgreSQL catalogue: the six tables, every principal field, the primary keys, the Table 3.2 foreign keys, PROTECT on delete. It found that Django's foreign keys are checked at commit (deferred), so the test checks them immediately |
| Adapters were said to plug in "through registries", but `run_twin` built the HTTP adapter directly | An adapter registry with `run_twin --adapter`; a test checks that every registered adapter is read-only and complete (NFR5, G3) |
| NFR5 asks for a documented extension walkthrough | `docs/EXTENDING.md`: a scenario type and an adapter added on a copy of the repository and tested — 7 files, 123 lines, no change to the engine, API or dashboard |
| §6.3 promised a data dictionary | `docs/DATA_DICTIONARY.md`, taken from the models |
| §8 promised dependency audits | `docs/evidence/P6_dependency_audit.txt`. The audit found one Python advisory (certifi), fixed by upgrading to 2026.10.19. The npm findings are in a development-only lint tool |
| Chapter 4 needs the as-built figures | `docs/diagrams/`: architecture, DFD, ERD and use cases, in the style of Chapter 3, with additions dashed |
| E8 had no tooling | `evaluation/e8_functional_matrix.py` (requirement → tests, walkthrough steps, experiments; pass/fail) and `evaluation/e8_sus.py` with `docs/evaluation/E8_USABILITY_KIT.md` |
| The local database restarted on a new random port, so the services would never find it again after the E6 outage fault | `localpg.py` reuses its previous port (tested on a scratch database) |
| A resumed emulator restarted its traffic calendar, so growth reset and the first days' events happened again | The saved clock keeps the calendar's origin; a test covers it. The stored history predates the fix, which is stated in AS_BUILT_NOTES |
| E9's first quick run showed the Trends page reporting −39 % a week on a campus growing 1 % a week: a plain line is pulled by where the quieter weekends fall | The capacity fit gives each day of the week its own level (growth = each weekday against the same weekday a week earlier), and the projection starts from the busiest level; a test covers it |
| The E3 review found that the protocol was rewritten (and its hash changed) on every run, that a killed run could leave a passing verdict, and that the plan's false-alarm definition had been narrowed | A frozen protocol file with its hash checked at start-up and its amendments listed; a separate run registration; results.json only at the end; the plan's false-alarm definition as the headline; per-class calibration; the most lead possible measured from the first reading that contains the surge |
| E7 measured memory as the working set (psutil rss), which Windows trims and compresses when RAM is short: the engine showed 47 MB while holding 262 MB | E6 and E7 record committed (private) memory and judge the budgets on it; the working set is kept beside it. With the right measure the API (about 340 MB) is over its 150 MB budget |
| Every Next.js prefetch was a 404 behind Caddy: the static export writes `/x/__next.<group>/x/__PAGE__.txt`, the browser asks for `/x/__next.<group>.x.__PAGE__.txt` | Two rewrites in the Caddyfile; the screenshot run checks that no page logs an error |
| E4 found that the recommendation engine kept fixes that changed nothing (a routing cost on a link with no other path), because the forecast load alone was below the threshold; the alert's forecast was 20–44 points below the real peak | Every immediate fix is also tested with the link at full load, and must take at least 5 points off it; a test covers it |

**Supervisor's corrections after the seminar (v1.6, 26 October 2026):**

| Finding | Change |
|---|---|
| The supervisor asked for the Research Gap to be in Chapter Two, and not as a table | §2.6 Research Gap is now prose, with G1–G4 named in the text. The old §2.6 Summary is §2.7, the old §3.1.3 Conceptual Model is §3.1.2, and Chapter 3's tables are now 3.1–3.4 (database tables, relationships, use cases, technology stack). Figure 3.1's gap column is headed "(from Section 2.6)". Every reference in the repository was renumbered, then audited against the corrected document |
| The audit found section references from an earlier numbering: the requirements cited as §3.4.1/§3.4.2 (they are in §3.3), the database tables as §3.6 (§3.5), the data flow as §3.5 (§3.6) and the gaps as §3.2 (§2.6) | Corrected in the E8 matrix and the documents |
| Two gap statements cited studies for claims that Table 2.1 does not support: Ahmed et al. (2016), an anomaly-detection survey, for forecasting; Shi et al. (2021), whose twin does test configurations, for "no facility for testing a change" | Each citation now supports only what Table 2.1 says of that study |
| Moving text pushed three figure captions onto the next page: the Caption style keeps with the next paragraph, which suits table captions (above their tables) but drags a figure caption away from its image | Each figure image keeps with its caption, and figure captions no longer keep with the next paragraph |
| A cloud copy was asked for: the API on Modal and the dashboard on Vercel, always on while the project is developed | `deploy/modal_app.py`: one Modal container runs PostgreSQL, the emulator, the engine and the API, with the database dumped to a Modal volume every 10 minutes; Neon's free plan was rejected because a twin that writes every minute would use up its monthly compute in about 16 days. The dashboard is built as a normal Next.js app on Vercel and forwards the Django paths to Modal (`frontend/next.config.ts`). See `docs/CLOUD.md` |
