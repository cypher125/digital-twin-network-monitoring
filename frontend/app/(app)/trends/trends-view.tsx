"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { HeatmapTable, SeriesTable, TimeSeriesChart, UtilisationHeatmap, type SeriesDef, type TimePoint } from "@/components/charts";
import { DataTable } from "@/components/DataTable";
import { Download } from "@/components/icons";
import { Card, ErrorNote, Loading, PageHeader, Segmented, StatusBadge, useViewToggle } from "@/components/ui";
import { fmtDate, fmtPct, fmtSignedPct, healthOf, HEALTH } from "@/lib/format";
import { useCapacity, useHeatmap, useLinkTrends, useNetworkTrend, useNetworkTrendLong, useTopology } from "@/lib/queries";
import type { CapacityRow, LinkTrendSummary, TrendRange } from "@/lib/types";

const RANGE_OPTIONS: { value: TrendRange; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "14d", label: "14 days" },
];
const RANGE_HOURS: Record<TrendRange, number> = { "24h": 24, "7d": 168, "14d": 336 };

const LINK_SERIES: SeriesDef[] = [
  { key: "avg", label: "Average", colour: "series-1" },
  { key: "p95", label: "95th percentile", colour: "series-2" },
];
const NETWORK_SERIES: SeriesDef[] = [
  { key: "avg", label: "Average of all links", colour: "series-1" },
  { key: "max", label: "Busiest link", colour: "series-2" },
];

/**
 * How far ahead the projection reaches the critical level, in whole days, rounded as the server
 * rounds the projected date (so "4 days" and the date four days on always agree).
 */
function daysAhead(days: number): string {
  if (days === 0) return "already";
  const whole = Math.round(days);
  return whole < 1 ? "under a day" : whole === 1 ? "1 day" : `${whole} days`;
}

export function TrendsView() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const range = (RANGE_OPTIONS.find((o) => o.value === search.get("range"))?.value ?? "7d") as TrendRange;
  const link = Number(search.get("link")) || null;
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(search.toString());
    if (value == null) next.delete(key);
    else next.set(key, value);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  const topology = useTopology();
  const summary = useLinkTrends(range, null);
  const series = useLinkTrends(range, link);
  // the whole network over the chosen period, fetched only while it is shown: 24 hours follows every
  // cycle; the hourly 7 and 14 days are heavy and change slowly, so they are fetched at most every 5 minutes
  const recent = useNetworkTrend(24, range === "24h" && !link);
  const long = useNetworkTrendLong(RANGE_HOURS[range], range !== "24h" && !link);
  const network = range === "24h" ? recent : long;
  const heatmap = useHeatmap(link);
  const capacity = useCapacity();
  const seriesView = useViewToggle();
  const heatView = useViewToggle();
  const period = RANGE_OPTIONS.find((o) => o.value === range)?.label;
  const thresholds = topology.data?.thresholds ?? summary.data?.thresholds;
  // capacity planning is worked out with the thresholds sent alongside it
  const planning = capacity.data?.thresholds ?? thresholds;
  const critical = planning?.critical_pct ?? 90;
  const linkLabel = link ? topology.data?.links.find((l) => l.link_id === link)?.label ?? `link ${link}` : null;

  const chart = useMemo(() => {
    if (link && series.data?.points) {
      return { data: series.data.points.map<TimePoint>((p) => ({ t: new Date(p.t).getTime(), avg: p.avg_pct, p95: p.p95_pct })), defs: LINK_SERIES };
    }
    return { data: (network.data?.points ?? []).map<TimePoint>((p) => ({ t: new Date(p.t).getTime(), avg: p.avg_pct, max: p.max_pct })), defs: NETWORK_SERIES };
  }, [link, series.data, network.data]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Trends and capacity planning"
        description="Long-term utilisation, the weekly pattern and growth per link, to plan upgrades before links become bottlenecks."
        actions={
          <a
            href={`/api/v1/trends/export.csv?range=${range}`}
            className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
          >
            <Download size={14} /> Export CSV
          </a>
        }
      />

      {/* filters for every chart below, in one row */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
        <Segmented label="Period" value={range} onChange={(value) => setParam("range", value)} options={RANGE_OPTIONS} />
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Link
          <select className="field w-auto min-w-64" value={link ?? ""} onChange={(e) => setParam("link", e.target.value || null)}>
            <option value="">Whole network</option>
            {(topology.data?.links ?? [])
              .slice()
              .sort((a, b) => a.label.localeCompare(b.label))
              .map((l) => (
                <option key={l.link_id} value={l.link_id}>
                  {l.label}
                </option>
              ))}
          </select>
        </label>
      </div>

      <Card
        title={link ? `${linkLabel}: utilisation over ${period}` : `Whole network: last ${period}`}
        subtitle={
          link
            ? `Averaged per ${series.data?.bucket ?? "interval"}`
            : `${network.data?.bucket ? `Averaged per ${network.data.bucket}. ` : ""}Choose a link above to see its own history over the same period`
        }
        actions={seriesView.toggle}
      >
        {(link ? series.error : network.error) ? (
          <ErrorNote error={link ? series.error : network.error} />
        ) : (link ? series.isPending : network.isPending) ? (
          <Loading />
        ) : seriesView.view === "chart" ? (
          <TimeSeriesChart data={chart.data} series={chart.defs} thresholds={thresholds} height={280} />
        ) : (
          <SeriesTable data={chart.data} series={chart.defs} />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Busiest links" subtitle={`Ranked by 95th-percentile utilisation over ${period}`}>
          {summary.error ? (
            <ErrorNote error={summary.error} />
          ) : summary.isPending ? (
            <Loading />
          ) : (
            <DataTable<LinkTrendSummary>
              rows={summary.data?.links ?? []}
              rowKey={(l) => l.link_id}
              maxHeight={420}
              initialSort={{ key: "p95", desc: true }}
              onRowClick={(l) => setParam("link", String(l.link_id))}
              columns={[
                { key: "label", header: "Link", sort: (l) => l.label, cell: (l) => <span className="text-accent-ink">{l.label}</span> },
                { key: "avg", header: "Average", numeric: true, sort: (l) => l.avg_pct, cell: (l) => fmtPct(l.avg_pct) },
                { key: "p95", header: "95th pct", numeric: true, sort: (l) => l.p95_pct, cell: (l) => fmtPct(l.p95_pct) },
                { key: "max", header: "Peak", numeric: true, sort: (l) => l.max_pct, cell: (l) => fmtPct(l.max_pct) },
                {
                  key: "share",
                  header: `Time ≥ ${thresholds?.warning_pct ?? 70}%`,
                  numeric: true,
                  sort: (l) => l.share_elevated_pct,
                  cell: (l) => fmtPct(l.share_elevated_pct),
                },
              ]}
            />
          )}
        </Card>
        <Card
          title={`Weekly pattern${link ? `: ${linkLabel}` : ""}`}
          subtitle="Always the last 14 days, whatever the period above. Average utilisation by weekday and hour (WAT); cells near the 0% end of the key are the quiet hours for maintenance."
          actions={heatView.toggle}
        >
          {heatmap.error ? (
            <ErrorNote error={heatmap.error} />
          ) : heatmap.isPending ? (
            <Loading />
          ) : heatView.view === "chart" ? (
            <UtilisationHeatmap cells={heatmap.data?.cells ?? []} />
          ) : (
            <HeatmapTable cells={heatmap.data?.cells ?? []} />
          )}
        </Card>
      </div>

      <Card
        title="Capacity planning"
        subtitle={`Always the last 14 days, whatever the period above. ${capacity.data?.method ?? "Linear fit of the daily 95th-percentile utilisation"}, projected to the ${critical}% critical threshold.`}
      >
        {capacity.error ? (
          <ErrorNote error={capacity.error} />
        ) : capacity.isPending ? (
          <Loading />
        ) : (
          <DataTable<CapacityRow>
            rows={capacity.data?.links ?? []}
            rowKey={(l) => l.link_id}
            maxHeight={460}
            initialSort={{ key: "days" }}
            columns={[
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
              {
                key: "now",
                // today is left out until it is over: a part-day 95th percentile covers only some hours
                header: "Last full day, 95th pct",
                numeric: true,
                sort: (l) => l.latest_daily_p95_pct,
                cell: (l) => <span title={l.latest_day ? `95th percentile on ${fmtDate(l.latest_day)}` : undefined}>{fmtPct(l.latest_daily_p95_pct)}</span>,
              },
              {
                key: "growth",
                header: "Growth per week",
                numeric: true,
                sort: (l) => l.growth_pts_per_week,
                cell: (l) => fmtSignedPct(l.growth_pts_per_week, 2),
              },
              {
                key: "days",
                header: `Reaches ${critical}% in`,
                numeric: true,
                sort: (l) => l.days_until_critical,
                cell: (l) =>
                  l.days_until_critical == null ? (
                    <span className="text-ink-2">not on current trend</span>
                  ) : (
                    daysAhead(l.days_until_critical)
                  ),
              },
              { key: "date", header: "Projected date", sort: (l) => l.projected_date, cell: (l) => fmtDate(l.projected_date) },
              {
                key: "status",
                header: "Status",
                sort: (l) => l.latest_daily_p95_pct,
                cell: (l) => {
                  const health = healthOf(l.latest_daily_p95_pct, "up", planning?.warning_pct, planning?.critical_pct);
                  const soon = l.days_until_critical != null && l.days_until_critical <= 90;
                  return soon && health === "green" ? <StatusBadge tone="serious" label="Plan an upgrade" /> : <StatusBadge tone={HEALTH[health].tone} label={HEALTH[health].label} />;
                },
              },
              { key: "data", header: "Days of data", numeric: true, sort: (l) => l.days_of_data, cell: (l) => l.days_of_data },
            ]}
          />
        )}
        <p className="mt-3 text-xs text-ink-2">
          A projection needs at least three days of data and assumes growth continues in a straight line; treat it as an early hint, not a promise.
        </p>
      </Card>
    </div>
  );
}
