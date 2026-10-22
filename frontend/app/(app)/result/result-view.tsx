"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { BeforeAfterChart, type BeforeAfterRow } from "@/components/charts";
import { MapLegend, TopologyMap } from "@/components/TopologyMap";
import { DataTable } from "@/components/DataTable";
import { Card, ErrorNote, HealthBadge, KeyValues, Loading, Notice, PageHeader, Segmented, StatTile, StatusBadge, ToneIcon, useViewToggle } from "@/components/ui";
import { DEFAULT_THRESHOLDS, fmtDateTime, fmtMbps, fmtPct, fmtSignedPct, healthOf } from "@/lib/format";
import { useComparison, useLive, useResult, useScenarioTypes, useTopology } from "@/lib/queries";
import type { Comparison, SimulationResult, Topology, TopologyLink } from "@/lib/types";
import { RUN_TONE } from "../simulation/simulation-console";

export function ResultView() {
  const id = Number(useSearchParams().get("id")) || null;
  const result = useResult(id);
  const live = useLive();
  const types = useScenarioTypes();

  if (id == null) return <ErrorNote error="No result was chosen." title="Result not found" />;
  if (result.isPending) return <Loading />;
  if (result.error || !result.data) return <ErrorNote error={result.error} title="Could not load the result" />;
  const r = result.data;
  const typeLabel = types.data?.types.find((t) => t.key === r.scenario_type)?.label ?? r.scenario_type;
  const request = r.result_summary?.request;
  // a run stores "current" or "forecast +N min"; while queued only the request ("forecast", with its horizon) is there
  const forecastBasis = /^forecast(?: \+(\d+) min)?$/.exec(r.result_summary?.basis ?? request?.basis ?? "current");
  const basis = forecastBasis ? `forecast traffic in ${forecastBasis[1] ?? request?.horizon_minutes ?? 30} minutes` : "current traffic";
  const waiting = live.data ? runWait(live.data.engine_state) : null;

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ href: "/simulation", label: "Simulation console" }}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {r.scenario_name}
            <StatusBadge tone={RUN_TONE[r.status].tone} label={RUN_TONE[r.status].label} size="md" />
          </span>
        }
        description={`${typeLabel} · simulated with ${basis} · requested ${fmtDateTime(r.requested_at)} (server clock)${r.run_by ? ` by ${r.run_by}` : ""}`}
        actions={
          <Link href={`/simulation?scenario=${r.scenario}`} className="inline-flex items-center rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2">
            Open the scenario
          </Link>
        }
      />
      {r.status === "queued" || r.status === "running" ? (
        <Card>
          <Loading label={r.status === "queued" ? "Waiting for the twin engine to pick up the run…" : "Simulating…"} />
          {waiting ? <Notice tone="warning">{waiting}</Notice> : null}
        </Card>
      ) : r.status === "failed" ? (
        <ErrorNote error={r.result_summary?.error ?? "The simulation could not be completed."} title="The simulation failed" />
      ) : (
        <Completed result={r} />
      )}
    </div>
  );
}

function Completed({ result }: { result: SimulationResult }) {
  const summary = useMemo(() => result.result_summary ?? {}, [result.result_summary]);
  const topology = useTopology();
  const [against, setAgainst] = useState<"stored" | "live">("stored");
  const comparison = useComparison(result.result_id, against, true);
  const chartView = useViewToggle();
  // the thresholds the run was worked out with
  const thresholds = useMemo(
    () => summary.thresholds ?? topology.data?.thresholds ?? DEFAULT_THRESHOLDS,
    [summary.thresholds, topology.data?.thresholds],
  );
  const names = new Map((topology.data?.devices ?? []).map((d) => [d.device_id, d.name]));
  const links = useMemo(() => summary.links ?? [], [summary.links]);
  const label = (id: number) => links.find((l) => l.link_id === id)?.label ?? `link ${id}`;

  const movers: BeforeAfterRow[] = useMemo(() => {
    const rows = comparison.data?.links ?? [];
    return rows
      .filter((row) => Math.abs(row.change_pct ?? 0) >= 0.5)
      .slice(0, 10)
      .map((row) => ({ link_id: row.link_id, label: row.label, before: row.baseline_pct, after: row.after_pct, down: row.status_after === "down" }));
  }, [comparison.data]);

  // the network as it would be after the change, for the map
  const changed: Topology | null = useMemo(() => {
    if (!topology.data) return null;
    const t = topology.data;
    const after = new Map(links.map((l) => [l.link_id, l]));
    const params = (summary.parameters ?? {}) as Record<string, unknown>;
    const failedDevice = result.scenario_type === "device_failure" ? Number(params.device_id) : null;
    const isolated = new Set(summary.isolated_devices ?? []);
    const recolour = (base: TopologyLink, outcome: (typeof links)[number]): TopologyLink => {
      const down = outcome.status_after === "down";
      return {
        ...base,
        capacity_mbps: outcome.capacity_mbps,
        status: outcome.status_after,
        utilisation_pct: down ? null : outcome.after_pct,
        health: down ? "down" : healthOf(outcome.after_pct, "up", thresholds.warning_pct, thresholds.critical_pct),
        traffic_in: null,
        traffic_out: null,
        warning: null,
        forecast: [],
      };
    };
    const mapped = t.links.map((l) => (after.has(l.link_id) ? recolour(l, after.get(l.link_id)!) : l));
    // a link added by an "add a link" scenario has a temporary negative id
    for (const outcome of links.filter((l) => l.link_id < 0)) {
      const source = Number(params.source_id);
      const dest = Number(params.dest_id);
      if (!Number.isFinite(source) || !Number.isFinite(dest)) continue;
      const blank: TopologyLink = {
        link_id: outcome.link_id, source_id: source, dest_id: dest, label: outcome.label, capacity_mbps: outcome.capacity_mbps,
        status: "up", utilisation_pct: null, traffic_in: null, traffic_out: null, error_count: null, health: "unknown",
        single_point_of_failure: false, most_used: false, forecast: [], warning: null,
      };
      mapped.push(recolour(blank, outcome));
    }
    const devices = t.devices.map((d) =>
      d.device_id === failedDevice ? { ...d, status: "down", health: "down" as const } : isolated.has(d.device_id) ? { ...d, health: "unknown" as const } : d,
    );
    return { ...t, devices, links: mapped };
  }, [topology.data, links, summary.parameters, summary.isolated_devices, result.scenario_type, thresholds]);

  const lostBefore = summary.undeliverable_mbps_before ?? 0;
  const lostAfter = summary.undeliverable_mbps_after ?? 0;

  return (
    <>
      {summary.summary ? (
        <div className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink">
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">What would happen</div>
          {summary.summary}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Busiest link after"
          value={fmtPct(summary.max_after?.pct)}
          detail={summary.max_after?.label}
          tone={summary.max_after ? toneOf(summary.max_after.pct, thresholds) : undefined}
        />
        <StatTile label="Busiest link before" value={fmtPct(summary.max_before?.pct)} detail={summary.max_before?.label} />
        <StatTile
          label="New bottlenecks"
          value={summary.created?.length ?? 0}
          tone={(summary.created?.length ?? 0) > 0 ? "critical" : "good"}
          detail={`links pushed to ${thresholds.critical_pct}% or more`}
        />
        <StatTile
          label="Bottlenecks relieved"
          value={summary.relieved?.length ?? 0}
          tone={(summary.relieved?.length ?? 0) > 0 ? "good" : undefined}
          detail={`links brought below ${thresholds.critical_pct}%`}
        />
        <StatTile
          label="Devices cut off"
          value={summary.isolated_devices?.length ?? 0}
          tone={(summary.isolated_devices?.length ?? 0) > 0 ? "critical" : "good"}
          detail={(summary.isolated_devices ?? []).slice(0, 3).map((d) => names.get(d) ?? d).join(", ") || "none"}
        />
        <StatTile
          label="Traffic not delivered"
          value={fmtMbps(lostAfter)}
          tone={lostAfter > lostBefore + 0.05 ? "critical" : undefined}
          detail={`before: ${fmtMbps(lostBefore)}`}
        />
      </div>

      <Card
        title="Links that change most"
        subtitle={against === "stored" ? "Modelled utilisation before and after the change" : "Utilisation measured now, and after the change"}
        actions={
          <>
            <Segmented
              label="Compare with"
              value={against}
              onChange={setAgainst}
              options={[
                { value: "stored", label: "Before the change" },
                { value: "live", label: "The network now" },
              ]}
            />
            {chartView.toggle}
          </>
        }
      >
        {comparison.error ? (
          <ErrorNote error={comparison.error} />
        ) : comparison.isPending ? (
          <Loading />
        ) : chartView.view === "chart" ? (
          <BeforeAfterChart
            rows={movers}
            thresholds={thresholds}
            beforeLabel={against === "stored" ? "Before the change" : "Measured now"}
            afterLabel="After the change"
          />
        ) : (
          <ComparisonTable data={comparison.data} thresholds={thresholds} />
        )}
      </Card>

      <Card title="The network after the change" subtitle="Modelled utilisation of every link with the change applied; devices cut off are shown as having no data">
        {changed ? (
          <>
            <TopologyMap topology={changed} height={460} navigate={false} />
            <div className="mt-3">
              <MapLegend thresholds={thresholds} />
            </div>
          </>
        ) : topology.error ? (
          <ErrorNote error={topology.error} />
        ) : (
          <Loading label="Loading the map…" />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Bottlenecks" className="min-w-0">
          {/* each icon reflects its list, as on the tiles above: none created is good news */}
          <div className="space-y-3 text-sm">
            <div>
              <div className="mb-1 flex items-center gap-1.5 font-medium text-ink">
                <ToneIcon tone={summary.created?.length ? "critical" : "good"} size={14} /> Created by the change
              </div>
              {summary.created?.length ? (
                <ul className="list-inside list-disc text-ink-2">
                  {summary.created.map((id) => (
                    <li key={id}>{label(id)}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink-2">None.</p>
              )}
            </div>
            <div>
              <div className="mb-1 flex items-center gap-1.5 font-medium text-ink">
                {summary.relieved?.length ? <ToneIcon tone="good" size={14} /> : null} Relieved by the change
              </div>
              {summary.relieved?.length ? (
                <ul className="list-inside list-disc text-ink-2">
                  {summary.relieved.map((id) => (
                    <li key={id}>{label(id)}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-ink-2">None.</p>
              )}
            </div>
          </div>
        </Card>
        <Card title="How the run was done" className="min-w-0">
          <KeyValues
            items={[
              ["Network time", fmtDateTime(summary.network_time)],
              ["Executed (server clock)", fmtDateTime(result.executed_at)],
              [
                "Calibration",
                summary.calibration_factor != null
                  ? `× ${summary.calibration_factor.toFixed(3)} (measured ÷ modelled utilisation on busy links)`
                  : "–",
              ],
              [
                "Model fidelity",
                summary.model_fidelity_mae_pct != null
                  ? `${summary.model_fidelity_mae_pct.toFixed(2)} points average difference from the measured network`
                  : "–",
              ],
              ["Notes", summary.notes?.length ? summary.notes.join(" ") : "–"],
            ]}
          />
        </Card>
      </div>

      <Card
        title="Every link"
        subtitle={`Modelled utilisation before and after the change; measured values from ${
          summary.network_time ? `${fmtDateTime(summary.network_time)} WAT` : "the time of the run"
        }`}
      >
        <DataTable
          rows={links}
          rowKey={(l) => l.link_id}
          maxHeight={480}
          initialSort={{ key: "delta", desc: true }}
          columns={[
            {
              key: "label",
              header: "Link",
              sort: (l) => l.label,
              cell: (l) =>
                l.link_id > 0 ? (
                  <Link href={`/link?id=${l.link_id}`} className="text-accent-ink hover:underline">
                    {l.label}
                  </Link>
                ) : (
                  `${l.label} (new)`
                ),
            },
            { key: "observed", header: "Measured at run time", numeric: true, sort: (l) => l.observed_pct, cell: (l) => fmtPct(l.observed_pct) },
            { key: "before", header: "Before", numeric: true, sort: (l) => l.before_pct, cell: (l) => fmtPct(l.before_pct) },
            { key: "after", header: "After", numeric: true, sort: (l) => l.after_pct, cell: (l) => fmtPct(l.after_pct) },
            { key: "delta", header: "Change", numeric: true, sort: (l) => Math.abs(l.delta_pct), cell: (l) => fmtSignedPct(l.delta_pct) },
            {
              key: "status",
              header: "After the change",
              sort: (l) => l.after_pct,
              cell: (l) => (
                <span className="inline-flex items-center gap-2">
                  <HealthBadge health={l.status_after === "down" ? "down" : healthOf(l.after_pct, "up", thresholds.warning_pct, thresholds.critical_pct)} />
                  {l.overloaded ? <span className="text-xs text-danger-ink">overloaded</span> : null}
                </span>
              ),
            },
          ]}
        />
      </Card>
    </>
  );
}

/**
 * Why a queued run is not being picked up, or null while the engine serves runs. The engine runs them
 * between polls of the data source, so it still does when stepped (demo mode) or after a failed
 * cycle ("error"), but not while it cannot reach the data source or the database.
 */
function runWait(state: string): string | null {
  if (state === "stopped" || state === "not running") return "The twin engine is not running, so the run will wait until it starts.";
  const waitingFor = /^waiting for (.+)$/.exec(state);
  if (waitingFor) return `The twin engine is ${state}, so the run will wait until ${waitingFor[1]} can be reached again.`;
  return null;
}

function toneOf(pct: number, t: { warning_pct: number; critical_pct: number }) {
  return pct >= t.critical_pct ? "critical" : pct >= t.warning_pct ? "warning" : "good";
}

function ComparisonTable({ data, thresholds }: { data: Comparison | undefined; thresholds: { warning_pct: number; critical_pct: number } }) {
  return (
    <DataTable
      rows={data?.links ?? []}
      rowKey={(l) => l.link_id}
      maxHeight={420}
      initialSort={{ key: "change", desc: true }}
      columns={[
        { key: "label", header: "Link", sort: (l) => l.label, cell: (l) => l.label },
        { key: "baseline", header: data?.against === "live" ? "Measured now" : "Before", numeric: true, sort: (l) => l.baseline_pct, cell: (l) => fmtPct(l.baseline_pct) },
        { key: "after", header: "After", numeric: true, sort: (l) => l.after_pct, cell: (l) => fmtPct(l.after_pct) },
        { key: "change", header: "Change", numeric: true, sort: (l) => Math.abs(l.change_pct ?? 0), cell: (l) => fmtSignedPct(l.change_pct) },
        {
          key: "status",
          header: "After the change",
          cell: (l) => <HealthBadge health={l.status_after === "down" ? "down" : healthOf(l.after_pct, "up", thresholds.warning_pct, thresholds.critical_pct)} />,
        },
      ]}
    />
  );
}
