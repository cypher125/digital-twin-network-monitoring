"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { DataTable } from "@/components/DataTable";
import { Upload } from "@/components/icons";
import { Button, Card, ErrorNote, KeyValues, Loading, Notice, PageHeader, StatTile, StatusBadge } from "@/components/ui";
import { api, ApiError, post } from "@/lib/api";
import { engineBadge, fmtBytes, fmtCompact, fmtDateTime, fmtNumber, ROLE_LABEL } from "@/lib/format";
import { useLive, useMe, useSettings, useSystemStatus, useUsers } from "@/lib/queries";
import type { ImportReport, ModelInfo, User, UserRow } from "@/lib/types";

// The six tables of Table 3.2, in plain words (the table name is the tooltip). The two simulation
// tables also hold the scenarios and runs the twin makes itself for alerts, which the Simulation
// page leaves out, so their counts say so.
const TABLE_LABELS: Record<string, string> = {
  network_device: "Devices",
  network_link: "Links",
  monitoring_record: "Measurements",
  prediction: "Predictions",
  simulation_scenario: "Saved scenarios (including the twin's own)",
  simulation_result: "Simulation results (including the twin's own)",
};

const QUALITY_LABELS: Record<string, string> = {
  interfaces_expected: "Interfaces expected",
  interfaces_received: "Interfaces received",
  interfaces_missing: "Interfaces missing",
  spikes_rejected: "Spikes rejected",
  counter_resets: "Counter resets handled",
  utilisation_clipped: "Readings clipped to 100%",
  links_without_rate: "Links without a rate",
  unknown_elements: "Unknown elements ignored",
  cpu_rejected: "CPU readings rejected",
  flows_rejected: "Flow records rejected",
  capacity_changes: "Capacity changes detected",
};

const TIMING_LABELS: [string, string][] = [
  ["collect_ms", "Collect"],
  ["validate_ms", "Validate"],
  ["update_ms", "Update the model"],
  ["store_ms", "Store"],
  ["predict_ms", "Predict"],
  ["total_ms", "Whole cycle"],
  ["recommend_ms", "Fixes for the latest alert (alongside)"],
];

export function SystemView() {
  const status = useSystemStatus();
  const settings = useSettings();
  const me = useMe();
  const senior = me.data?.role === "senior";

  return (
    <div className="space-y-4">
      <PageHeader title="System" description="Health of the Digital Twin Engine, the forecasting models and the database, and administration." />
      {status.isPending ? (
        <Loading />
      ) : status.error || !status.data ? (
        <ErrorNote error={status.error} />
      ) : (
        <>
          <EngineCard status={status.data.engine} />
          <ModelsCard models={status.data.models} critical={status.data.thresholds.critical_pct} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Database">
              <KeyValues
                items={[
                  ["Server", status.data.database.server],
                  ["Size", fmtBytes(status.data.database.size_bytes)],
                  ...Object.entries(status.data.database.approximate_rows).map(([table, rows]): [ReactNode, ReactNode] => [
                    <span key={table} title={`Table ${table}`}>
                      {TABLE_LABELS[table] ?? table}
                    </span>,
                    // the small tables are counted exactly; the large ones are PostgreSQL's estimate
                    `${fmtCompact(Math.max(0, rows))} rows${status.data.database.exact_tables?.includes(table) ? "" : " (approx.)"}`,
                  ]),
                ]}
              />
            </Card>
            <Card title="Settings">
              {settings.data ? (
                <KeyValues
                  items={[
                    ["Thresholds", `warning ${settings.data.warning_pct}%, critical ${settings.data.critical_pct}%`],
                    ["Monitoring cycle", `${settings.data.cycle_seconds} s of network time`],
                    ["Forecast horizons", settings.data.horizons_minutes.map((h) => `${h} min`).join(", ")],
                    ["Warning rule", "classifier probability at or above the threshold each model learned in training (see Forecasting models)"],
                    ["Keep measurements", `${settings.data.monitoring_retention_days} days`],
                    ["Keep predictions", `${settings.data.prediction_retention_days} days`],
                    [
                      "Time zone",
                      settings.data.time_zone === "Africa/Lagos" ? (
                        <span title="Africa/Lagos">West Africa Time (WAT, UTC+1)</span>
                      ) : (
                        settings.data.time_zone
                      ),
                    ],
                  ]}
                />
              ) : (
                <Loading />
              )}
            </Card>
          </div>
        </>
      )}
      {senior ? <UsersCard /> : null}
      {senior ? <ImportCard /> : null}
      {me.data ? <PasswordCard user={me.data} /> : null}
    </div>
  );
}

function EngineCard({ status }: { status: NonNullable<ReturnType<typeof useSystemStatus>["data"]>["engine"] }) {
  // The badge follows the 1-second live poll, as the header does. This status is fetched again only when
  // a cycle is stored, so on its own it would still say "Running" after the engine stops or falls behind.
  const live = useLive().data;
  const state = live?.engine_state ?? status.state ?? "not running";
  const stale = live?.stale ?? status.stale;
  const running = state === "running";
  const badge = !running
    ? engineBadge(state, stale)
    : stale
      ? { tone: "warning" as const, label: "Running, data delayed" }
      : { tone: "good" as const, label: "Running" };
  const timings = status.timings ?? {};
  const quality = status.data_quality ?? {};
  return (
    <Card
      title="Digital Twin Engine"
      // the engine's own wording in full (the badge is a short word)
      subtitle={running ? undefined : `${state.charAt(0).toUpperCase()}${state.slice(1)}.`}
      actions={<StatusBadge tone={badge.tone} label={badge.label} size="md" title={`Engine: ${state}`} />}
    >
      {status.topology_changed ? (
        <div className="mb-3">
          <Notice tone="warning">
            The Topology Store has changed since the Digital Twin Engine started (devices or links were edited or imported).
            Restart the engine to use the changes; until then it monitors and simulates the network as it was when it started.
          </Notice>
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Cycles stored"
          value={fmtCompact(status.cycles_stored ?? 0)}
          detail={status.started_at ? `engine started ${fmtDateTime(status.started_at)} (server clock)` : undefined}
        />
        <StatTile label="Last cycle (network time)" value={status.last_cycle ? fmtDateTime(status.last_cycle).split(", ").pop() : "–"} detail={status.last_cycle ? fmtDateTime(status.last_cycle) : "none yet"} />
        <StatTile label="Whole cycle took" value={timings.total_ms != null ? `${fmtNumber(timings.total_ms)} ms` : "–"} detail="target: well under 5 s (NFR1)" tone={timings.total_ms != null ? (timings.total_ms < 5000 ? "good" : "critical") : undefined} />
        <StatTile
          label="Cycles missed"
          value={status.cycles_missed ?? 0}
          tone={(status.cycles_missed ?? 0) > 0 ? "warning" : "good"}
          detail="polls that came too late to read a cycle"
        />
      </div>
      <p className="mt-2 text-xs text-ink-2">
        {status.simulations_run ?? 0} simulations run and {status.recommendations_made ?? 0} recommendations made since the engine started
        {status.recommendations_pending ? `; ${status.recommendations_pending} alert(s) waiting for their fixes` : ""}.
      </p>
      {status.last_error ? (
        <div className="mt-3">
          <Notice tone="warning">Last error: {status.last_error}</Notice>
        </div>
      ) : null}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Data source</h3>
          <KeyValues
            items={[
              ["Name", status.source?.name ?? "–"],
              ["Mode", status.source?.mode ? `${status.source.mode}${status.source.mode === "live" && status.source.speed ? `, ${status.source.speed}× real time` : ""}` : "–"],
              ["Network time", fmtDateTime(status.source?.time)],
              ["Received (server clock)", fmtDateTime(status.last_received_at)],
            ]}
          />
        </div>
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Last cycle, step by step</h3>
          <table className="num w-full text-sm">
            <tbody>
              {TIMING_LABELS.map(([key, label]) => (
                <tr key={key} className={key === "total_ms" ? "border-t border-line font-medium" : undefined}>
                  <td className="py-0.5 text-ink-2">{label}</td>
                  <td className="py-0.5 text-right text-ink">{timings[key] != null ? `${fmtNumber(timings[key], 1)} ms` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Data quality, last cycle</h3>
          <table className="num w-full text-sm">
            <tbody>
              {Object.entries(QUALITY_LABELS).map(([key, label]) => (
                <tr key={key}>
                  <td className="py-0.5 text-ink-2">{label}</td>
                  <td className="py-0.5 text-right text-ink">{quality[key] ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {status.recent_events?.length ? (
        <div className="mt-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Recent network events</h3>
          <DataTable
            rows={status.recent_events}
            rowKey={(e) => `${e.network_time}-${e.element}-${e.type}`}
            dense
            columns={[
              { key: "time", header: "Network time", cell: (e) => fmtDateTime(e.network_time) },
              { key: "type", header: "Event", cell: (e) => e.type.replace(/_/g, " ") },
              { key: "element", header: "Element", cell: (e) => e.element },
              { key: "applied", header: "Applied to the twin in", numeric: true, cell: (e) => `${fmtNumber(e.applied_ms, 1)} ms` },
            ]}
          />
        </div>
      ) : null}
    </Card>
  );
}

function ModelsCard({ models, critical }: { models: ModelInfo[]; critical: number }) {
  if (models.length === 0) {
    return (
      <Card title="Forecasting models">
        <Notice>No trained model yet. Run “manage.py train_models” once the twin has collected history.</Notice>
      </Card>
    );
  }
  return (
    <Card
      title="Forecasting models"
      subtitle={`Random Forest regression (how busy) and classification (will it reach ${critical}%?), measured on held-out days`}
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {models.map((m) => {
          const horizons = Object.keys(m.mae_by_horizon).sort((a, b) => Number(a) - Number(b));
          return (
            <div key={m.kind}>
              <div className="mb-1 text-sm font-medium text-ink">
                {m.kind === "full" ? "Full model (uses yesterday's pattern)" : "Short-history model"}
              </div>
              <div className="mb-2 text-xs text-ink-2">
                {m.version} · trained {fmtDateTime(m.created_at)} (server clock) · {fmtBytes(m.size_bytes)}
                {m.rows?.train_samples ? ` · ${fmtCompact(m.rows.train_samples)} training samples` : ""}
                {m.warning_threshold != null ? ` · warns at probability ${m.warning_threshold}` : ""}
              </div>
              <table className="num w-full text-sm">
                <caption className="sr-only">Accuracy by forecast horizon</caption>
                <thead>
                  <tr className="border-b border-line text-xs text-ink-2">
                    <th scope="col" className="py-1 text-left font-medium">
                      Horizon
                    </th>
                    <th scope="col" className="py-1 text-right font-medium">
                      Error (MAE)
                    </th>
                    <th scope="col" className="py-1 text-right font-medium">
                      No-change baseline
                    </th>
                    <th scope="col" className="py-1 text-right font-medium">
                      Warning precision
                    </th>
                    <th scope="col" className="py-1 text-right font-medium">
                      Warning recall
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {horizons.map((h) => (
                    <tr key={h} className="border-b border-line last:border-0">
                      <td className="py-1 text-ink">{h} min</td>
                      <td className="py-1 text-right text-ink">{m.mae_by_horizon[h].toFixed(2)} pts</td>
                      <td className="py-1 text-right text-ink-2">{m.persistence_mae_by_horizon[h]?.toFixed(2) ?? "–"} pts</td>
                      <td className="py-1 text-right text-ink">{m.warning_quality[h] ? `${Math.round(m.warning_quality[h].precision * 100)}%` : "–"}</td>
                      <td className="py-1 text-right text-ink">{m.warning_quality[h] ? `${Math.round(m.warning_quality[h].recall * 100)}%` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-ink-2">
        MAE is the average gap between forecast and measured utilisation, in percentage points (lower is better). The no-change baseline assumes utilisation stays as it is now.
      </p>
    </Card>
  );
}

function UsersCard() {
  const users = useUsers(true);
  return (
    <Card title="Administrator accounts" subtitle="Accounts and roles are managed in the Django admin site (/admin)">
      {users.error ? (
        <ErrorNote error={users.error} />
      ) : (
        <DataTable<UserRow>
          rows={users.data ?? []}
          rowKey={(u) => u.username}
          columns={[
            { key: "user", header: "Username", sort: (u) => u.username, cell: (u) => u.username },
            { key: "name", header: "Name", sort: (u) => u.full_name, cell: (u) => u.full_name || "–" },
            { key: "role", header: "Role", sort: (u) => u.role, cell: (u) => ROLE_LABEL[u.role] },
            { key: "active", header: "Active", cell: (u) => (u.is_active ? "yes" : "no") },
            { key: "login", header: "Last sign-in (server clock)", sort: (u) => u.last_login ?? "", cell: (u) => fmtDateTime(u.last_login) },
          ]}
        />
      )}
    </Card>
  );
}

/** "1 new device", "3 new devices". */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The body of a refused import, when it is the import report (and not, say, "not valid YAML"). */
function isImportReport(body: unknown): body is ImportReport {
  if (typeof body !== "object" || body === null) return false;
  const report = body as Partial<ImportReport>;
  return typeof report.ok === "boolean" && Array.isArray(report.errors);
}

function ImportCard() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const send = useMutation({
    mutationFn: async (dryRun: boolean) => {
      const form = new FormData();
      form.append("file", file as File);
      form.append("dry_run", dryRun ? "true" : "false");
      try {
        return await api<ImportReport>("topology/import", { method: "POST", form });
      } catch (error) {
        // a file with problems comes back as HTTP 400 with the whole report: show it, problem by problem
        if (error instanceof ApiError && error.status === 400 && isImportReport(error.body)) return error.body;
        throw error;
      }
    },
    onSuccess: (data) => {
      setReport(data);
      if (data.ok && !data.dry_run) {
        // everything read from the Topology Store: the map, the device and link records, and the simulation form's choices
        for (const key of ["topology", "device", "link", "scenario-types"]) queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: () => setReport(null),
  });
  const skipped = report?.links_skipped ?? [];
  return (
    <Card title="Import topology" subtitle="Add or update devices and links from a YAML or JSON file (2 MB at most). Check first, then import.">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept=".yaml,.yml,.json"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setReport(null);
          }}
          className="text-sm text-ink file:mr-3 file:rounded-md file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-ink"
        />
        <Button onClick={() => send.mutate(true)} disabled={!file || send.isPending}>
          Check the file
        </Button>
        <Button variant="primary" onClick={() => send.mutate(false)} disabled={!file || send.isPending || !report?.ok || !report.dry_run}>
          <Upload size={14} /> Import
        </Button>
      </div>
      {send.error ? (
        <div className="mt-3">
          <ErrorNote error={send.error} title="The file was not accepted" />
        </div>
      ) : null}
      {report ? (
        <div className="mt-3">
          <Notice tone={!report.ok ? "critical" : skipped.length ? "warning" : "good"}>
            {report.ok ? (
              <>
                {report.dry_run ? "Check passed: " : "Imported: "}
                {plural(report.devices_created, "new device")} and {report.devices_updated} updated;{" "}
                {plural(report.links_created, "new link")} and {report.links_updated} updated.
                {report.dry_run
                  ? ""
                  : report.restart_needed === false
                    ? " No engine restart is needed: apart from map positions, nothing has changed."
                    : " The Digital Twin Engine uses them once it is restarted."}
                {skipped.length ? (
                  <>
                    <div className="mt-1">
                      {skipped.length === 1 ? "1 link" : `${skipped.length} links`} {report.dry_run ? "would be" : skipped.length === 1 ? "was" : "were"}{" "}
                      left out:
                    </div>
                    <ul className="mt-1 list-inside list-disc">
                      {skipped.map((line, index) => (
                        <li key={index}>{line}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </>
            ) : (
              <>
                {report.dry_run ? "The check" : "The import"} found {report.errors.length === 1 ? "1 problem" : `${report.errors.length} problems`}
                {report.dry_run ? "" : ", so nothing was changed"}. Correct the file and check it again.
              </>
            )}
            {report.errors.length ? (
              <ul className="mt-1 list-inside list-disc">
                {report.errors.map((error, index) => (
                  // the same message can appear twice (for two elements alike)
                  <li key={index}>{error}</li>
                ))}
              </ul>
            ) : null}
          </Notice>
        </div>
      ) : null}
    </Card>
  );
}

function PasswordCard({ user }: { user: User }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const change = useMutation({
    mutationFn: () => post<{ detail: string }>("auth/password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setAgain("");
    },
  });
  const mismatch = again.length > 0 && next !== again;
  return (
    <Card title="Change your password" subtitle={`Signed in as ${user.username}`}>
      <form
        id="password"
        className="grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!mismatch) change.mutate();
        }}
      >
        <label className="text-xs font-medium text-ink">
          Current password
          <input className="field mt-1" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <div>
          <label className="block text-xs font-medium text-ink">
            New password
            {/* the server's minimum length (AUTH_PASSWORD_VALIDATORS); its other rules are listed below */}
            <input
              className="field mt-1"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
              minLength={10}
              aria-describedby="password-rules"
            />
          </label>
          <p id="password-rules" className="mt-1 text-xs text-ink-2">
            At least 10 characters; not only numbers, not a common password and not close to your username or name.
          </p>
        </div>
        <label className="text-xs font-medium text-ink">
          New password again
          <input className="field mt-1" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        </label>
        <div className="sm:col-span-3">
          {mismatch ? <p className="mb-2 text-sm text-danger-ink">The new passwords do not match.</p> : null}
          {change.error ? <p className="mb-2 text-sm text-danger-ink">{change.error.message}</p> : null}
          {change.isSuccess ? <p className="mb-2 text-sm text-success-ink">Password changed.</p> : null}
          <Button type="submit" variant="primary" disabled={change.isPending || mismatch}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}
