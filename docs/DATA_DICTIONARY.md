# Data dictionary

These are the six application tables of Figure 3.3 and Table 3.1, as built in PostgreSQL.
- Column names and types are copied from the Django models (`backend/apps/twin/models.py`) as the migrations create them.
- The schema conformance tests (`backend/tests/integration/test_schema.py`) check them against the live database.
- Fields marked **\*** are additions to Table 3.1's principal fields (plan D13). Each one is explained in `AS_BUILT_NOTES.md` §1.

**Conventions:**
- Units: Mbps for traffic and capacity, percent from 0 to 100, and confidence from 0 to 1.
- All timestamps are `timestamptz`, stored in UTC. `timestamp` and `generated_at` are network time from the data source. `received_at` and `requested_at` are wall-clock time.
- Every foreign key uses `ON DELETE PROTECT`, so history cannot be lost. Devices and links are retired by setting `status = 'decommissioned'`, and users are deactivated, never deleted.

## NetworkDevice (`network_device`) — D1 Topology Store, the nodes of the graph

| Column | Type | Null | Description |
|---|---|---|---|
| device_id | bigint, PK | no | Identifier |
| name | varchar(100), unique | no | Device name, e.g. `CORE-SW-01` |
| device_type | varchar(20) | no | One of router, switch, firewall, server, access_point, wan_gateway |
| ip_address | inet, unique | yes | Management address |
| location | varchar(120) | no (may be empty) | Building or zone |
| status | varchar(20) | no | up, down, unknown or decommissioned; default unknown |
| configuration\* | jsonb | no | Role, zone, vendor and model, interface-to-link map, map position, ACL and QoS settings (FR1 "configuration for nodes") |

## NetworkLink (`network_link`) — D1 Topology Store, the edges of the graph

| Column | Type | Null | Description |
|---|---|---|---|
| link_id | bigint, PK | no | Identifier |
| source_device_id | bigint, FK → network_device | no | One end; traffic_out on this link is source → destination |
| dest_device_id | bigint, FK → network_device | no | The other end |
| capacity_mbps | double precision | no | Link capacity in Mbps |
| status | varchar(20) | no | up, down, unknown or decommissioned; default unknown |
| routing_cost\* | double precision | yes | Routing (OSPF-style) cost; empty means reference bandwidth ÷ capacity (10,000 ÷ capacity_mbps) |

**Constraints:**
- `networklink_capacity_positive`: capacity_mbps > 0.
- `networklink_distinct_endpoints`: source and destination differ.
- `networklink_unique_pair`: at most one link per pair of devices, in either direction.

## MonitoringRecord (`monitoring_record`) — D2 Monitoring Records, the time series

One row per device or per link per monitoring cycle.

| Column | Type | Null | Description |
|---|---|---|---|
| record_id | bigint, PK | no | Identifier |
| device_id | bigint, FK → network_device | yes | Set on device rows |
| link_id | bigint, FK → network_link | yes | Set on link rows |
| timestamp | timestamptz | no | Measurement time (end of the cycle, network time) |
| traffic_in | double precision | yes | Mbps; on a link destination → source, on a device the total in over its interfaces |
| traffic_out | double precision | yes | Mbps; on a link source → destination, on a device the total out |
| utilisation_pct | double precision | yes | Link rows: max(in, out) ÷ capacity × 100 |
| error_count | integer ≥ 0 | yes | Interface errors during the cycle |
| cpu_util | double precision | yes | Device rows: CPU load, % |
| status\* | varchar(20) | no (may be empty) | The element's status at that time (availability history) |
| received_at\* | timestamptz | yes | When the adapter received the data (wall clock), used to measure NFR1 |

**Constraints:**
- `monitoringrecord_device_xor_link`: exactly one of device_id and link_id is set.
- `monitoringrecord_unique_link_ts` and `monitoringrecord_unique_device_ts`: one row per element per timestamp, so repeated ingestion never creates duplicates. Each is a partial unique index that also serves the "latest state" and history queries.
- Range checks: `monitoringrecord_utilisation_range` (0–100) and `monitoringrecord_cpu_range` (0–100).

**Index:** `monitoringrecord_ts_brin`, a BRIN index on timestamp, used for retention and long trend scans.

## Prediction (`prediction`) — D3 Predictions

One row per link, per forecast horizon, per cycle.

| Column | Type | Null | Description |
|---|---|---|---|
| prediction_id | bigint, PK | no | Identifier |
| link_id | bigint, FK → network_link | no | The forecast link |
| generated_at | timestamptz | no | The cycle that produced the forecast (network time) |
| horizon_minutes | smallint > 0 | no | 5, 10, 15 or 30 |
| predicted_utilisation | double precision | no | Forecast utilisation, %, from the regression forest |
| confidence_score | double precision, 0–1 | no | Agreement of the forest's trees (D5); shown as High, Medium or Low |
| is_warning | boolean | no | The warning classifier predicts the link will reach 90 % within this horizon (D4) |
| model_version\* | varchar(64) | no | Which trained model produced the row |

**Constraints:**
- `prediction_unique_link_time_horizon`: one row per (link, generated_at, horizon).
- `prediction_confidence_range`: 0–1.
- `prediction_horizon_positive`: horizon > 0.

**Indexes:**
- `prediction_generated_brin` (BRIN on generated_at).
- `prediction_warning_idx`: a partial index on warning rows, newest first, used by the alerts page.

## SimulationScenario (`simulation_scenario`) — D4 Scenarios and Results

| Column | Type | Null | Description |
|---|---|---|---|
| scenario_id | bigint, PK | no | Identifier |
| created_by | integer, FK → auth_user | no | The administrator who defined it. The column name follows Figure 3.3 exactly |
| scenario_name | varchar(120) | no | Name given by the administrator |
| scenario_type | varchar(30) | no | traffic_increase, link_failure, device_failure, routing_change, reroute_traffic, capacity_change, access_control_rule, qos_policy or add_link (D21) |
| parameters | jsonb | no | The change, validated against the type's parameter schema |
| created_at | timestamptz | no | When it was defined |

**Rule:** once a scenario has results, it cannot be edited; it is copied instead. So every result matches the parameters that produced it.

## SimulationResult (`simulation_result`) — D4 Scenarios and Results

One row per run of a scenario.

| Column | Type | Null | Description |
|---|---|---|---|
| result_id | bigint, PK | no | Identifier |
| scenario_id | bigint, FK → simulation_scenario | no | The scenario that was run |
| executed_at | timestamptz | yes | When the run finished (empty while queued or running) |
| predicted_utilisation | jsonb | no | {link_id: utilisation %} for every link after the change |
| bottleneck_links | jsonb | no | The links at or above the critical threshold (90 %) after the change |
| result_summary | jsonb | no | Summary text plus the stored baseline, bottlenecks created and relieved, changes per link, undeliverable traffic, and the thresholds and parameters used |
| status\* | varchar(20) | no | queued, running, completed or failed (the run queue) |
| run_by_id\* | integer, FK → auth_user | yes | Who asked for the run; the system account for recommendations |
| requested_at\* | timestamptz | no | When the run was requested |

**Index:** `simulationresult_queue_idx`, a partial index on queued runs, oldest first. The engine takes the next run from it.

## Relationships (Table 3.2, plus two implied by Chapter 3)

| Parent | Child | Through | Cardinality |
|---|---|---|---|
| NetworkDevice | NetworkLink | source_device_id, dest_device_id | 1 : N (each, "connects") |
| NetworkDevice | MonitoringRecord | device_id | 1 : N ("is monitored by") |
| NetworkLink | MonitoringRecord | link_id | 1 : N ("is monitored by") |
| NetworkLink | Prediction | link_id | 1 : N ("is forecast by") |
| SimulationScenario | SimulationResult | scenario_id | 1 : N ("produces") |
| User (auth_user) | SimulationScenario | created_by | 1 : N ("creates") — implied by Figure 3.3 |
| User (auth_user) | SimulationResult | run_by_id | 1 : N ("runs") — added |

## Other tables (not part of Figure 3.3)

| Table | Owner | Purpose |
|---|---|---|
| `auth_user`, `auth_group`, `auth_user_groups`, … | Django | Accounts and the Senior and Junior roles (store D5 in the as-built DFD). Passwords are Argon2 hashes |
| `django_session` | Django | Signed-in sessions (12 hours; a Senior Administrator must have been active in the last 30 minutes to make changes) |
| `axes_accessattempt`, `axes_accessfailurelog`, `axes_accesslog`, … | django-axes | Failed sign-ins and lock-outs (NFR4) |
| `dt_runtime_cache` | Django database cache | The engine's published status: state version, last cycle, timings, active model. The dashboard reads it through `GET live` once a second |
| `django_migrations`, `django_admin_log`, `django_content_type`, `auth_permission` | Django | Framework bookkeeping |
