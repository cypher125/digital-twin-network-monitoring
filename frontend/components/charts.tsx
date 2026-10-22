"use client";

// Charts follow the dataviz rules used throughout the dashboard: one y-axis, 2 px
// lines, hairline solid grid, dashed lines only for thresholds and projections, a
// legend for two or more series, a crosshair tooltip, and a table view with the
// same numbers (see useViewToggle).

import { useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Rectangle,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type BarShapeProps,
  type TooltipContentProps,
} from "recharts";
import { fmtDateTime, fmtDay, fmtPct, fmtTime, WEEKDAYS } from "@/lib/format";
import { useTokens, type TokenName } from "@/lib/theme";
import type { Thresholds } from "@/lib/types";
import { DataTable, type Column } from "./DataTable";
import { Ban } from "./icons";
import { Empty } from "./ui";

export interface SeriesDef {
  key: string;
  label: string;
  colour: TokenName;
  /** a projection (forecast): dashed, with markers */
  projection?: boolean;
}

export type TimePoint = { t: number } & Record<string, number | null | undefined>;

const WAT_OFFSET_MS = 60 * 60 * 1000; // West Africa Time is UTC+1 all year
const STEPS_MIN = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880];

/**
 * Round, evenly spaced time ticks aligned to West Africa Time, and how to label them. The step comes
 * from the measured part (up to `measuredEnd`), so a forecast tail does not coarsen the ticks and the
 * charts of one period share a step.
 */
function timeTicks(start: number, end: number, measuredEnd = end, target = 6): { ticks: number[]; label: (t: number) => string } {
  // floor: a span a little over a round period (one extra cycle) keeps that period's step
  const stepFor = (minutes: number) => STEPS_MIN.find((s) => Math.floor(minutes / s) <= target) ?? 2880;
  const span = (measuredEnd - start) / 60_000;
  let stepMin = stepFor(span);
  // a tail much longer than the measured part would crowd the axis: step by the whole span instead
  if ((end - start) / 60_000 / stepMin > 2 * target) stepMin = stepFor((end - start) / 60_000);
  const step = stepMin * 60_000;
  const first = Math.ceil((start + WAT_OFFSET_MS) / step) * step - WAT_OFFSET_MS;
  const ticks: number[] = [];
  for (let t = first; t <= end; t += step) ticks.push(t);
  const label =
    stepMin >= 1440 ? (t: number) => fmtDay(t) : span > 36 * 60 ? (t: number) => `${fmtDay(t).split(" ")[0]} ${fmtTime(t)}` : (t: number) => fmtTime(t);
  return { ticks, label };
}

/** Ticks from 0 to a round maximum at or above `max`: steps of 1, 2, 2.5 or 5 × 10ⁿ, at most five intervals. */
function niceTicks(max: number): number[] {
  const top = Number.isFinite(max) && max > 0 ? max : 1;
  const power = 10 ** Math.floor(Math.log10(top / 5));
  const intervals = (step: number) => Math.ceil(top / step - 1e-9);
  // the smallest round step that covers `top` in five intervals or fewer (10 × power always does)
  const step = [1, 2, 2.5, 5].map((m) => m * power).find((s) => intervals(s) <= 5) ?? 10 * power;
  return Array.from({ length: intervals(step) + 1 }, (_, i) => Number((i * step).toPrecision(12)));
}

export function SeriesLegend({ series }: { series: SeriesDef[] }) {
  const tokens = useTokens();
  if (series.length < 2) return null;
  return (
    <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-label="Legend">
      {series.map((s) => (
        <li key={s.key} className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden>
            <line
              x1="1"
              y1="4"
              x2="17"
              y2="4"
              stroke={tokens[s.colour]}
              strokeWidth={2}
              strokeLinecap="round"
              strokeDasharray={s.projection ? "4 3" : undefined}
            />
          </svg>
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function ThresholdKey({ thresholds }: { thresholds?: Thresholds }) {
  const tokens = useTokens();
  if (!thresholds) return null;
  return (
    <span className="inline-flex items-center gap-3 text-xs text-ink-2">
      {[
        ["Warning", thresholds.warning_pct, tokens.warning],
        ["Critical", thresholds.critical_pct, tokens.critical],
      ].map(([name, value, colour]) => (
        <span key={String(name)} className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden>
            <line x1="1" y1="4" x2="17" y2="4" stroke={String(colour)} strokeWidth={1.5} strokeDasharray="3 3" />
          </svg>
          {name} {value}%
        </span>
      ))}
    </span>
  );
}

function TooltipCard({ title, rows }: { title: ReactNode; rows: { key: string; colour: string; label: string; value: string; dashed?: boolean }[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-medium text-ink">{title}</div>
      {rows.map((row) => (
        <div key={row.key} className="flex min-w-44 items-center gap-2 py-0.5">
          <svg width="14" height="8" aria-hidden>
            <line x1="1" y1="4" x2="13" y2="4" stroke={row.colour} strokeWidth={2} strokeDasharray={row.dashed ? "3 2" : undefined} />
          </svg>
          <span className="text-ink-2">{row.label}</span>
          <span className="num ml-auto pl-3 font-medium text-ink">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export function TimeSeriesChart({
  data,
  series,
  unit = "%",
  thresholds,
  height = 260,
  now,
  yMax,
  format,
}: {
  data: TimePoint[];
  series: SeriesDef[];
  unit?: "%" | "Mbps" | "";
  thresholds?: Thresholds;
  height?: number;
  /** draw a "now" marker (the last measured cycle) */
  now?: number | null;
  yMax?: number;
  format?: (value: number) => string;
}) {
  const tokens = useTokens();
  const percent = unit === "%";
  const valueFormat = format ?? ((v: number) => (unit === "%" ? fmtPct(v) : unit === "Mbps" ? `${v.toFixed(1)} Mbps` : v.toFixed(1)));
  const [start, end] = data.length ? [data[0].t, data[data.length - 1].t] : [0, 0];
  // the measured part ends at "now"; after it comes the forecast
  const measuredEnd = now != null && now > start && now <= end ? now : end;
  const axis = useMemo(() => timeTicks(start, end, measuredEnd), [start, end, measuredEnd]);
  // the % axis is fixed at 0-100%; other units get a round maximum with evenly spaced ticks
  const valueTicks = useMemo(() => {
    if (percent || yMax != null) return undefined;
    let max = 0;
    for (const point of data) for (const s of series) max = Math.max(max, point[s.key] ?? 0);
    return niceTicks(max);
  }, [data, series, percent, yMax]);
  if (data.length === 0) return <Empty>No measurements in this period yet.</Empty>;

  const renderTooltip = (props: TooltipContentProps) => {
    if (!props.active || !props.payload?.length) return null;
    const rows = series.flatMap((s) => {
      const item = props.payload.find((p) => p.dataKey === s.key);
      if (!item || item.value == null) return [];
      return [{ key: s.key, colour: tokens[s.colour], label: s.label, value: valueFormat(Number(item.value)), dashed: s.projection }];
    });
    return <TooltipCard title={fmtDateTime(Number(props.label))} rows={rows} />;
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <SeriesLegend series={series} />
        {percent ? <ThresholdKey thresholds={thresholds} /> : null}
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={tokens.grid} strokeWidth={1} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[start, end]}
              ticks={axis.ticks}
              tickFormatter={axis.label}
              stroke={tokens.axis}
              tick={{ fill: tokens.muted, fontSize: 11 }}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              domain={[0, yMax ?? (percent ? 100 : (valueTicks?.[valueTicks.length - 1] ?? "auto"))]}
              ticks={percent ? (yMax ? undefined : [0, 25, 50, 75, 100]) : valueTicks}
              tickFormatter={(v: number) => (percent ? `${v}%` : Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}K` : `${v}`)}
              stroke={tokens.axis}
              tick={{ fill: tokens.muted, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={percent ? 40 : 48}
              allowDecimals={false}
            />
            {percent && thresholds ? (
              <>
                <ReferenceLine y={thresholds.warning_pct} stroke={tokens.warning} strokeDasharray="4 4" strokeWidth={1.5} ifOverflow="extendDomain" />
                <ReferenceLine y={thresholds.critical_pct} stroke={tokens.critical} strokeDasharray="4 4" strokeWidth={1.5} ifOverflow="extendDomain" />
              </>
            ) : null}
            {now ? (
              <ReferenceLine
                x={now}
                stroke={tokens.muted}
                strokeWidth={1}
                label={{ value: "now", position: "insideTopLeft", fill: tokens.muted, fontSize: 11 }}
              />
            ) : null}
            <Tooltip content={renderTooltip} cursor={{ stroke: tokens.axis, strokeWidth: 1 }} isAnimationActive={false} />
            {series.map((s) => (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.label}
                type="linear"
                stroke={tokens[s.colour]}
                strokeWidth={2}
                strokeDasharray={s.projection ? "5 4" : undefined}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={s.projection ? { r: 4, fill: tokens[s.colour], stroke: tokens.surface, strokeWidth: 2 } : false}
                activeDot={{ r: 4, fill: tokens[s.colour], stroke: tokens.surface, strokeWidth: 2 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** The table twin of a TimeSeriesChart. */
export function SeriesTable({ data, series, unit = "%", maxHeight = 320 }: {
  data: TimePoint[];
  series: SeriesDef[];
  unit?: "%" | "Mbps" | "";
  maxHeight?: number;
}) {
  const columns: Column<TimePoint>[] = [
    { key: "t", header: "Time (WAT)", cell: (row) => fmtDateTime(row.t), sort: (row) => row.t },
    ...series.map<Column<TimePoint>>((s) => ({
      key: s.key,
      header: s.label,
      numeric: true,
      sort: (row) => row[s.key] ?? null,
      cell: (row) => {
        const value = row[s.key];
        if (value == null) return "–";
        return unit === "%" ? fmtPct(value) : unit === "Mbps" ? `${value.toFixed(1)} Mbps` : value.toFixed(1);
      },
    })),
  ];
  const rows = data.filter((row) => series.some((s) => row[s.key] != null));
  return <DataTable rows={rows} columns={columns} rowKey={(row) => row.t} initialSort={{ key: "t", desc: true }} maxHeight={maxHeight} dense />;
}

// --------------------------------------------------------------- before / after
export interface BeforeAfterRow {
  link_id: number;
  label: string;
  before: number | null;
  after: number;
  /** out of service after the change: marked Down, not drawn as a 0% bar */
  down?: boolean;
}

/** Utilisation before and after a simulated change, for the links that change most. */
export function BeforeAfterChart({ rows, thresholds, beforeLabel = "Before the change", afterLabel = "After the change" }: {
  rows: BeforeAfterRow[];
  thresholds?: Thresholds;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  const tokens = useTokens();
  const series: SeriesDef[] = [
    { key: "before", label: beforeLabel, colour: "series-1" },
    { key: "after", label: afterLabel, colour: "series-2" },
  ];
  if (rows.length === 0) return <Empty>No link changes by more than a rounding error.</Empty>;
  const max = Math.max(100, ...rows.map((r) => Math.max(r.after, r.before ?? 0)));
  const height = 44 + rows.length * 40;

  const renderTooltip = (props: TooltipContentProps) => {
    if (!props.active || !props.payload?.length) return null;
    const row = props.payload[0]?.payload as BeforeAfterRow | undefined;
    if (!row) return null;
    return (
      <TooltipCard
        title={row.label}
        rows={[
          { key: "before", colour: tokens["series-1"], label: beforeLabel, value: fmtPct(row.before) },
          { key: "after", colour: tokens["series-2"], label: afterLabel, value: row.down ? "Down" : fmtPct(row.after) },
        ]}
      />
    );
  };

  // A link that is down after the change has no bar to draw: mark its place with the Down icon and word.
  // (With a custom shape Recharts keeps zero-width bars, which it otherwise drops before any label.)
  const renderAfterBar = (props: BarShapeProps) => {
    if (!(props.payload as BeforeAfterRow | undefined)?.down) return <Rectangle {...props} />;
    const x = props.x ?? 0;
    const middle = (props.y ?? 0) + (props.height ?? 0) / 2;
    return (
      <g>
        <Ban x={x + 2} y={middle - 6} size={12} stroke={tokens.down} />
        <text x={x + 18} y={middle} dominantBaseline="central" fontSize={11} fill={tokens["ink-2"]}>
          Down
        </text>
      </g>
    );
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <SeriesLegend series={series} />
        <ThresholdKey thresholds={thresholds} />
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid horizontal={false} stroke={tokens.grid} />
            <XAxis
              type="number"
              domain={[0, Math.ceil(max / 10) * 10]}
              tickFormatter={(v: number) => `${v}%`}
              stroke={tokens.axis}
              tick={{ fill: tokens.muted, fontSize: 11 }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={170}
              tick={{ fill: tokens["ink-2"], fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              interval={0}
            />
            {thresholds ? (
              <>
                <ReferenceLine x={thresholds.warning_pct} stroke={tokens.warning} strokeDasharray="4 4" strokeWidth={1.5} />
                <ReferenceLine x={thresholds.critical_pct} stroke={tokens.critical} strokeDasharray="4 4" strokeWidth={1.5} />
              </>
            ) : null}
            <Tooltip content={renderTooltip} cursor={{ fill: tokens["surface-2"] }} isAnimationActive={false} />
            <Bar dataKey="before" fill={tokens["series-1"]} maxBarSize={14} radius={[0, 4, 4, 0]} isAnimationActive={false} />
            <Bar dataKey="after" fill={tokens["series-2"]} maxBarSize={14} radius={[0, 4, 4, 0]} shape={renderAfterBar} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------- heatmap
export interface HeatCell {
  weekday: number; // ISO: 1 = Monday
  hour: number;
  avg_pct: number | null;
}

const SEQ: TokenName[] = ["seq-0", "seq-1", "seq-2", "seq-3", "seq-4", "seq-5", "seq-6"];

function niceMax(value: number): number {
  for (const step of [5, 10, 20, 25, 50, 75, 100]) if (value <= step) return step;
  return Math.ceil(value / 10) * 10;
}

/** Average utilisation by weekday and hour: quiet windows for maintenance (sequential blue). */
export function UtilisationHeatmap({ cells }: { cells: HeatCell[] }) {
  const tokens = useTokens();
  const [hover, setHover] = useState<HeatCell | null>(null);
  const values = cells.map((c) => c.avg_pct ?? 0);
  if (cells.length === 0) return <Empty>Not enough history for a weekly pattern yet.</Empty>;
  const top = niceMax(Math.max(...values, 1));
  const byKey = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c]));
  const colourOf = (value: number | null) =>
    value == null ? tokens["surface-2"] : tokens[SEQ[Math.min(SEQ.length - 1, Math.floor((value / top) * SEQ.length))]];

  return (
    <div>
      <div className="overflow-x-auto">
        <div className="min-w-[560px]">
          <div className="grid grid-cols-[3rem_repeat(24,minmax(0,1fr))] gap-[2px]" onMouseLeave={() => setHover(null)}>
            <div />
            {Array.from({ length: 24 }, (_, hour) => (
              <div key={hour} className="num pb-1 text-center text-[10px] text-muted">
                {hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}
              </div>
            ))}
            {WEEKDAYS.map((day, index) => (
              <div key={day} className="contents">
                <div className="flex items-center text-xs text-ink-2">{day}</div>
                {Array.from({ length: 24 }, (_, hour) => {
                  const cell = byKey.get(`${index + 1}-${hour}`) ?? { weekday: index + 1, hour, avg_pct: null };
                  const active = hover?.weekday === cell.weekday && hover.hour === hour;
                  return (
                    <div
                      key={hour}
                      onMouseEnter={() => setHover(cell)}
                      title={`${day} ${String(hour).padStart(2, "0")}:00 – ${fmtPct(cell.avg_pct)}`}
                      className="h-6 rounded-[3px]"
                      style={{ background: colourOf(cell.avg_pct), outline: active ? `2px solid ${tokens.ink}` : undefined }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-ink-2">
        <div className="flex items-center gap-2">
          <span>0%</span>
          <div className="flex h-2.5 w-40 overflow-hidden rounded-sm">
            {SEQ.map((name) => (
              <div key={name} className="flex-1" style={{ background: tokens[name] }} />
            ))}
          </div>
          <span>{top}% average utilisation</span>
        </div>
        <div className="num min-h-4" aria-live="polite">
          {hover ? `${WEEKDAYS[hover.weekday - 1]} ${String(hover.hour).padStart(2, "0")}:00–${String(hover.hour).padStart(2, "0")}:59 WAT: ${fmtPct(hover.avg_pct)}` : "Point at a cell for its value."}
        </div>
      </div>
    </div>
  );
}

export function HeatmapTable({ cells }: { cells: HeatCell[] }) {
  const byKey = new Map(cells.map((c) => [`${c.weekday}-${c.hour}`, c.avg_pct]));
  return (
    <div className="overflow-x-auto">
      <table className="num w-full border-collapse text-xs">
        <caption className="sr-only">Average utilisation by weekday and hour</caption>
        <thead>
          <tr>
            <th scope="col" className="px-1 py-1 text-left font-medium text-ink-2">
              Hour
            </th>
            {WEEKDAYS.map((day) => (
              <th key={day} scope="col" className="px-1 py-1 text-right font-medium text-ink-2">
                {day}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 24 }, (_, hour) => (
            <tr key={hour} className="border-t border-line">
              <th scope="row" className="px-1 py-0.5 text-left font-normal text-ink-2">
                {String(hour).padStart(2, "0")}:00
              </th>
              {WEEKDAYS.map((day, index) => (
                <td key={day} className="px-1 py-0.5 text-right text-ink">
                  {fmtPct(byKey.get(`${index + 1}-${hour}`) ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
