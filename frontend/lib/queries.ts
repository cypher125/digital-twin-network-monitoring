"use client";

// Data hooks. The dashboard polls one small endpoint (`live`) every second; every
// other view is keyed by the engine's state version, so it is fetched again only
// when the twin has stored something new (plan decision D28). Earlier data stays
// on screen while the next version loads, so charts never flash empty. Only a view's
// own earlier data is reused: after the element (or the period) changes, the view
// shows its loading state rather than another element's figures under the new name.

import { hashKey, keepPreviousData, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { get, qs } from "./api";
import type {
  ActiveAlerts,
  AlertHistory,
  Capacity,
  Comparison,
  DeviceRecord,
  Heatmap,
  LinkForecast,
  LinkRecord,
  LinkTrends,
  Live,
  Metrics,
  NetworkTrend,
  Paged,
  ResultListItem,
  Scenario,
  ScenarioTypes,
  Settings,
  SimulationResult,
  SystemStatus,
  Topology,
  TrendRange,
  User,
  UserRow,
} from "./types";

export function useLive() {
  return useQuery({
    queryKey: ["live"],
    queryFn: ({ signal }) => get<Live>("live", { poll: true, signal }),
    refetchInterval: (query) => (query.state.data?.poll_seconds ?? 1) * 1000,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export function useStateVersion(): number {
  return useLive().data?.state_version ?? 0;
}

/** True when `cachedKey` is `key` followed by a state version: the same view, at some version. */
function isVersionOf(cachedKey: readonly unknown[], key: readonly unknown[]): boolean {
  return cachedKey.length === key.length + 1 && hashKey(cachedKey.slice(0, -1)) === hashKey(key);
}

/** The newest cached state version of a view (the version is the last part of its key). */
function newestCached<T>(client: QueryClient, key: readonly unknown[]): T | undefined {
  let best: { version: number; data: T } | undefined;
  for (const [cachedKey, data] of client.getQueriesData<T>({ queryKey: key })) {
    if (data === undefined || !isVersionOf(cachedKey, key)) continue;
    const version = Number(cachedKey[cachedKey.length - 1]);
    if (!best || version > best.version) best = { version, data };
  }
  return best?.data;
}

/**
 * A GET that is refreshed whenever the twin's state version changes. A page opened
 * between cycles shows the newest cached version at once while the current one loads.
 */
function useVersioned<T>(key: readonly unknown[], path: string, enabled = true) {
  const version = useStateVersion();
  const client = useQueryClient();
  return useQuery({
    queryKey: [...key, version],
    queryFn: ({ signal }) => get<T>(path, { poll: true, signal }),
    // TanStack offers the data this hook showed last, whatever its key (another device after
    // ?id= changed, or another period): keep it only when it is an earlier version of this view.
    // Generic, like TanStack's keepPreviousData, so that useQuery takes the data type from
    // queryFn (with a plain `T` here TypeScript infers the data type from this function).
    placeholderData: <D>(previous: D | undefined, previousQuery: { queryKey: readonly unknown[] } | undefined) =>
      (previousQuery && isVersionOf(previousQuery.queryKey, key) ? previous : undefined) ?? newestCached<D>(client, key),
    staleTime: Infinity,
    gcTime: 120_000,
    enabled,
  });
}

/**
 * A GET that only changes when its inputs change (or slowly, for heavy trend queries).
 * No placeholder: when an input changes, the previous answer belongs to another element
 * (or period), so the view shows its loading state until its own data arrives.
 */
function useStatic<T>(key: readonly unknown[], path: string, enabled = true, staleTime = 60_000) {
  return useQuery({
    queryKey: key,
    queryFn: ({ signal }) => get<T>(path, { poll: true, signal }),
    staleTime,
    enabled,
  });
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    // an automatic request (D8): real use of the page is reported by AuthGate's activity ping,
    // so neither this fetch nor a refetch after the network comes back keeps write access alive
    queryFn: ({ signal }) => get<User>("auth/me", { poll: true, signal }),
    retry: false,
    staleTime: 60_000,
    refetchOnReconnect: false,
  });
}

export const useTopology = () => useVersioned<Topology>(["topology"], "topology");
export const useActiveAlerts = () => useVersioned<ActiveAlerts>(["alerts", "active"], "alerts/active");
export const useAlertHistory = (hours: number) =>
  useVersioned<AlertHistory>(["alerts", "history", hours], `alerts/history${qs({ hours })}`);

export const useLinkForecast = (id: number | null, hours: number) =>
  useVersioned<LinkForecast>(["link-forecast", id, hours], `links/${id}/forecast${qs({ hours })}`, id != null);
export const useLinkMetrics = (id: number | null, hours: number) =>
  useVersioned<Metrics & { link_id: number; label: string; capacity_mbps: number }>(
    ["link-metrics", id, hours],
    `links/${id}/metrics${qs({ hours })}`,
    id != null,
  );
export const useDeviceMetrics = (id: number | null, hours: number) =>
  useVersioned<Metrics & { device_id: number; name: string }>(
    ["device-metrics", id, hours],
    `devices/${id}/metrics${qs({ hours })}`,
    id != null,
  );
export const useLink = (id: number | null) => useStatic<LinkRecord>(["link", id], `links/${id}`, id != null, 30_000);
export const useDevice = (id: number | null) => useStatic<DeviceRecord>(["device", id], `devices/${id}`, id != null, 30_000);

/** The whole-network trend up to 24 hours, refreshed every cycle; `enabled: false` while the page shows something else. */
export const useNetworkTrend = (hours: number, enabled = true) =>
  useVersioned<NetworkTrend>(["network-trend", hours], `trends/network${qs({ hours })}`, enabled);
/**
 * The whole-network trend over more than 24 hours (up to 336, in hourly buckets). A heavy query that
 * changes slowly, so, like the link trends, it is not keyed by the state version (the API caches it too).
 */
export const useNetworkTrendLong = (hours: number, enabled = true) =>
  useStatic<NetworkTrend>(["network-trend-long", hours], `trends/network${qs({ hours })}`, enabled, 300_000);
export const useLinkTrends = (range: TrendRange, link: number | null) =>
  useStatic<LinkTrends>(["trends", range, link], `trends/links${qs({ range, link })}`, true, 300_000);
export const useHeatmap = (link: number | null) =>
  useStatic<Heatmap>(["heatmap", link], `trends/heatmap${qs({ link })}`, true, 600_000);
export const useCapacity = () => useStatic<Capacity>(["capacity"], "trends/capacity", true, 600_000);

export const useScenarioTypes = () => useStatic<ScenarioTypes>(["scenario-types"], "scenario-types", true, 30_000);

/** The newest `limit` saved scenarios; `count` says how many there are in all. */
export function useScenarios(limit = 100) {
  return useQuery({
    queryKey: ["scenarios", limit],
    queryFn: ({ signal }) => get<Paged<Scenario>>(`scenarios${qs({ limit })}`, { poll: true, signal }),
    staleTime: 5_000,
    // a longer list of the same scenarios ("Show older"): keep the shorter one on screen while it loads
    placeholderData: keepPreviousData,
  });
}

// recommendation scenarios belong to the system user, so ask for them too (a recommendation's result links to its scenario)
export const useScenario = (id: number | null) =>
  useStatic<Scenario>(["scenario", id], `scenarios/${id}?include=recommendations`, id != null, 5_000);

/** Recent runs (of one scenario, or of all), fetched again while any of them is waiting or running. */
export function useResults(scenario?: number | null) {
  return useQuery({
    queryKey: ["results", scenario ?? null],
    queryFn: ({ signal }) => get<Paged<ResultListItem>>(`results${qs({ scenario, limit: 50 })}`, { poll: true, signal }),
    staleTime: 2_000,
    // queued runs are picked up by the engine within about a second (D10)
    refetchInterval: (query) => (query.state.data?.results.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
}

export function useResult(id: number | null) {
  return useQuery({
    queryKey: ["result", id],
    queryFn: ({ signal }) => get<SimulationResult>(`results/${id}?include=recommendations`, { poll: true, signal }),
    enabled: id != null,
    // queued runs are picked up by the engine within about a second (D10)
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1000 : false;
    },
  });
}

export const useComparison = (id: number | null, against: "stored" | "live", ready: boolean) =>
  useVersioned<Comparison>(["compare", id, against], `results/${id}/compare${qs({ against, include: "recommendations" })}`, id != null && ready);

export const useSystemStatus = () => useVersioned<SystemStatus>(["system-status"], "system/status");
export const useSettings = () => useStatic<Settings>(["settings"], "settings", true, Infinity);
export const useUsers = (enabled: boolean) => useStatic<UserRow[]>(["users"], "users", enabled, 30_000);
