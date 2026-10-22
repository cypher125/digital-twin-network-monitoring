"use client";

// Guided scenario form (UC3). The fields come from the server's scenario types, so
// the form always matches the rules the simulation engine checks.

import { useState } from "react";
import { fmtCapacity } from "@/lib/format";
import type { FieldSpec, ScenarioType, ScenarioTypes } from "@/lib/types";
import { Plus, X } from "./icons";
import { Button, cx, Segmented } from "./ui";

export type Params = Record<string, unknown>;

export const INTERNET = "internet";

export function TypePicker({ types, value, onChange }: { types: ScenarioType[]; value: string | null; onChange: (key: string) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {types.map((type) => (
        <button
          key={type.key}
          type="button"
          onClick={() => onChange(type.key)}
          aria-pressed={value === type.key}
          className={cx(
            // a column from the top: a button centres its content, and the grid stretches the shorter card of a row
            "flex flex-col justify-start rounded-md border px-3 py-2 text-left",
            value === type.key ? "border-accent bg-accent-wash" : "border-line bg-surface hover:bg-surface-2",
          )}
        >
          <div className="text-sm font-medium text-ink">
            {type.label}
            {type.tier === "could" ? <span className="ml-1.5 text-xs font-normal text-ink-2">(extra)</span> : null}
          </div>
          <div className="mt-0.5 text-xs text-ink-2">{type.description}</div>
        </button>
      ))}
    </div>
  );
}

function Label({ field, htmlFor }: { field: FieldSpec; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-ink">
      {field.label}
      {field.required ? null : <span className="font-normal text-ink-2"> (optional)</span>}
    </label>
  );
}

export function ParameterFields({ type, choices, params, onChange, disabled }: {
  type: ScenarioType;
  choices: ScenarioTypes["choices"];
  params: Params;
  onChange: (params: Params) => void;
  disabled?: boolean;
}) {
  const set = (name: string, value: unknown) => {
    const next = { ...params };
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete next[name];
    else next[name] = value;
    onChange(next);
  };
  return (
    <div className="space-y-3">
      {type.fields.map((field) => (
        <FieldInput key={field.name} field={field} choices={choices} value={params[field.name]} onChange={(v) => set(field.name, v)} disabled={disabled} />
      ))}
    </div>
  );
}

function FieldInput({ field, choices, value, onChange, disabled }: {
  field: FieldSpec;
  choices: ScenarioTypes["choices"];
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}) {
  const id = `field-${field.name}`;
  const optional = !field.required;
  switch (field.type) {
    case "number":
      return (
        <div>
          <Label field={field} htmlFor={id} />
          <input
            id={id}
            className="field num"
            type="number"
            step="any"
            min={field.min}
            max={field.max}
            value={value == null ? "" : String(value)}
            onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
            required={field.required}
            disabled={disabled}
          />
          {field.name === "percent" ? <p className="mt-1 text-xs text-ink-2">For example 30 for 30% more traffic, or −20 for 20% less.</p> : null}
        </div>
      );
    case "link":
      return (
        <div>
          <Label field={field} htmlFor={id} />
          <select id={id} className="field" value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} required={field.required} disabled={disabled}>
            <option value="">{optional ? "— any / not set —" : "Choose a link…"}</option>
            {choices.links.map((l) => (
              <option key={l.link_id} value={l.link_id}>
                {l.label} ({fmtCapacity(l.capacity_mbps)})
              </option>
            ))}
          </select>
        </div>
      );
    case "device":
    case "destination":
      return (
        <div>
          <Label field={field} htmlFor={id} />
          <select
            id={id}
            className="field"
            value={value == null ? "" : String(value)}
            onChange={(e) => {
              const v = e.target.value;
              onChange(v === "" ? undefined : v === INTERNET ? INTERNET : Number(v));
            }}
            required={field.required}
            disabled={disabled}
          >
            <option value="">{optional ? "— any / not set —" : "Choose…"}</option>
            {field.type === "destination" ? <option value={INTERNET}>The internet (through the ISP links)</option> : null}
            {choices.devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.name} ({d.device_type.replace("_", " ")}
                {d.zone ? `, ${d.zone}` : ""})
              </option>
            ))}
          </select>
        </div>
      );
    case "zone":
      return (
        <div>
          <Label field={field} htmlFor={id} />
          <select id={id} className="field" value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)} required={field.required} disabled={disabled}>
            <option value="">{optional ? "— any zone —" : "Choose a zone…"}</option>
            {choices.zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </div>
      );
    case "class":
      return (
        <div>
          <Label field={field} htmlFor={id} />
          <select id={id} className="field" value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)} required={field.required} disabled={disabled}>
            <option value="">{optional ? "— all traffic —" : "Choose a traffic class…"}</option>
            {choices.classes.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          {choices.classes.length === 0 ? <p className="mt-1 text-xs text-ink-2">Traffic classes appear once the twin has received flow data.</p> : null}
        </div>
      );
    case "links": {
      const selected = new Set(Array.isArray(value) ? (value as number[]) : []);
      return (
        <fieldset>
          <legend className="mb-1 block text-xs font-medium text-ink">{field.label}</legend>
          <div className="max-h-48 space-y-0.5 overflow-auto rounded-md border border-line p-2">
            {choices.links.map((l) => (
              <label key={l.link_id} className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={selected.has(l.link_id)}
                  disabled={disabled}
                  onChange={(e) => {
                    const next = new Set(selected);
                    if (e.target.checked) next.add(l.link_id);
                    else next.delete(l.link_id);
                    onChange([...next]);
                  }}
                />
                {l.label}
              </label>
            ))}
          </div>
        </fieldset>
      );
    }
    case "link_costs":
      return <LinkCosts field={field} choices={choices} value={value} onChange={onChange} disabled={disabled} />;
  }
}

function LinkCosts({ field, choices, value, onChange, disabled }: {
  field: FieldSpec;
  choices: ScenarioTypes["choices"];
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}) {
  const rows = Array.isArray(value) && value.length ? (value as { link_id?: number; cost?: number }[]) : [{}];
  const update = (index: number, patch: { link_id?: number; cost?: number }) => {
    const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange(next);
  };
  const costOf = (id?: number) => choices.links.find((l) => l.link_id === id)?.cost;
  return (
    <fieldset>
      <legend className="mb-1 block text-xs font-medium text-ink">{field.label}</legend>
      <div className="space-y-2">
        {rows.map((row, index) => (
          <div key={index} className="grid grid-cols-[1fr_7rem_auto] items-start gap-2">
            <select
              className="field"
              aria-label="Link"
              value={row.link_id ?? ""}
              disabled={disabled}
              onChange={(e) => update(index, { link_id: e.target.value === "" ? undefined : Number(e.target.value) })}
            >
              <option value="">Choose a link…</option>
              {choices.links.map((l) => (
                <option key={l.link_id} value={l.link_id}>
                  {l.label}
                </option>
              ))}
            </select>
            <div>
              <input
                className="field num"
                type="number"
                min={0.001}
                step="any"
                aria-label="New routing cost"
                placeholder="cost"
                value={row.cost ?? ""}
                disabled={disabled}
                onChange={(e) => update(index, { cost: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
              {costOf(row.link_id) != null ? <p className="mt-0.5 text-[11px] text-ink-2">now {costOf(row.link_id)}</p> : null}
            </div>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Remove this row"
              disabled={disabled || rows.length === 1}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              <X size={14} />
            </Button>
          </div>
        ))}
        <Button size="sm" onClick={() => onChange([...rows, {}])} disabled={disabled}>
          <Plus size={14} /> Another link
        </Button>
        <p className="text-xs text-ink-2">A higher cost makes routing avoid the link; equal costs share traffic between paths.</p>
      </div>
    </fieldset>
  );
}

export interface RunChoice {
  basis: "current" | "forecast";
  horizon_minutes: number;
}

export function RunOptions({ value, onChange, horizons }: { value: RunChoice; onChange: (value: RunChoice) => void; horizons: number[] }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-ink">Traffic to simulate with</div>
      <Segmented
        label="Traffic basis"
        value={value.basis}
        onChange={(basis) => onChange({ ...value, basis })}
        options={[
          { value: "current", label: "Current traffic" },
          { value: "forecast", label: "Forecast traffic" },
        ]}
      />
      {value.basis === "forecast" ? (
        <div className="flex items-center gap-2 text-sm text-ink">
          <span className="text-xs text-ink-2">as predicted in</span>
          <select className="field w-auto" value={value.horizon_minutes} onChange={(e) => onChange({ ...value, horizon_minutes: Number(e.target.value) })}>
            {horizons.map((h) => (
              <option key={h} value={h}>
                {h} minutes
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  );
}

/** A copy of the parameters with the empty rows of a link-cost list removed. */
export function cleanParams(params: Params): Params {
  const out: Params = { ...params };
  if (Array.isArray(out.link_costs)) {
    out.link_costs = (out.link_costs as { link_id?: number; cost?: number }[]).filter((row) => row.link_id != null || row.cost != null);
  }
  return out;
}

export function useScenarioDraft(initialType: string | null) {
  const [type, setType] = useState<string | null>(initialType);
  const [name, setName] = useState("");
  const [params, setParams] = useState<Params>({});
  return { type, setType, name, setName, params, setParams };
}
