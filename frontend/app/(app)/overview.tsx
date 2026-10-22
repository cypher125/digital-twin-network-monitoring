"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { DataTable, type Column } from "@/components/DataTable";
import { SeriesTable, TimeSeriesChart, type SeriesDef, type TimePoint } from "@/components/charts";
import { MapLegend, TopologyMap } from "@/components/TopologyMap";
import { AlertSummary } from "@/components/alerts";
import { Card, ErrorNote, HealthBadge, Loading, Meter, StatTile, ToneIcon, useViewToggle } from "@/components/ui";
import { fmtCapacity, fmtDateTime, fmtMbps, fmtPct, HEALTH } from "@/lib/format";
import { useActiveAlerts, useNetworkTrend, useTopology } from "@/lib/queries";
import type { Topology, TopologyLink } from "@/lib/types";

const TREND_SERIES: SeriesDef[] = [
  { key: "avg_pct", label: "Average of all links", colour: "series-1" },
  { key: "max_pct", label: "Busiest link", colour: "series-2" },
];

// Below Tailwind's sm breakpoint (640px) the whole campus drawing is too small to read or tap, so the map
// card starts on its table there.
const PHONE_WIDTH = "(width < 40rem)";

export function Overview() {
  const topology = useTopology();
  const alerts = useActiveAlerts();
  const trend = useNetworkTrend(6);
  const trendView = useViewToggle();
  const [phone, setPhone] = useState(false);
  const phoneFound = useRef(false);

  // Checked after the first render, because the page is prerendered with no screen to measure, and only
  // once, so a view chosen afterwards with the card's own toggle stays.
  useEffect(() => {
    if (window.matchMedia(PHONE_WIDTH).matches && !phoneFound.current) {
      phoneFound.current = true;
      setPhone(true);
    }
  }, []);

  const trendData: TimePoint[] = useMemo(
    () => (trend.data?.points ?? []).map((p) => ({ t: new Date(p.t).getTime(), avg_pct: p.avg_pct, max_pct: p.max_pct })),
    [trend.data],
  );

  if (topology.isPending) return <Loading label="Loading the network…" />;
  if (topology.error || !topology.data) return <ErrorNote error={topology.error} title="Could not load the network" />;
  const data = topology.data;
  const s = data.summary;
  const byHealth = s.links_by_health;
  const devicesDown = data.devices.filter((d) => d.status === "down").length;
  // the rest have never reported (status unknown): no data, not out of service
  const devicesSilent = s.devices_total - s.devices_up - devicesDown;
  const devicesDetail =
    [devicesDown ? `${devicesDown} out of service` : null, devicesSilent ? `${devicesSilent} not reporting` : null]
      .filter(Boolean)
      .join(", ") || "all in service";
  const busiest = [...data.links]
    .filter((l) => l.utilisation_pct != null && l.status !== "down")
    .sort((a, b) => (b.utilisation_pct ?? 0) - (a.utilisation_pct ?? 0))
    .slice(0, 8);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-ink">Network overview</h1>
          <p className="text-sm text-ink-2">
            {data.last_cycle ? `Latest measurements: ${fmtDateTime(data.last_cycle)} (West Africa Time)` : "Waiting for the first measurements…"}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Devices up"
          value={`${s.devices_up} of ${s.devices_total}`}
          tone={devicesDown ? "down" : devicesSilent ? "unknown" : "good"}
          detail={devicesDetail}
        />
        <StatTile label="Average link utilisation" value={fmtPct(s.average_utilisation_pct)} detail={`across ${s.links_total} links`} />
        <StatTile
          label="Busiest link"
          value={fmtPct(s.peak_link?.utilisation_pct)}
          detail={s.peak_link?.label ?? "–"}
          href={s.peak_link ? `/link?id=${s.peak_link.link_id}` : undefined}
          tone={s.peak_link ? HEALTH[data.links.find((l) => l.link_id === s.peak_link?.link_id)?.health ?? "unknown"].tone : undefined}
        />
        <StatTile
          label="Links at warning level"
          value={byHealth.yellow ?? 0}
          tone={(byHealth.yellow ?? 0) > 0 ? "warning" : "good"}
          detail={`${data.thresholds.warning_pct}% to ${data.thresholds.critical_pct}% utilisation`}
        />
        <StatTile
          label="Links congested now"
          value={s.links_critical_now}
          tone={s.links_critical_now > 0 ? "critical" : "good"}
          detail={`${data.thresholds.critical_pct}% utilisation or more`}
        />
        <StatTile
          label="Congestion predicted"
          value={s.links_warned}
          tone={s.links_warned > 0 ? "serious" : "good"}
          detail="within the next 30 minutes"
          href="/alerts"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* a new key starts the card again on its table once a phone screen is found */}
        <MapCard key={phone ? "phone" : "wide"} topology={data} start={phone ? "table" : "chart"} />
        <div className="space-y-4 xl:col-span-4">
          <Card
            title="Predictive alerts"
            subtitle={`Links likely to reach ${data.thresholds.critical_pct}% within 30 minutes`}
            actions={
              <Link href="/alerts" className="text-xs text-accent-ink hover:underline">
                All alerts
              </Link>
            }
          >
            {alerts.data ? <AlertSummary data={alerts.data} limit={5} /> : alerts.error ? <ErrorNote error={alerts.error} /> : <Loading />}
          </Card>
          <Card title="Busiest links now">
            <ul className="space-y-2.5">
              {busiest.map((link) => (
                <li key={link.link_id}>
                  <Link href={`/link?id=${link.link_id}`} className="group block">
                    <div className="mb-1 flex items-center gap-2 text-xs">
                      <ToneIcon tone={HEALTH[link.health].tone} size={13} />
                      <span className="truncate text-ink group-hover:underline">{link.label}</span>
                      <span className="num ml-auto font-medium text-ink">{fmtPct(link.utilisation_pct)}</span>
                    </div>
                    <Meter value={link.utilisation_pct} tone={HEALTH[link.health].tone} label={`${link.label} utilisation`} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Card title="Network utilisation, last 6 hours" actions={trendView.toggle}>
        {trend.error ? (
          <ErrorNote error={trend.error} />
        ) : trend.isPending ? (
          <Loading />
        ) : trendView.view === "chart" ? (
          <TimeSeriesChart data={trendData} series={TREND_SERIES} thresholds={data.thresholds} height={240} />
        ) : (
          <SeriesTable data={trendData} series={TREND_SERIES} />
        )}
      </Card>
    </div>
  );
}

/** The live map, or the same links as a table; `start` is the view it opens with. */
function MapCard({ topology, start }: { topology: Topology; start: "chart" | "table" }) {
  const view = useViewToggle(start);
  return (
    <Card
      className="xl:col-span-8"
      title="Live network map"
      subtitle="Colour shows current utilisation. Point at a link or device for details; click to open it."
      actions={view.toggle}
    >
      {view.view === "chart" ? (
        <>
          <TopologyMap topology={topology} />
          <div className="mt-3">
            <MapLegend thresholds={topology.thresholds} />
          </div>
        </>
      ) : (
        <LinksTable links={topology.links} critical={topology.thresholds.critical_pct} />
      )}
    </Card>
  );
}

/** `critical`: the configured critical threshold, which the forecast warnings are about. */
function LinksTable({ links, critical }: { links: TopologyLink[]; critical: number }) {
  const columns: Column<TopologyLink>[] = [
    {
      key: "label",
      header: "Link",
      sort: (l) => l.label,
      cell: (l) => (
        <Link href={`/link?id=${l.link_id}`} className="text-accent-ink hover:underline">
          {l.label}
        </Link>
      ),
    },
    { key: "health", header: "Status", sort: (l) => l.utilisation_pct ?? -1, cell: (l) => <HealthBadge health={l.health} /> },
    { key: "util", header: "Utilisation", numeric: true, sort: (l) => l.utilisation_pct, cell: (l) => fmtPct(l.utilisation_pct) },
    { key: "capacity", header: "Capacity", numeric: true, sort: (l) => l.capacity_mbps, cell: (l) => fmtCapacity(l.capacity_mbps) },
    { key: "out", header: "Traffic out", numeric: true, sort: (l) => l.traffic_out, cell: (l) => fmtMbps(l.traffic_out) },
    { key: "in", header: "Traffic in", numeric: true, sort: (l) => l.traffic_in, cell: (l) => fmtMbps(l.traffic_in) },
    {
      key: "warning",
      header: "Forecast",
      sort: (l) => (l.warning ? l.warning.horizon_minutes : 999),
      cell: (l) =>
        l.warning ? (
          <span className="inline-flex items-center gap-1">
            <ToneIcon tone="serious" size={13} />
            {critical}% within {l.warning.horizon_minutes} min
          </span>
        ) : (
          <span className="text-ink-2">no congestion expected</span>
        ),
    },
    { key: "spof", header: "Backup path", sort: (l) => (l.single_point_of_failure ? 0 : 1), cell: (l) => (l.single_point_of_failure ? "none" : "yes") },
  ];
  return <DataTable rows={links} columns={columns} rowKey={(l) => l.link_id} initialSort={{ key: "util", desc: true }} maxHeight={560} caption="All links" />;
}
