// Shapes of the Django REST API responses (backend/apps/api/views).

export type Health = "green" | "yellow" | "red" | "down" | "unknown";
export type Role = "senior" | "junior" | "none";
export type RunState = "queued" | "running" | "completed" | "failed";

export interface Thresholds {
  warning_pct: number;
  critical_pct: number;
}

export interface User {
  username: string;
  full_name: string;
  role: Role;
  is_staff: boolean;
  write_allowed: boolean;
}

export interface Live {
  state_version: number;
  last_cycle: string | null;
  network_time: string | null;
  mode: "live" | "stepped" | null;
  speed: number | null;
  engine_state: string;
  last_error: string;
  stale: boolean;
  poll_seconds: number;
}

export interface ForecastPoint {
  horizon_minutes: number;
  predicted_pct: number;
  confidence: number;
  warning: boolean;
}

export interface TopologyDevice {
  device_id: number;
  name: string;
  device_type: string;
  ip_address: string | null;
  location: string;
  status: string;
  role: string;
  zone: string;
  position: [number, number] | null;
  cpu_util: number | null;
  traffic_in: number | null;
  traffic_out: number | null;
  health: Health;
  single_point_of_failure: boolean;
}

export interface TopologyLink {
  link_id: number;
  source_id: number;
  dest_id: number;
  label: string;
  capacity_mbps: number;
  status: string;
  utilisation_pct: number | null;
  traffic_out: number | null;
  traffic_in: number | null;
  error_count: number | null;
  health: Health;
  single_point_of_failure: boolean;
  most_used: boolean;
  forecast: ForecastPoint[];
  warning: { horizon_minutes: number; confidence: number; predicted_pct: number } | null;
}

export interface Topology {
  state_version: number;
  last_cycle: string | null;
  thresholds: Thresholds;
  devices: TopologyDevice[];
  links: TopologyLink[];
  summary: {
    devices_up: number;
    devices_total: number;
    links_total: number;
    links_by_health: Partial<Record<Health, number>>;
    average_utilisation_pct: number | null;
    peak_link: { link_id: number; label: string; utilisation_pct: number } | null;
    links_warned: number;
    links_critical_now: number;
  };
  horizons_minutes: number[];
}

export interface Recommendation {
  result_id: number;
  scenario_id: number;
  title: string;
  advice: "immediate" | "planning";
  rank: number | null;
  scenario_type: string;
  parameters: Record<string, unknown>;
  summary: string;
  link_after_pct: number | null;
  max_after: { link_id: number; label: string; pct: number } | null;
}

export interface Episode {
  link_id: number;
  started_at: string;
  last_warning_at: string;
  predicted_time: string;
  horizon_minutes: number;
  confidence: number;
  peak_predicted: number;
  critical_now: boolean;
  ended_at: string | null;
}

export interface ActiveAlert extends Episode {
  label: string;
  current_pct: number | null;
  minutes_until: number | null;
  kind: "critical_now" | "predicted";
  confidence_band: "High" | "Medium" | "Low";
  trajectory: ForecastPoint[];
  recommendations: Recommendation[];
}

export interface ActiveAlerts {
  generated_at: string | null;
  thresholds: Thresholds;
  model: string | null;
  model_kind: "short" | "full" | null;
  /** when the model in use was trained (server clock, UTC) */
  model_trained_at?: string | null;
  history_cycles: number | null;
  short_model_needs: number | null;
  alerts: ActiveAlert[];
}

export interface AlertHistory {
  hours: number;
  episodes: (Episode & { label: string; active: boolean })[];
}

export interface SeriesPoint {
  t: string;
  utilisation_pct: number | null;
  max_utilisation_pct: number | null;
  traffic_in: number | null;
  traffic_out: number | null;
  error_count: number | null;
  cpu_util: number | null;
  status: string | null;
}

export interface LinkForecast {
  link_id: number;
  label: string;
  capacity_mbps: number;
  generated_at: string | null;
  thresholds: Thresholds;
  model_version: string | null;
  history: SeriesPoint[];
  forecast: (ForecastPoint & { t: string })[];
}

export interface Metrics {
  hours: number;
  thresholds: Thresholds;
  points: SeriesPoint[];
}

export interface DeviceRecord {
  device_id: number;
  name: string;
  device_type: string;
  ip_address: string | null;
  location: string;
  status: string;
  configuration: Record<string, unknown>;
}

export interface LinkRecord {
  link_id: number;
  source_device: number;
  dest_device: number;
  capacity_mbps: number;
  status: string;
  routing_cost: number | null;
  label: string;
}

export interface FieldSpec {
  name: string;
  label: string;
  type: "number" | "link" | "links" | "device" | "destination" | "zone" | "class" | "link_costs";
  required: boolean;
  min?: number;
  max?: number;
}

export interface ScenarioType {
  key: string;
  label: string;
  description: string;
  fields: FieldSpec[];
  tier: string;
}

export interface ScenarioTypes {
  types: ScenarioType[];
  choices: {
    devices: { device_id: number; name: string; device_type: string; zone: string }[];
    links: { link_id: number; label: string; capacity_mbps: number; cost: number }[];
    zones: string[];
    classes: string[];
  };
}

export interface Scenario {
  scenario_id: number;
  scenario_name: string;
  scenario_type: string;
  parameters: Record<string, unknown>;
  created_by: string;
  created_at: string;
  runs: number;
}

export interface ResultListItem {
  result_id: number;
  scenario: number;
  scenario_name: string;
  scenario_type: string;
  status: RunState;
  requested_at: string;
  executed_at: string | null;
  run_by: string | null;
  summary: string;
}

export interface LinkOutcome {
  link_id: number;
  label: string;
  capacity_mbps: number;
  observed_pct: number | null;
  before_pct: number;
  after_pct: number;
  delta_pct: number;
  status_after: string;
  overloaded: boolean;
}

export interface ResultSummary {
  /** what the run asked for; a recommendation's own run stores only its basis ("forecast +30 min") */
  request?: { basis: string; horizon_minutes?: number };
  error?: string;
  scenario_type?: string;
  parameters?: Record<string, unknown>;
  basis?: string;
  network_time?: string | null;
  thresholds?: Thresholds;
  calibration_factor?: number;
  links?: LinkOutcome[];
  bottlenecks_before?: number[];
  bottlenecks_after?: number[];
  created?: number[];
  relieved?: number[];
  max_before?: { link_id: number; label: string; pct: number };
  max_after?: { link_id: number; label: string; pct: number };
  isolated_devices?: number[];
  undeliverable_mbps_before?: number;
  undeliverable_mbps_after?: number;
  model_fidelity_mae_pct?: number | null;
  notes?: string[];
  summary?: string;
}

export interface SimulationResult {
  result_id: number;
  scenario: number;
  scenario_name: string;
  scenario_type: string;
  status: RunState;
  requested_at: string;
  executed_at: string | null;
  run_by: string | null;
  predicted_utilisation: Record<string, number> | null;
  bottleneck_links: { link_id: number; label: string; utilisation_pct: number }[] | null;
  result_summary: ResultSummary | null;
}

export interface Comparison {
  result_id: number;
  against: "stored" | "live";
  basis: string | null;
  summary: string | null;
  created: number[];
  relieved: number[];
  links: {
    link_id: number;
    label: string;
    baseline_pct: number | null;
    after_pct: number;
    change_pct: number | null;
    status_after: string;
    overloaded: boolean;
  }[];
}

export interface Paged<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type TrendRange = "24h" | "7d" | "14d";

export interface LinkTrendSummary {
  link_id: number;
  label: string;
  avg_pct: number | null;
  p95_pct: number | null;
  max_pct: number | null;
  share_elevated_pct: number | null;
}

export interface LinkTrends {
  range: TrendRange;
  thresholds: Thresholds;
  links?: LinkTrendSummary[];
  bucket?: string;
  link_id?: number;
  points?: { t: string; avg_pct: number | null; p95_pct: number | null; max_pct: number | null }[];
}

export interface NetworkTrend {
  hours: number;
  /** "10 minutes" or "1 hour"; null when every cycle is a point */
  bucket?: string | null;
  thresholds?: Thresholds;
  points: { t: string; avg_pct: number | null; max_pct: number | null }[];
}

export interface Heatmap {
  link_id: number | null;
  thresholds?: Thresholds;
  cells: { weekday: number; hour: number; avg_pct: number | null }[];
}

export interface CapacityRow {
  link_id: number;
  label: string;
  days_of_data: number;
  /** the last complete WAT day fitted (YYYY-MM-DD), the day of latest_daily_p95_pct */
  latest_day?: string;
  latest_daily_p95_pct: number;
  growth_pts_per_week: number | null;
  growth_pct_per_week: number | null;
  days_until_critical: number | null;
  fitted_p95_now?: number;
  projected_date: string | null;
}

export interface Capacity {
  thresholds?: Thresholds;
  method?: string;
  links: CapacityRow[];
}

export interface ModelInfo {
  kind: "short" | "full";
  version: string;
  created_at: string | null;
  window: Record<string, string> | null;
  rows: Record<string, number> | null;
  mae_by_horizon: Record<string, number>;
  persistence_mae_by_horizon: Record<string, number>;
  warning_quality: Record<string, { precision: number; recall: number }>;
  warning_threshold: number | null;
  size_bytes: number | null;
}

export interface EngineStatus {
  state?: string;
  last_error?: string;
  heartbeat?: string;
  started_at?: string;
  cycles_stored?: number;
  last_cycle?: string | null;
  last_received_at?: string | null;
  timings?: Record<string, number>;
  data_quality?: Record<string, number>;
  source?: { name?: string; mode?: string; speed?: number; time?: string; cycle_seconds?: number };
  recent_events?: { type: string; element: string; network_time: string; applied_ms: number }[];
  simulations_run?: number;
  recommendations_made?: number;
  forecasting?: {
    active_model: string | null;
    model_kind: string | null;
    history_cycles: number;
    short_model_needs: number;
    full_model_needs: number | null;
    available: string[];
    active_alerts: Episode[];
  } | null;
  traffic_classes?: string[];
  state_version?: number;
  cycles_missed?: number;
  recommendations_pending?: number;
  /** devices or links changed in the Topology Store after the engine started: it must be restarted to use them */
  topology_changed?: boolean;
  stale: boolean;
}

export interface SystemStatus {
  engine: EngineStatus;
  models: ModelInfo[];
  /** `exact_tables`: the tables whose row count is exact; the others are PostgreSQL's estimate */
  database: { size_bytes: number; approximate_rows: Record<string, number>; exact_tables?: string[]; server: string };
  thresholds: Thresholds;
}

export interface Settings extends Thresholds {
  cycle_seconds: number;
  horizons_minutes: number[];
  warning_probability: number;
  monitoring_retention_days: number;
  prediction_retention_days: number;
  poll_seconds: number;
  time_zone: string;
}

export interface UserRow {
  username: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login: string | null;
}

export interface ImportReport {
  ok: boolean;
  dry_run: boolean;
  errors: string[];
  devices_created: number;
  devices_updated: number;
  links_created: number;
  links_updated: number;
  /** links not imported because a device at one end is decommissioned (one plain sentence each) */
  links_skipped?: string[];
  /** the engine needs a restart to use the import (or would, after a check); false when only map positions change */
  restart_needed?: boolean;
}
