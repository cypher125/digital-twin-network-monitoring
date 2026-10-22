"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { AlertCard } from "@/components/alerts";
import { SeriesTable, TimeSeriesChart, type SeriesDef, type TimePoint } from "@/components/charts";
import { DataTable } from "@/components/DataTable";
import { Button, Card, ErrorNote, HealthBadge, KeyValues, Loading, Notice, PageHeader, Segmented, StatTile, ToneIcon, useViewToggle } from "@/components/ui";
import { patch } from "@/lib/api";
import { confidenceBand, fmtCapacity, fmtMbps, fmtNumber, fmtPct, HEALTH, healthDescription } from "@/lib/format";
import { useActiveAlerts, useLink, useLinkForecast, useMe, useTopology } from "@/lib/queries";
import type { LinkRecord } from "@/lib/types";

const RANGES = [
  { value: 1, label: "1 h" },
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 168, label: "7 days" },
];

// Display words for the stored status; the editor offers the same words.
const STATUS_LABEL: Record<string, string> = { up: "Up", down: "Down", unknown: "Unknown", decommissioned: "Decommissioned" };

export function LinkDetail() {
  const id = Number(useSearchParams().get("id")) || null;
  const [hours, setHours] = useState(6);
  const topology = useTopology();
  const forecast = useLinkForecast(id, hours);
  const alerts = useActiveAlerts();
  const me = useMe();
  const chartView = useViewToggle();
  const trafficView = useViewToggle();

  const link = topology.data?.links.find((l) => l.link_id === id);
  const bucketed = hours > 6;

  const { utilData, utilSeries, trafficData, now, projected } = useMemo(() => {
    const history = forecast.data?.history ?? [];
    const points: TimePoint[] = history.map((p) => ({
      t: new Date(p.t).getTime(),
      utilisation: p.utilisation_pct,
      peak: bucketed ? p.max_utilisation_pct : null,
    }));
    const last = points.length ? points[points.length - 1] : null;
    const projection = forecast.data?.forecast ?? [];
    // the forecast covers 30 minutes, so it is drawn on the 1 h, 6 h and 24 h views only
    const projected = last != null && projection.length > 0 && hours <= 24;
    if (last && projected) {
      last.forecast = last.utilisation; // the projection starts at the latest measurement
      for (const p of projection) points.push({ t: new Date(p.t).getTime(), forecast: p.predicted_pct });
    }
    const series: SeriesDef[] = [{ key: "utilisation", label: bucketed ? "Average utilisation" : "Utilisation", colour: "series-1" }];
    if (bucketed) series.push({ key: "peak", label: "Peak in each interval", colour: "series-2" });
    if (projected) series.push({ key: "forecast", label: "Forecast", colour: "series-1", projection: true });
    const traffic: TimePoint[] = history.map((p) => ({ t: new Date(p.t).getTime(), out: p.traffic_out, in: p.traffic_in }));
    return { utilData: points, utilSeries: series, trafficData: traffic, now: projected ? last?.t ?? null : null, projected };
  }, [forecast.data, bucketed, hours]);

  if (id == null) return <ErrorNote error="No link was chosen." title="Link not found" />;
  if (topology.isPending) return <Loading />;
  // a failed request is not a missing link
  if (!topology.data) return <ErrorNote error={topology.error} title="Could not load the network" />;
  if (!link) return <ErrorNote error="This link does not exist or has been retired." title="Link not found" />;
  const thresholds = topology.data.thresholds;
  const critical = thresholds.critical_pct;
  const alert = alerts.data?.alerts.find((a) => a.link_id === id);
  const plus30 = link.forecast.find((f) => f.horizon_minutes === 30);
  const source = topology.data.devices.find((d) => d.device_id === link.source_id);
  const dest = topology.data.devices.find((d) => d.device_id === link.dest_id);
  const forecastNote = projected
    ? "Dashed: forecast for the next 30 minutes"
    : hours > 24
      ? "Forecasts appear on the 1 h, 6 h and 24 h views"
      : forecast.data
        ? "Forecasts appear once the prediction engine has enough history"
        : undefined;

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ href: "/", label: "Overview" }}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {link.label}
            <HealthBadge health={link.health} size="md" />
          </span>
        }
        description={
          <>
            {fmtCapacity(link.capacity_mbps)} link between{" "}
            <Link className="text-accent-ink hover:underline" href={`/device?id=${link.source_id}`}>
              {source?.name}
            </Link>{" "}
            and{" "}
            <Link className="text-accent-ink hover:underline" href={`/device?id=${link.dest_id}`}>
              {dest?.name}
            </Link>
            .{link.single_point_of_failure ? " It has no backup path: if it fails, part of the network is cut off." : ""}
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Utilisation now"
          value={fmtPct(link.utilisation_pct)}
          tone={HEALTH[link.health].tone}
          detail={healthDescription(link.health, thresholds)}
        />
        <StatTile label="Traffic out / in" value={fmtMbps(link.traffic_out)} detail={`in: ${fmtMbps(link.traffic_in)}`} />
        <StatTile
          label="Forecast in 30 minutes"
          value={fmtPct(plus30?.predicted_pct)}
          tone={link.warning ? "serious" : plus30 ? "good" : undefined}
          detail={
            link.warning
              ? `likely to reach ${critical}% within ${link.warning.horizon_minutes} min`
              : plus30
                ? "no congestion expected"
                : "no forecast yet"
          }
        />
        <StatTile label="Errors (last cycle)" value={fmtNumber(link.error_count)} detail="interface error counter" />
      </div>

      {alert ? <AlertCard alert={alert} user={me.data} critical={critical} /> : null}

      {/* the period of both charts below; the tiles above and the latest forecast show the latest cycle */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
        <span className="text-sm text-ink-2">Period</span>
        <Segmented label="Period" value={hours} onChange={setHours} options={RANGES} />
      </div>

      <Card title="Utilisation and forecast" subtitle={forecastNote} actions={chartView.toggle}>
        {forecast.error ? (
          <ErrorNote error={forecast.error} />
        ) : forecast.isPending ? (
          <Loading />
        ) : chartView.view === "chart" ? (
          <TimeSeriesChart data={utilData} series={utilSeries} thresholds={thresholds} now={now} height={300} />
        ) : (
          <SeriesTable data={utilData} series={utilSeries} />
        )}
      </Card>

      <Card title="Traffic, Mbps" actions={trafficView.toggle}>
        {forecast.error ? (
          <ErrorNote error={forecast.error} />
        ) : forecast.isPending ? (
          <Loading />
        ) : trafficView.view === "chart" ? (
          <TimeSeriesChart
            unit="Mbps"
            data={trafficData}
            series={[
              { key: "out", label: `Out (${source?.name} → ${dest?.name})`, colour: "series-1" },
              { key: "in", label: `In (${dest?.name} → ${source?.name})`, colour: "series-2" },
            ]}
            height={220}
          />
        ) : (
          <SeriesTable
            unit="Mbps"
            data={trafficData}
            series={[
              { key: "out", label: "Out", colour: "series-1" },
              { key: "in", label: "In", colour: "series-2" },
            ]}
          />
        )}
      </Card>

      <Card title="Forecast by horizon" subtitle={`Latest forecast: predicted utilisation and whether the link is likely to reach ${critical}%`}>
        {link.forecast.length ? (
          <DataTable
            rows={link.forecast}
            rowKey={(f) => f.horizon_minutes}
            columns={[
              { key: "h", header: "In", cell: (f) => `${f.horizon_minutes} min` },
              { key: "p", header: "Predicted", numeric: true, cell: (f) => fmtPct(f.predicted_pct) },
              {
                key: "w",
                header: `Reaches ${critical}%?`,
                cell: (f) =>
                  f.warning ? (
                    <span className="inline-flex items-center gap-1">
                      <ToneIcon tone="serious" size={13} /> likely
                    </span>
                  ) : (
                    "unlikely"
                  ),
              },
              { key: "c", header: "Confidence", cell: (f) => `${confidenceBand(f.confidence)} (${Math.round(f.confidence * 100)}%)` },
            ]}
          />
        ) : (
          <Notice>No forecast for this link yet.</Notice>
        )}
      </Card>

      {/* Next keeps this page mounted when only ?id= changes: the key gives each link a fresh editor */}
      <LinkSettings key={link.link_id} linkId={link.link_id} canEdit={me.data?.role === "senior"} />
    </div>
  );
}

function LinkSettings({ linkId, canEdit }: { linkId: number; canEdit: boolean }) {
  const record = useLink(linkId);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  // only ever this link's own record, so another link's values are never shown or saved here
  const data = record.data?.link_id === linkId ? record.data : undefined;
  const finish = (changed: boolean) => {
    setEditing(false);
    setSaved(changed);
  };
  return (
    <Card
      title="Configuration (Topology Store)"
      subtitle="Changes are saved to the Topology Store, not the real network. The Digital Twin Engine applies them when it next starts; the System page says when a restart is needed."
      actions={canEdit && data && !editing ? <Button size="sm" onClick={() => setEditing(true)}>Edit</Button> : null}
    >
      {!data ? (
        record.error ? <ErrorNote error={record.error} /> : <Loading />
      ) : editing ? (
        <LinkEditor record={data} onDone={finish} />
      ) : (
        <>
          {saved ? (
            <div className="mb-3">
              <Notice tone="good">Saved to the Topology Store. The Digital Twin Engine applies the change when it next starts.</Notice>
            </div>
          ) : null}
          <KeyValues
            items={[
              ["Capacity", fmtCapacity(data.capacity_mbps)],
              ["Routing cost", data.routing_cost ?? "automatic (10 000 ÷ capacity)"],
              ["Status", STATUS_LABEL[data.status] ?? data.status],
              ["Link ID", data.link_id],
            ]}
          />
        </>
      )}
    </Card>
  );
}

function LinkEditor({ record, onDone }: { record: LinkRecord; onDone: (saved: boolean) => void }) {
  const queryClient = useQueryClient();
  const [capacity, setCapacity] = useState(String(record.capacity_mbps));
  const [cost, setCost] = useState(record.routing_cost == null ? "" : String(record.routing_cost));
  const [status, setStatus] = useState(record.status);
  const save = useMutation({
    mutationFn: () =>
      patch<LinkRecord>(`links/${record.link_id}`, {
        capacity_mbps: Number(capacity),
        routing_cost: cost === "" ? null : Number(cost),
        status,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["link", record.link_id] });
      queryClient.invalidateQueries({ queryKey: ["topology"] });
      // the simulation form's link choices show each link's capacity and cost
      queryClient.invalidateQueries({ queryKey: ["scenario-types"] });
      onDone(true);
    },
  });
  return (
    <form
      className="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-3"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label className="text-xs font-medium text-ink">
        Capacity (Mbps)
        <input className="field mt-1" type="number" min={1} step="any" value={capacity} onChange={(e) => setCapacity(e.target.value)} required />
      </label>
      <label className="text-xs font-medium text-ink">
        Routing cost (empty = automatic)
        <input className="field mt-1" type="number" min={0.001} step="any" value={cost} onChange={(e) => setCost(e.target.value)} />
      </label>
      <label className="text-xs font-medium text-ink">
        Status
        <select className="field mt-1" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="up">Up</option>
          <option value="down">Down</option>
          <option value="unknown">Unknown</option>
          <option value="decommissioned">Decommissioned (retire)</option>
        </select>
      </label>
      {save.error ? <p className="text-sm text-danger-ink sm:col-span-3">{save.error.message}</p> : null}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button onClick={() => onDone(false)} disabled={save.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
