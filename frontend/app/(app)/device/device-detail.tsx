"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { SeriesTable, TimeSeriesChart, type SeriesDef, type TimePoint } from "@/components/charts";
import { DataTable } from "@/components/DataTable";
import { Button, Card, ErrorNote, HealthBadge, KeyValues, Loading, Notice, PageHeader, Segmented, StatTile, ToneIcon, useViewToggle } from "@/components/ui";
import { patch } from "@/lib/api";
import { DEVICE_TYPES, fmtCapacity, fmtMbps, fmtPct, HEALTH, type Tone } from "@/lib/format";
import { useDevice, useDeviceMetrics, useMe, useTopology } from "@/lib/queries";
import type { DeviceRecord, SeriesPoint, TopologyLink } from "@/lib/types";

const RANGES = [
  { value: 1, label: "1 h" },
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 168, label: "7 days" },
];

const CPU: SeriesDef[] = [{ key: "cpu", label: "CPU utilisation", colour: "series-1" }];
const TRAFFIC: SeriesDef[] = [
  { key: "in", label: "Received", colour: "series-1" },
  { key: "out", label: "Sent", colour: "series-2" },
];

// Display words for stored values; the editor offers the same words for the status.
const STATUS_LABEL: Record<string, string> = { up: "Up", down: "Down", unknown: "Unknown", decommissioned: "Decommissioned" };
const DEVICE_ROLE_LABEL: Record<string, string> = {
  core: "Core",
  distribution: "Distribution",
  access: "Access",
  datacentre: "Data centre",
  edge: "Edge",
  wan: "WAN",
  server: "Server",
};

/** The Status tile: the device's stored state, in the words and icons of the status badges. */
function statusTile(status: string): { value: string; tone: Tone; detail: string } {
  if (status === "up") return { value: "Up", tone: "good", detail: "in service" };
  const meta = HEALTH[status === "down" ? "down" : "unknown"]; // "unknown" (never reported) must not read as Up
  return { value: meta.label, tone: meta.tone, detail: meta.description };
}

/**
 * True when received and sent stay within 1% of the busiest value (about a line's width)
 * at nearly every point, as on a switch, which forwards what it receives: Sent then hides Received.
 */
function trafficOverlaps(points: SeriesPoint[]): boolean {
  const pairs: [number, number][] = [];
  for (const p of points) if (p.traffic_in != null && p.traffic_out != null) pairs.push([p.traffic_in, p.traffic_out]);
  if (pairs.length === 0) return false;
  const tolerance = 0.01 * pairs.reduce((peak, [a, b]) => Math.max(peak, a, b), 0);
  return pairs.filter(([a, b]) => Math.abs(a - b) <= tolerance).length >= 0.95 * pairs.length;
}

export function DeviceDetail() {
  const id = Number(useSearchParams().get("id")) || null;
  const [hours, setHours] = useState(6);
  const topology = useTopology();
  const metrics = useDeviceMetrics(id, hours);
  const me = useMe();
  const cpuView = useViewToggle();
  const trafficView = useViewToggle();

  const { cpuData, trafficData, trafficOverlap } = useMemo(() => {
    const points = metrics.data?.points ?? [];
    return {
      cpuData: points.map<TimePoint>((p) => ({ t: new Date(p.t).getTime(), cpu: p.cpu_util })),
      trafficData: points.map<TimePoint>((p) => ({ t: new Date(p.t).getTime(), in: p.traffic_in, out: p.traffic_out })),
      trafficOverlap: trafficOverlaps(points),
    };
  }, [metrics.data]);

  if (id == null) return <ErrorNote error="No device was chosen." title="Device not found" />;
  if (topology.isPending) return <Loading />;
  // a failed request is not a missing device
  if (!topology.data) return <ErrorNote error={topology.error} title="Could not load the network" />;
  const device = topology.data.devices.find((d) => d.device_id === id);
  if (!device) return <ErrorNote error="This device does not exist or has been retired." title="Device not found" />;
  const links = topology.data.links.filter((l) => l.source_id === id || l.dest_id === id);
  const names = new Map(topology.data.devices.map((d) => [d.device_id, d.name]));
  const status = statusTile(device.status);
  const critical = topology.data.thresholds.critical_pct;

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ href: "/", label: "Overview" }}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {device.name}
            <HealthBadge health={device.health} size="md" />
          </span>
        }
        description={`${DEVICE_TYPES[device.device_type] ?? device.device_type} in ${device.location}${
          device.single_point_of_failure ? ". A single point of failure: if it fails, part of the network is cut off." : "."
        }`}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Status" value={status.value} tone={status.tone} detail={status.detail} />
        <StatTile label="CPU now" value={fmtPct(device.cpu_util, 0)} tone={HEALTH[device.health].tone} />
        <StatTile label="Received / sent" value={fmtMbps(device.traffic_in)} detail={`sent: ${fmtMbps(device.traffic_out)}`} />
        <StatTile label="Links" value={links.length} detail={`${links.filter((l) => l.status === "down").length} down`} />
      </div>

      {/* the period of both charts below; the tiles above show the latest cycle */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
        <span className="text-sm text-ink-2">Period</span>
        <Segmented label="Period" value={hours} onChange={setHours} options={RANGES} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="CPU utilisation" actions={cpuView.toggle}>
          {metrics.error ? (
            <ErrorNote error={metrics.error} />
          ) : metrics.isPending ? (
            <Loading />
          ) : cpuView.view === "chart" ? (
            <TimeSeriesChart data={cpuData} series={CPU} height={220} />
          ) : (
            <SeriesTable data={cpuData} series={CPU} />
          )}
        </Card>
        <Card title="Traffic, Mbps (all interfaces)" actions={trafficView.toggle}>
          {metrics.error ? (
            <ErrorNote error={metrics.error} />
          ) : metrics.isPending ? (
            <Loading />
          ) : trafficView.view === "chart" ? (
            <>
              <TimeSeriesChart unit="Mbps" data={trafficData} series={TRAFFIC} height={220} />
              {trafficOverlap ? (
                <p className="mt-2 text-xs text-ink-2">Received and sent are almost equal throughout this period, so the Sent line covers most of the Received line.</p>
              ) : null}
            </>
          ) : (
            <SeriesTable unit="Mbps" data={trafficData} series={TRAFFIC} />
          )}
        </Card>
      </div>

      <Card title="Connected links">
        <DataTable<TopologyLink>
          rows={links}
          rowKey={(l) => l.link_id}
          initialSort={{ key: "util", desc: true }}
          columns={[
            {
              key: "to",
              header: "To",
              sort: (l) => names.get(l.source_id === id ? l.dest_id : l.source_id) ?? "",
              cell: (l) => {
                const other = l.source_id === id ? l.dest_id : l.source_id;
                return (
                  <Link href={`/device?id=${other}`} className="text-accent-ink hover:underline">
                    {names.get(other)}
                  </Link>
                );
              },
            },
            {
              key: "link",
              header: "Link",
              cell: (l) => (
                <Link href={`/link?id=${l.link_id}`} className="text-accent-ink hover:underline">
                  details
                </Link>
              ),
            },
            { key: "health", header: "Status", cell: (l) => <HealthBadge health={l.health} /> },
            { key: "util", header: "Utilisation", numeric: true, sort: (l) => l.utilisation_pct, cell: (l) => fmtPct(l.utilisation_pct) },
            { key: "cap", header: "Capacity", numeric: true, sort: (l) => l.capacity_mbps, cell: (l) => fmtCapacity(l.capacity_mbps) },
            {
              key: "warn",
              header: "Forecast",
              cell: (l) =>
                l.warning ? (
                  <span className="inline-flex items-center gap-1">
                    <ToneIcon tone="serious" size={13} /> {critical}% within {l.warning.horizon_minutes} min
                  </span>
                ) : (
                  <span className="text-ink-2">no congestion expected</span>
                ),
            },
          ]}
        />
      </Card>

      {/* Next keeps this page mounted when only ?id= changes: the key gives each device a fresh editor */}
      <DeviceSettings key={device.device_id} deviceId={device.device_id} linkCount={links.length} canEdit={me.data?.role === "senior"} />
    </div>
  );
}

function DeviceSettings({ deviceId, linkCount, canEdit }: { deviceId: number; linkCount: number; canEdit: boolean }) {
  const record = useDevice(deviceId);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  // only ever this device's own record, so another device's values are never shown or saved here
  const data = record.data?.device_id === deviceId ? record.data : undefined;
  const config = data?.configuration ?? {};
  const role = String(config.role ?? "");
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
        <DeviceEditor record={data} linkCount={linkCount} onDone={finish} />
      ) : (
        <>
          {saved ? (
            <div className="mb-3">
              <Notice tone="good">Saved to the Topology Store. The Digital Twin Engine applies the change when it next starts.</Notice>
            </div>
          ) : null}
          <KeyValues
            items={[
              ["Type", DEVICE_TYPES[data.device_type] ?? data.device_type],
              ["IP address", data.ip_address ?? "–"],
              ["Location", data.location],
              ["Zone", String(config.zone || "–")],
              ["Role", DEVICE_ROLE_LABEL[role] ?? (role || "–")],
              ["Status", STATUS_LABEL[data.status] ?? data.status],
            ]}
          />
        </>
      )}
    </Card>
  );
}

function DeviceEditor({ record, linkCount, onDone }: { record: DeviceRecord; linkCount: number; onDone: (saved: boolean) => void }) {
  const queryClient = useQueryClient();
  const [location, setLocation] = useState(record.location);
  const [ip, setIp] = useState(record.ip_address ?? "");
  const [status, setStatus] = useState(record.status);
  const save = useMutation({
    mutationFn: () => patch<DeviceRecord>(`devices/${record.device_id}`, { location, ip_address: ip || null, status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["device", record.device_id] });
      queryClient.invalidateQueries({ queryKey: ["topology"] });
      // the simulation form's device choices come from the Topology Store too
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
      <label className="text-xs font-medium text-ink sm:col-span-3">
        Location
        <input className="field mt-1" value={location} onChange={(e) => setLocation(e.target.value)} required maxLength={120} />
      </label>
      <label className="text-xs font-medium text-ink">
        IP address
        <input className="field mt-1" value={ip} onChange={(e) => setIp(e.target.value)} />
      </label>
      <label className="text-xs font-medium text-ink">
        Status
        <select className="field mt-1" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="up">Up</option>
          <option value="down">Down</option>
          <option value="unknown">Unknown</option>
          <option value="decommissioned" disabled={linkCount > 0}>
            {linkCount > 0 ? "Decommissioned (retire its links first)" : "Decommissioned (retire)"}
          </option>
        </select>
      </label>
      {linkCount > 0 ? (
        <p className="text-xs text-ink-2 sm:col-span-3">
          To retire this device, first retire {linkCount === 1 ? "its link: open it" : `its ${linkCount} links: open each one`} from Connected links above
          and set its status to Decommissioned. A link cannot stay in the network once a device at either end is retired.
        </p>
      ) : null}
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
