"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { DataTable } from "@/components/DataTable";
import { Copy, Play, Plus, Trash } from "@/components/icons";
import { cleanParams, ParameterFields, RunOptions, TypePicker, type Params, type RunChoice } from "@/components/ScenarioForm";
import { Button, Card, ErrorNote, Loading, Notice, PageHeader, StatusBadge } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { fmtDateTime, fmtNumber } from "@/lib/format";
import { useMe, useResults, useScenario, useScenarios, useScenarioTypes, useSettings } from "@/lib/queries";
import type { ResultListItem, RunState, Scenario, ScenarioTypes } from "@/lib/types";

export const RUN_TONE: Record<RunState, { tone: "good" | "info" | "critical" | "unknown"; label: string }> = {
  queued: { tone: "unknown", label: "Queued" },
  running: { tone: "info", label: "Running" },
  completed: { tone: "good", label: "Completed" },
  failed: { tone: "critical", label: "Failed" },
};

/** The account that owns the scenarios the twin makes itself to try fixes for alerts (the server's SYSTEM_USERNAME). */
const SYSTEM_USER = "dt-system";

/** How many more saved scenarios "Show older" asks for (the server's page size). */
const SCENARIO_PAGE = 100;

/** A scenario that was saved although its run could not be started, and the traffic choice that run asked for. */
interface UnstartedRun {
  scenarioId: number;
  run: RunChoice;
  error: unknown;
}

export function SimulationConsole() {
  const search = useSearchParams();
  const router = useRouter();
  const me = useMe();
  const types = useScenarioTypes();
  const [scenarioLimit, setScenarioLimit] = useState(SCENARIO_PAGE);
  const scenarios = useScenarios(scenarioLimit);
  const results = useResults();
  const senior = me.data?.role === "senior";
  const openId = Number(search.get("scenario")) || null;
  const [runTarget, setRunTarget] = useState<Scenario | null>(null);
  // Kept here, not in the builder: saving a new scenario opens it, and the builder is remounted
  // for each scenario it shows, which would lose the message.
  const [unstarted, setUnstarted] = useState<UnstartedRun | null>(null);
  const shown = scenarios.data?.results.length ?? 0;
  const total = scenarios.data?.count ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Simulation console"
        description="Try a change on a copy of the twin's network model and see its effect before doing it for real. Nothing here changes the real network or the live model."
      />
      {!senior ? (
        <Notice>
          You can look at scenarios and results. Only a Senior Administrator can create or run scenarios.
        </Notice>
      ) : null}

      {/* one column below xl; min-w-0 lets a wide table scroll inside its card rather than widen the page */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-5">
          {types.isPending ? (
            <Loading />
          ) : types.error || !types.data ? (
            <ErrorNote error={types.error} />
          ) : senior ? (
            <ScenarioBuilder
              key={openId ?? "new"}
              types={types.data}
              openId={openId}
              onClose={() => router.replace("/simulation")}
              unstarted={unstarted?.scenarioId === openId ? unstarted : null}
              onUnstarted={setUnstarted}
            />
          ) : openId ? (
            <ScenarioBuilder key={openId} types={types.data} openId={openId} onClose={() => router.replace("/simulation")} readOnly />
          ) : null}
        </div>

        <div className="min-w-0 space-y-4 xl:col-span-7">
          <Card title="Saved scenarios" subtitle="Scenarios with results cannot be edited, so every result matches what produced it">
            {scenarios.error ? (
              <ErrorNote error={scenarios.error} />
            ) : scenarios.isPending ? (
              <Loading />
            ) : (
              <>
                <ScenarioTable
                  scenarios={scenarios.data?.results ?? []}
                  types={types.data}
                  senior={senior}
                  onRun={(s) => setRunTarget(s)}
                />
                {total > shown ? (
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-2">
                    <span>
                      Showing the newest {fmtNumber(shown)} of {fmtNumber(total)} scenarios.
                    </span>
                    <Button size="sm" onClick={() => setScenarioLimit((limit) => limit + SCENARIO_PAGE)} disabled={scenarios.isPlaceholderData}>
                      {scenarios.isPlaceholderData ? "Loading…" : "Show older"}
                    </Button>
                  </div>
                ) : null}
              </>
            )}
          </Card>
          <Card title="Recent runs">
            {results.error ? (
              <ErrorNote error={results.error} />
            ) : results.isPending ? (
              <Loading />
            ) : (
              <ResultTable results={results.data?.results ?? []} />
            )}
          </Card>
        </div>
      </div>

      <RunDialog scenario={runTarget} onClose={() => setRunTarget(null)} />
    </div>
  );
}

function defaultName(label: string) {
  return label;
}

function ScenarioBuilder({ types, openId, onClose, readOnly, unstarted, onUnstarted }: {
  types: ScenarioTypes;
  openId: number | null;
  onClose: () => void;
  readOnly?: boolean;
  /** set when this scenario was saved but its run could not be started */
  unstarted?: UnstartedRun | null;
  onUnstarted?: (value: UnstartedRun | null) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const existing = useScenario(openId);
  const settings = useSettings();
  const [typeKey, setTypeKey] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [params, setParams] = useState<Params>({});
  // after a refused run the scenario opens with the traffic choice that run asked for, ready to try again
  const [run, setRun] = useState<RunChoice>(unstarted?.run ?? { basis: "current", horizon_minutes: 30 });
  const loaded = useRef(false);

  useEffect(() => {
    if (existing.data && !loaded.current) {
      loaded.current = true;
      setTypeKey(existing.data.scenario_type);
      setName(existing.data.scenario_name);
      setParams(Object.fromEntries(Object.entries(existing.data.parameters).filter(([k]) => k !== "trigger")));
    }
  }, [existing.data]);

  const type = types.types.find((t) => t.key === typeKey) ?? null;
  // the twin's own scenarios (fixes it tried for an alert) can be copied, but not changed or run
  const system = existing.data?.created_by === SYSTEM_USER;
  const locked = readOnly || system || (existing.data?.runs ?? 0) > 0;

  const save = useMutation({
    mutationFn: async (andRun: boolean) => {
      const body = { scenario_name: name.trim() || defaultName(type?.label ?? "Scenario"), scenario_type: typeKey, parameters: cleanParams(params) };
      const scenario = openId ? await patch<Scenario>(`scenarios/${openId}`, body) : await post<Scenario>("scenarios", body);
      let result: ResultListItem | null = null;
      let runError: unknown = null;
      if (andRun) {
        try {
          result = await post<ResultListItem>(`scenarios/${scenario.scenario_id}/run`, run);
        } catch (error) {
          // the scenario is saved all the same: say so, rather than "not saved", which invites a duplicate
          runError = error;
        }
      }
      return { scenario, result, runError };
    },
    onMutate: () => onUnstarted?.(null),
    onSuccess: ({ scenario, result, runError }) => {
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      queryClient.invalidateQueries({ queryKey: ["scenario", scenario.scenario_id] });
      queryClient.invalidateQueries({ queryKey: ["results"] });
      if (result) {
        router.push(`/result?id=${result.result_id}`);
        return;
      }
      // open the saved scenario, so that the next press saves to it instead of creating another
      if (runError != null) onUnstarted?.({ scenarioId: scenario.scenario_id, run, error: runError });
      router.replace(`/simulation?scenario=${scenario.scenario_id}`);
    },
  });
  // After a save the builder is replaced: by the result, or (for a new scenario) by the saved one.
  // Until then the buttons stay disabled, so that a second press cannot save or run it twice.
  const leaving = save.isSuccess && (save.data.result != null || !openId);

  const copy = useMutation({
    // recommendation scenarios belong to the system user, so ask for them explicitly
    mutationFn: () => post<Scenario>(`scenarios/${openId}/copy?include=recommendations`),
    onSuccess: (scenario) => {
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      router.replace(`/simulation?scenario=${scenario.scenario_id}`);
    },
  });

  if (openId && existing.isPending) return <Loading />;
  if (openId && existing.error) return <ErrorNote error={existing.error} title="Could not open the scenario" />;

  return (
    <Card
      title={openId ? (locked ? "Scenario" : "Edit scenario") : "New scenario"}
      subtitle={
        openId && existing.data
          ? `Created by ${system ? "the twin for an alert" : existing.data.created_by} on ${fmtDateTime(existing.data.created_at)} (server clock)`
          : "1. Choose the kind of change. 2. Fill in the details. 3. Run."
      }
      actions={
        openId ? (
          <Button size="sm" variant="ghost" onClick={onClose}>
            <Plus size={14} /> New scenario
          </Button>
        ) : null
      }
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(true);
        }}
      >
        {!openId ? (
          <TypePicker
            types={types.types}
            value={typeKey}
            onChange={(key) => {
              setTypeKey(key);
              setParams({});
              setName(types.types.find((t) => t.key === key)?.label ?? "");
            }}
          />
        ) : null}

        {type ? (
          <>
            <div className="rounded-md bg-surface-2 px-3 py-2 text-sm text-ink">
              <span className="font-medium">{type.label}.</span> <span className="text-ink-2">{type.description}</span>
            </div>
            <div>
              <label htmlFor="scenario-name" className="mb-1 block text-xs font-medium text-ink">
                Scenario name
              </label>
              <input id="scenario-name" className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required disabled={locked} />
            </div>
            <ParameterFields type={type} choices={types.choices} params={params} onChange={setParams} disabled={locked} />

            {locked ? (
              readOnly ? null : (
                <Notice>
                  {system
                    ? "The twin made this scenario itself to try a fix for an alert, so it cannot be changed or run here."
                    : "This scenario has been run, so it cannot be changed."}{" "}
                  {/* the copy opens in place of this builder, so the button stays disabled until it does */}
                  <button type="button" className="text-accent-ink underline" onClick={() => copy.mutate()} disabled={copy.isPending || copy.isSuccess}>
                    {system ? "Make a copy to change or run it" : "Make a copy to change it"}
                  </button>
                  .
                </Notice>
              )
            ) : (
              <>
                <RunOptions value={run} onChange={setRun} horizons={settings.data?.horizons_minutes ?? [5, 10, 15, 30]} />
                {save.error ? <ErrorNote error={save.error} title="The scenario was not saved" /> : null}
                {unstarted ? <ErrorNote error={unstarted.error} title="Saved, but the run could not be started" /> : null}
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" variant="primary" disabled={save.isPending || leaving}>
                    <Play size={14} /> {save.isPending || leaving ? "Working…" : "Save and run"}
                  </Button>
                  <Button onClick={() => save.mutate(false)} disabled={save.isPending || leaving}>
                    Save only
                  </Button>
                </div>
              </>
            )}
            {locked && !readOnly && !system ? (
              <div className="space-y-2">
                <RunOptions value={run} onChange={setRun} horizons={settings.data?.horizons_minutes ?? [5, 10, 15, 30]} />
                <RunButton scenarioId={openId!} run={run} />
              </div>
            ) : null}
            {copy.error ? <ErrorNote error={copy.error} title="Not copied" /> : null}
          </>
        ) : null}
      </form>
    </Card>
  );
}

function RunButton({ scenarioId, run, label = "Run again" }: { scenarioId: number; run: RunChoice; label?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: () => post<ResultListItem>(`scenarios/${scenarioId}/run`, run),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["results"] });
      // the scenario now has a run, so it can no longer be changed or deleted
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      queryClient.invalidateQueries({ queryKey: ["scenario", scenarioId] });
      router.push(`/result?id=${result.result_id}`);
    },
  });
  // the result page replaces this button; until it opens, a second press would start a second run
  const starting = start.isPending || start.isSuccess;
  return (
    <div>
      <Button variant="primary" onClick={() => start.mutate()} disabled={starting}>
        <Play size={14} /> {starting ? "Starting…" : label}
      </Button>
      {start.error ? <p className="mt-1 text-sm text-danger-ink">{start.error.message}</p> : null}
    </div>
  );
}

function ScenarioTable({ scenarios, types, senior, onRun }: {
  scenarios: Scenario[];
  types: ScenarioTypes | undefined;
  senior: boolean;
  onRun: (scenario: Scenario) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const label = (key: string) => types?.types.find((t) => t.key === key)?.label ?? key;
  const remove = useMutation({
    mutationFn: (id: number) => del(`scenarios/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scenarios"] }),
  });
  const copy = useMutation({
    mutationFn: (id: number) => post<Scenario>(`scenarios/${id}/copy`),
    onSuccess: (scenario) => {
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      router.replace(`/simulation?scenario=${scenario.scenario_id}`);
    },
  });
  return (
    <>
      {remove.error || copy.error ? (
        <div className="mb-2 space-y-2">
          {remove.error ? <ErrorNote error={remove.error} title="Not deleted" /> : null}
          {copy.error ? <ErrorNote error={copy.error} title="Not copied" /> : null}
        </div>
      ) : null}
      <DataTable<Scenario>
        rows={scenarios}
        rowKey={(s) => s.scenario_id}
        maxHeight={360}
        initialSort={{ key: "created", desc: true }}
        empty="No scenarios yet."
        columns={[
          {
            key: "name",
            header: "Name",
            sort: (s) => s.scenario_name.toLowerCase(),
            cell: (s) => (
              <Link href={`/simulation?scenario=${s.scenario_id}`} className="text-accent-ink hover:underline">
                {s.scenario_name}
              </Link>
            ),
          },
          { key: "type", header: "Change", sort: (s) => label(s.scenario_type), cell: (s) => label(s.scenario_type) },
          // left out on phones, where the table is wider than the screen
          { key: "by", header: "By", className: "hidden sm:table-cell", sort: (s) => s.created_by, cell: (s) => s.created_by },
          { key: "created", header: "Created (server clock)", sort: (s) => s.created_at, cell: (s) => fmtDateTime(s.created_at) },
          { key: "runs", header: "Runs", numeric: true, sort: (s) => s.runs, cell: (s) => s.runs },
          ...(senior
            ? [
                {
                  key: "actions",
                  header: <span className="sr-only">Actions</span>,
                  cell: (s: Scenario) => (
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" title="Run" aria-label={`Run ${s.scenario_name}`} onClick={() => onRun(s)}>
                        <Play size={14} />
                      </Button>
                      {/* isPending only: this table stays on screen after a copy opens, so isSuccess would block every later copy */}
                      <Button
                        size="sm"
                        variant="ghost"
                        title="Copy"
                        aria-label={`Copy ${s.scenario_name}`}
                        onClick={() => copy.mutate(s.scenario_id)}
                        disabled={copy.isPending}
                      >
                        <Copy size={14} />
                      </Button>
                      {/* always three buttons, so that they line up from row to row */}
                      <Button
                        size="sm"
                        variant="ghost"
                        title={s.runs > 0 ? "Scenarios that have been run cannot be deleted" : "Delete"}
                        aria-label={`Delete ${s.scenario_name}`}
                        disabled={s.runs > 0 || remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete the scenario "${s.scenario_name}"?`)) remove.mutate(s.scenario_id);
                        }}
                      >
                        <Trash size={14} />
                      </Button>
                    </div>
                  ),
                },
              ]
            : []),
        ]}
      />
    </>
  );
}

export function ResultTable({ results }: { results: ResultListItem[] }) {
  return (
    <DataTable<ResultListItem>
      rows={results}
      rowKey={(r) => r.result_id}
      maxHeight={360}
      initialSort={{ key: "requested", desc: true }}
      empty="No runs yet."
      columns={[
        {
          key: "name",
          header: "Scenario",
          sort: (r) => r.scenario_name.toLowerCase(),
          cell: (r) => (
            <Link href={`/result?id=${r.result_id}`} className="text-accent-ink hover:underline">
              {r.scenario_name}
            </Link>
          ),
        },
        { key: "status", header: "Status", sort: (r) => r.status, cell: (r) => <StatusBadge tone={RUN_TONE[r.status].tone} label={RUN_TONE[r.status].label} /> },
        { key: "requested", header: "Requested (server clock)", sort: (r) => r.requested_at, cell: (r) => fmtDateTime(r.requested_at) },
        { key: "by", header: "By", sort: (r) => r.run_by ?? "", cell: (r) => r.run_by ?? "–" },
        { key: "summary", header: "Result", cell: (r) => <span className="line-clamp-2 text-xs text-ink-2">{r.summary || "–"}</span> },
      ]}
    />
  );
}

function RunDialog({ scenario, onClose }: { scenario: Scenario | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const settings = useSettings();
  const [run, setRun] = useState<RunChoice>({ basis: "current", horizon_minutes: 30 });
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (scenario && !element.open) element.showModal();
    if (!scenario && element.open) element.close();
  }, [scenario]);
  return (
    <dialog
      ref={dialog}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="m-auto w-[min(92vw,440px)] rounded-lg border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40"
      aria-labelledby="run-dialog-title"
    >
      {scenario ? (
        <div className="space-y-4 p-5">
          <div>
            <h2 id="run-dialog-title" className="text-base font-semibold">
              Run “{scenario.scenario_name}”
            </h2>
            <p className="mt-1 text-sm text-ink-2">The twin runs it on a copy of the live model, usually within a second.</p>
          </div>
          <RunOptions value={run} onChange={setRun} horizons={settings.data?.horizons_minutes ?? [5, 10, 15, 30]} />
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <RunButton scenarioId={scenario.scenario_id} run={run} label="Run" />
          </div>
        </div>
      ) : null}
    </dialog>
  );
}
