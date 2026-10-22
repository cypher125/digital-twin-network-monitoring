import type { Health, Thresholds } from "./types";

// Times are stored in UTC and shown in West Africa Time (plan decision D18).
export const TIME_ZONE = "Africa/Lagos";

const timeFormat = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" });
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const dayFormat = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, weekday: "short", day: "numeric", month: "short" });
const dateFormat = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, day: "numeric", month: "short", year: "numeric" });

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

export const fmtTime = (value: string | number | Date | null | undefined) => (value == null ? "–" : timeFormat.format(toDate(value)));
export const fmtDateTime = (value: string | number | Date | null | undefined) =>
  value == null ? "–" : dateTimeFormat.format(toDate(value));
export const fmtDay = (value: string | number | Date | null | undefined) => (value == null ? "–" : dayFormat.format(toDate(value)));
export const fmtDate = (value: string | number | Date | null | undefined) => (value == null ? "–" : dateFormat.format(toDate(value)));

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "–";
  return `${value.toFixed(digits)}%`;
}

export function fmtSignedPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±";
  return `${sign}${Math.abs(value).toFixed(digits)} pts`;
}

export function fmtMbps(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(2)} Gbps`;
  if (Math.abs(value) >= 100) return `${value.toFixed(0)} Mbps`;
  return `${value.toFixed(1)} Mbps`;
}

export function fmtCapacity(mbps: number): string {
  return mbps >= 1000 ? `${(mbps / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1 })} Gbps` : `${mbps} Mbps`;
}

export function fmtNumber(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "–";
  return value.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Compact counts for tiles and axes: 1,284 / 12.9K / 4.2M. */
export function fmtCompact(value: number | null | undefined): string {
  if (value == null) return "–";
  if (Math.abs(value) < 10_000) return value.toLocaleString("en-GB");
  return new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function fmtMinutes(minutes: number | null | undefined): string {
  if (minutes == null) return "–";
  if (minutes <= 0) return "now";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** Minutes between two timestamps (b − a). */
export function minutesBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null;
  return (new Date(b).getTime() - new Date(a).getTime()) / 60_000;
}

/** The D1 thresholds, for the moments before the server has sent the configured ones. */
export const DEFAULT_THRESHOLDS: Thresholds = { warning_pct: 70, critical_pct: 90 };

// Colour coding of section 3.7 with the D1 thresholds. Colour is never the only cue:
// every status is shown with its icon and its label. The descriptions give the default
// thresholds; where the configured ones are known, use healthDescription.
export const HEALTH: Record<Health, { label: string; tone: Tone; description: string }> = {
  green: { label: "Normal", tone: "good", description: "below 70% utilisation" },
  yellow: { label: "Warning", tone: "warning", description: "70% to 90% utilisation" },
  red: { label: "Critical", tone: "critical", description: "90% utilisation or more" },
  down: { label: "Down", tone: "down", description: "out of service" },
  unknown: { label: "No data", tone: "unknown", description: "no recent reading" },
};

/** What a status means, with the configured thresholds: "below 70% utilisation", "out of service". */
export function healthDescription(health: Health, thresholds: Thresholds = DEFAULT_THRESHOLDS): string {
  const { warning_pct: warning, critical_pct: critical } = thresholds;
  if (health === "green") return `below ${warning}% utilisation`;
  if (health === "yellow") return `${warning}% to ${critical}% utilisation`;
  if (health === "red") return `${critical}% utilisation or more`;
  return HEALTH[health].description;
}

export type Tone = "good" | "warning" | "serious" | "critical" | "down" | "unknown" | "info";

export function healthOf(value: number | null | undefined, status = "up", warning = 70, critical = 90): Health {
  if (status === "down") return "down";
  if (value == null) return "unknown";
  if (value >= critical) return "red";
  if (value >= warning) return "yellow";
  return "green";
}

/**
 * Short wording for the engine state (`engine_state` from `live`, `state` in the engine
 * status); show the full state text alongside, for example as a tooltip. `stale`: the
 * engine says it is running but no new cycle has been stored for a while.
 */
export function engineBadge(state: string, stale: boolean): { tone: Tone; label: string } {
  if (state === "running") return stale ? { tone: "warning", label: "Data delayed" } : { tone: "good", label: "Live" };
  if (state === "starting") return { tone: "info", label: "Starting" };
  // demo mode: the test harness moves the clock between cycles; simulations are still served
  if (state.startsWith("paused: the data source clock is stepped")) return { tone: "info", label: "Stepped" };
  if (state.startsWith("paused")) return { tone: "warning", label: "Paused" };
  if (state.startsWith("waiting")) return { tone: "warning", label: "Waiting for data" };
  if (state === "error") return { tone: "critical", label: "Engine error" };
  return { tone: "critical", label: "Engine stopped" }; // "stopped", or "not running" (no engine status at all)
}

export const DEVICE_TYPES: Record<string, string> = {
  router: "Router",
  switch: "Switch",
  firewall: "Firewall",
  server: "Server",
  access_point: "Access point",
  wan_gateway: "WAN gateway (ISP)",
};

export const ROLE_LABEL: Record<string, string> = {
  senior: "Senior Administrator",
  junior: "Junior Administrator",
  none: "No role",
};

export function confidenceBand(confidence: number): "High" | "Medium" | "Low" {
  return confidence >= 0.8 ? "High" : confidence >= 0.6 ? "Medium" : "Low";
}

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
