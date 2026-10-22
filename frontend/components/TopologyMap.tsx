"use client";

// Live network map (UC1, FR5): devices at their configured positions, links coloured
// by current utilisation (green / yellow / red, D1), line width by capacity, and a
// highlight on links the prediction engine warns about. The map updates in place
// each cycle, so zoom and pan are kept.

import type { Core, ElementDefinition, EventObject, StylesheetJson } from "cytoscape";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { DEFAULT_THRESHOLDS, DEVICE_TYPES, fmtCapacity, fmtMbps, fmtPct, HEALTH } from "@/lib/format";
import { useTokens, type Tokens } from "@/lib/theme";
import type { Health, Thresholds, Topology, TopologyDevice, TopologyLink } from "@/lib/types";
import { Maximize } from "./icons";
import { StatusBadge, ToneIcon } from "./ui";

// shapes that stay distinct at map and legend size (an octagon reads as a circle, a barrel as a square)
const SHAPES: Record<string, string> = {
  wan_gateway: "diamond",
  router: "ellipse",
  firewall: "hexagon",
  switch: "round-rectangle",
  server: "rectangle", // tall and narrow, see the stylesheet
  access_point: "triangle",
};

// No data shares the grey of Down (the axis grey is too faint on the dark theme); dots and dashes tell them apart
function healthColour(tokens: Tokens, health: Health): string {
  return { green: tokens.good, yellow: tokens.warning, red: tokens.critical, down: tokens.down, unknown: tokens.down }[health];
}

// 100 Mbps -> 2 px, 1 Gbps -> 3 px, 10 Gbps -> 4 px
function linkWidth(capacity: number): number {
  return Math.max(2, Math.min(5, Math.log10(Math.max(capacity, 10))));
}

function elementsOf(topology: Topology): ElementDefinition[] {
  const nodes: ElementDefinition[] = topology.devices.map((d, i) => ({
    group: "nodes",
    data: {
      id: `d${d.device_id}`,
      label: deviceLabel(d),
      shape: SHAPES[d.device_type] ?? "ellipse",
      deviceType: d.device_type,
      health: d.health,
      down: d.status === "down",
      big: d.role === "core" || d.role === "edge" || d.role === "wan",
    },
    position: d.position ? { x: d.position[0], y: d.position[1] } : { x: 80 * (i % 12), y: 700 + 60 * Math.floor(i / 12) },
  }));
  // A link must join two devices that are drawn: Cytoscape refuses an edge to a missing node, and the
  // whole map would fail. The API leaves out links to retired devices; this keeps the map safe regardless.
  const drawn = new Set(topology.devices.map((d) => d.device_id));
  const edges: ElementDefinition[] = topology.links.filter((l) => drawn.has(l.source_id) && drawn.has(l.dest_id)).map((l) => ({
    group: "edges",
    data: {
      id: `l${l.link_id}`,
      source: `d${l.source_id}`,
      target: `d${l.dest_id}`,
      health: l.health,
      width: linkWidth(l.capacity_mbps),
      warned: l.warning != null,
      down: l.status === "down",
      label: edgeLabel(l),
    },
  }));
  return [...nodes, ...edges];
}

// label selectively: only links that need attention carry their number on the map
function edgeLabel(l: TopologyLink): string {
  if (l.status === "down") return "Down";
  if (l.utilisation_pct == null) return "";
  if (l.warning) return `${Math.round(l.utilisation_pct)}% · in ${l.warning.horizon_minutes} min`;
  if (l.health === "red" || l.health === "yellow") return `${Math.round(l.utilisation_pct)}%`;
  return "";
}

// devices likewise: one that needs attention gets a second line, so its state is in words as well as colour
function deviceLabel(d: TopologyDevice): string {
  if (d.status === "down") return `${d.name}\nDown`;
  if (d.health === "unknown") return `${d.name}\nNo data`;
  if ((d.health === "red" || d.health === "yellow") && d.cpu_util != null) return `${d.name}\nCPU ${Math.round(d.cpu_util)}%`;
  return d.name;
}

function stylesheet(tokens: Tokens): StylesheetJson {
  return [
    {
      selector: "node",
      style: {
        shape: "data(shape)" as never,
        width: 22,
        height: 22,
        "background-color": tokens["surface-2"],
        "border-width": 2,
        "border-color": tokens["ink-2"],
        label: "data(label)",
        "font-size": 15,
        "font-family": "system-ui, -apple-system, Segoe UI, sans-serif",
        color: tokens["ink-2"],
        "text-valign": "bottom",
        "text-margin-y": 3,
        "text-wrap": "wrap",
        // opaque, so no link shows through a name
        "text-background-color": tokens.surface,
        "text-background-opacity": 1,
        "text-background-padding": "1px",
        "text-background-shape": "round-rectangle",
        "min-zoomed-font-size": 7,
      },
    },
    { selector: "node[?big]", style: { width: 28, height: 28, "font-weight": 600 as never, color: tokens.ink } },
    // servers are tall and narrow, labelled on the right so the data-centre column stays compact
    {
      selector: 'node[deviceType = "server"]',
      style: { width: 16, height: 24, "text-halign": "right", "text-valign": "center", "text-margin-x": 4, "text-margin-y": 0 },
    },
    { selector: 'node[health = "yellow"]', style: { "border-color": tokens.warning, "border-width": 3 } },
    { selector: 'node[health = "red"]', style: { "border-color": tokens.critical, "border-width": 3 } },
    // No data: grey dots (a near-zero dash with round caps); Down: grey dashes, as in the legend
    {
      selector: 'node[health = "unknown"]',
      style: { "border-color": tokens.down, "border-style": "dashed", "border-dash-pattern": [0.1, 4], "border-cap": "round", "background-opacity": 0.4 },
    },
    {
      selector: "node[?down]",
      style: { "border-color": tokens.down, "border-style": "dashed", "border-dash-pattern": [5, 3], "background-opacity": 0.4 },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "curve-style": "straight",
        "line-color": tokens.good,
        "line-cap": "round",
        label: "data(label)",
        "font-size": 12,
        "font-family": "system-ui, -apple-system, Segoe UI, sans-serif",
        color: tokens.ink,
        "text-background-color": tokens.surface,
        "text-background-opacity": 0.92,
        "text-background-padding": "2px",
        "text-background-shape": "round-rectangle",
        "min-zoomed-font-size": 6,
      },
    },
    { selector: 'edge[health = "yellow"]', style: { "line-color": tokens.warning } },
    { selector: 'edge[health = "red"]', style: { "line-color": tokens.critical } },
    { selector: 'edge[health = "unknown"]', style: { "line-color": tokens.down, "line-style": "dashed", "line-dash-pattern": [0.1, 6] } },
    // butt ends: round caps would close the gaps, and a Down link would read as a solid line
    {
      selector: "edge[?down]",
      style: { "line-color": tokens.down, "line-style": "dashed", "line-dash-pattern": [6, 4], "line-cap": "butt" },
    },
    {
      selector: "edge[?warned]",
      style: { "underlay-color": tokens.serious, "underlay-opacity": 0.45, "underlay-padding": 5 } as never,
    },
    { selector: "edge.hover, node.hover", style: { "overlay-color": tokens.ink, "overlay-opacity": 0.08, "overlay-padding": 6 } },
  ] as StylesheetJson;
}

// what is under the pointer, by id, so the tooltip shows the newest figures and goes when the element does
type Placement = { left: number; top?: number; bottom?: number };
type Hover = { kind: "link" | "device"; id: number; at: Placement };

// the tooltip is kept inside the map: w-64 plus a margin, and about the height of the tallest one
const TIP_WIDTH = 264;
const TIP_HEIGHT = 200;

export function TopologyMap({ topology, height = 520, navigate = true }: { topology: Topology; height?: number; navigate?: boolean }) {
  const router = useRouter();
  const tokens = useTokens();
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const latest = useRef(topology);
  const [hover, setHover] = useState<Hover | null>(null);
  const [ready, setReady] = useState(false);
  const [painted, setPainted] = useState(false);
  const clickable = useRef(navigate);

  // the map (created once, after an async import) and its event handlers read the newest props through these refs
  useEffect(() => {
    latest.current = topology;
    clickable.current = navigate;
  }, [topology, navigate]);

  // create the map once
  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    import("cytoscape").then(({ default: cytoscape }) => {
      if (disposed || !container.current) return;
      const cy = cytoscape({
        container: container.current,
        elements: elementsOf(latest.current),
        style: stylesheet(tokens),
        layout: { name: "preset", fit: true, padding: 28 },
        minZoom: 0.1, // a phone needs about 0.27 to show the whole campus
        maxZoom: 3,
        autoungrabify: true,
        boxSelectionEnabled: false,
        selectionType: "single",
      });
      const idOf = (event: EventObject) => Number(String(event.target.id()).slice(1));
      // next to the pointer, moved left near the right edge and above the pointer near the bottom
      const place = (event: EventObject): Placement => {
        const p = event.renderedPosition ?? { x: 0, y: 0 };
        const left = Math.max(0, Math.min(p.x + 14, cy.width() - TIP_WIDTH));
        const below = p.y + 14 + TIP_HEIGHT <= cy.height() || p.y < cy.height() / 2;
        return below ? { left, top: p.y + 14 } : { left, bottom: cy.height() - p.y + 14 };
      };
      cy.on("mouseover", "edge", (event) => {
        event.target.addClass("hover");
        setHover({ kind: "link", id: idOf(event), at: place(event) });
      });
      cy.on("mouseover", "node", (event) => {
        event.target.addClass("hover");
        setHover({ kind: "device", id: idOf(event), at: place(event) });
      });
      cy.on("mousemove", "edge, node", (event) => {
        const at = place(event);
        setHover((h) => (h ? { ...h, at } : h));
      });
      cy.on("mouseout", "edge, node", (event) => {
        event.target.removeClass("hover");
        setHover(null);
      });
      cy.on("tap", "edge", (event) => {
        const id = idOf(event);
        if (clickable.current && id > 0) router.push(`/link?id=${id}`);
      });
      cy.on("tap", "node", (event) => {
        if (clickable.current) router.push(`/device?id=${idOf(event)}`);
      });
      cy.one("render", () => setPainted(true)); // first frame drawn (the walkthrough waits for it)
      observer = new ResizeObserver(() => cy.resize());
      observer.observe(container.current);
      cyRef.current = cy;
      setReady(true);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      cyRef.current?.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- created once; updates below
  }, []);

  // new cycle: update the data in place (zoom and pan stay)
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const wanted = elementsOf(topology);
    const ids = new Set(wanted.map((e) => String(e.data.id)));
    cy.batch(() => {
      cy.elements().forEach((element) => {
        if (!ids.has(element.id())) element.remove();
      });
      for (const definition of wanted) {
        const existing = cy.getElementById(String(definition.data.id));
        if (existing.empty()) {
          cy.add(definition);
          continue;
        }
        existing.data(definition.data);
        // a device moved in the Topology Store (a re-import) moves here too, without reloading the page
        const to = definition.position;
        if (to && existing.isNode()) {
          const at = existing.position();
          if (at.x !== to.x || at.y !== to.y) existing.position({ x: to.x, y: to.y });
        }
      }
    });
  }, [topology, ready]);

  // theme change: restyle
  useEffect(() => {
    cyRef.current?.style(stylesheet(tokens));
  }, [tokens]);

  return (
    <div className="relative">
      <div
        ref={container}
        // no taller than the drawing needs on a phone, so the whole campus fits the width
        style={{ height: `min(${height}px, 62vw)` }}
        className="w-full rounded-md bg-surface"
        data-map-painted={painted ? "true" : "false"}
        role="img"
        aria-label={`Network map: ${topology.devices.length} devices and ${topology.links.length} links. The table view lists the same information.`}
      />
      <button
        type="button"
        onClick={() => cyRef.current?.fit(undefined, 28)}
        className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-2 hover:text-ink"
        title="Fit the whole network in view"
      >
        <Maximize size={13} />
        Fit
      </button>
      {hover ? <MapTooltip hover={hover} topology={topology} navigate={navigate} /> : null}
    </div>
  );
}

// looked up on every render, so the figures follow each cycle; nothing shows once the element has gone
function MapTooltip({ hover, topology, navigate }: { hover: Hover; topology: Topology; navigate: boolean }) {
  const style = hover.at;
  if (hover.kind === "link") {
    const l = topology.links.find((link) => link.link_id === hover.id);
    if (!l) return null;
    const meta = HEALTH[l.health];
    return (
      <div className="pointer-events-none absolute z-20 w-64 rounded-md border border-line bg-surface p-3 text-xs shadow-lg" style={style}>
        <div className="font-medium text-ink">{l.label}</div>
        <div className="mt-1.5 flex items-center gap-2">
          <StatusBadge tone={meta.tone} label={meta.label} />
          <span className="num text-ink">{fmtPct(l.utilisation_pct)}</span>
          <span className="text-ink-2">of {fmtCapacity(l.capacity_mbps)}</span>
        </div>
        <div className="num mt-1.5 grid grid-cols-2 gap-x-2 text-ink-2">
          <span>Out {fmtMbps(l.traffic_out)}</span>
          <span>In {fmtMbps(l.traffic_in)}</span>
        </div>
        {l.warning ? (
          <div className="mt-2 flex items-start gap-1.5 text-ink">
            <ToneIcon tone="serious" size={14} />
            <span>
              Likely to reach {fmtPct(topology.thresholds.critical_pct, 0)} within {l.warning.horizon_minutes} min (forecast{" "}
              {fmtPct(l.warning.predicted_pct)}, confidence {Math.round(l.warning.confidence * 100)}%)
            </span>
          </div>
        ) : null}
        {l.single_point_of_failure ? <div className="mt-1.5 text-ink-2">No backup path: a single point of failure.</div> : null}
        {navigate ? <div className="mt-1.5 text-muted">Click for details</div> : null}
      </div>
    );
  }
  const d = topology.devices.find((device) => device.device_id === hover.id);
  if (!d) return null;
  const meta = HEALTH[d.health];
  return (
    <div className="pointer-events-none absolute z-20 w-60 rounded-md border border-line bg-surface p-3 text-xs shadow-lg" style={style}>
      <div className="font-medium text-ink">{d.name}</div>
      <div className="text-ink-2">
        {DEVICE_TYPES[d.device_type] ?? d.device_type} · {d.ip_address ?? "no IP"}
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <StatusBadge tone={meta.tone} label={d.status === "down" ? "Down" : meta.label} />
        {d.cpu_util != null ? <span className="num text-ink">CPU {fmtPct(d.cpu_util, 0)}</span> : null}
      </div>
      <div className="mt-1 text-ink-2">{d.location}</div>
      {d.single_point_of_failure ? <div className="mt-1.5 text-ink-2">Single point of failure: its loss splits the network.</div> : null}
      {navigate ? <div className="mt-1.5 text-muted">Click for details</div> : null}
    </div>
  );
}

/** What the colours, widths and shapes on the map mean, with the thresholds the colours were worked out with. */
export function MapLegend({ thresholds = DEFAULT_THRESHOLDS }: { thresholds?: Thresholds }) {
  const tokens = useTokens();
  const { warning_pct: warning, critical_pct: critical } = thresholds;
  const lines: [Health, string][] = [
    ["green", `Normal (below ${warning}%)`],
    ["yellow", `Warning (${warning}–${critical}%)`],
    ["red", `Critical (${critical}% or more)`],
    ["down", "Down"],
    ["unknown", "No data"],
  ];
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink-2">
      {lines.map(([health, text]) => (
        <span key={health} className="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden>
            {/* dashes for Down and dots for No data, as drawn on the map */}
            <line
              x1="1"
              y1="4"
              x2="21"
              y2="4"
              stroke={healthColour(tokens, health)}
              strokeWidth={3}
              strokeLinecap={health === "down" ? "butt" : "round"}
              strokeDasharray={health === "down" ? "5 3" : health === "unknown" ? "0.1 5" : undefined}
            />
          </svg>
          <ToneIcon tone={HEALTH[health].tone} size={13} />
          {text}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <svg width="22" height="12" aria-hidden>
          <line x1="2" y1="6" x2="20" y2="6" stroke={tokens.serious} strokeOpacity={0.45} strokeWidth={10} strokeLinecap="round" />
          <line x1="2" y1="6" x2="20" y2="6" stroke={tokens.good} strokeWidth={3} strokeLinecap="round" />
        </svg>
        <ToneIcon tone="serious" size={13} />
        Congestion predicted
      </span>
      <span>Thicker line = higher capacity</span>
      {SHAPE_KEY.map(([label, glyph]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden fill={tokens["surface-2"]} stroke={tokens["ink-2"]} strokeWidth={1.5}>
            {glyph}
          </svg>
          {label}
        </span>
      ))}
    </div>
  );
}

const SHAPE_KEY: [string, React.ReactNode][] = [
  ["ISP gateway", <path key="d" d="M7 1.5 12.5 7 7 12.5 1.5 7Z" />],
  ["Router", <circle key="c" cx="7" cy="7" r="5.5" />],
  ["Firewall", <path key="h" d="M1.5 7 4.25 1.5h5.5L12.5 7l-2.75 5.5h-5.5Z" />],
  ["Switch", <rect key="r" x="1.5" y="1.5" width="11" height="11" rx="2.5" />],
  ["Server", <rect key="s" x="3.5" y="1.5" width="7" height="11" />],
  ["Access point", <path key="t" d="M7 1.5 12.5 12.5H1.5Z" />],
];
