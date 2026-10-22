"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { post } from "@/lib/api";
import { fmtDateTime, fmtPct, fmtTime } from "@/lib/format";
import type { ActiveAlert, ActiveAlerts, Recommendation, Scenario, User } from "@/lib/types";
import { Lightbulb } from "./icons";
import { Button, Empty, Notice, StatusBadge, ToneIcon } from "./ui";

/**
 * One line for an alert. A forecast alert means the classifier finds the link likely to reach the critical
 * level; the regression's own figure is often lower, so it is given alongside, never as the level expected.
 */
export function alertHeadline(alert: ActiveAlert, critical = 90): string {
  if (alert.kind === "critical_now") return `Congested now at ${fmtPct(alert.current_pct, 0)}`;
  const when = alert.minutes_until != null && alert.minutes_until > 0 ? `in about ${alert.minutes_until} min` : "very soon";
  // this cycle's forecast (peak_predicted is the highest figure over the whole alert)
  const warned = alert.trajectory.filter((p) => p.warning).map((p) => p.predicted_pct);
  const forecast = warned.length ? ` (forecast up to ${fmtPct(Math.max(...warned), 0)})` : "";
  return `Likely to reach ${fmtPct(critical, 0)} ${when}${forecast}`;
}

/** Why forecasts may be missing: the models need some history first, and someone must have trained them. */
export function ForecastAvailability({ data }: { data: ActiveAlerts }) {
  if (data.model) return null;
  const have = data.history_cycles ?? 0;
  const need = data.short_model_needs ?? 60;
  // a model is used once the history is longer than it needs: past that, none has been trained
  if (have > need)
    return (
      <Notice tone="warning">
        No forecasting model is loaded, so there are no predictive alerts. A Senior Administrator needs to train one
        (manage.py train_models); see the{" "}
        <Link href="/system" className="text-accent-ink hover:underline">
          System page
        </Link>
        . Monitoring works meanwhile.
      </Notice>
    );
  return (
    <Notice tone="info">
      Forecasts start once the twin has {need} minutes of history for every link ({have} so far). Monitoring works meanwhile.
    </Notice>
  );
}

export function AlertSummary({ data, limit }: { data: ActiveAlerts; limit?: number }) {
  const alerts = limit ? data.alerts.slice(0, limit) : data.alerts;
  if (!data.model) return <ForecastAvailability data={data} />;
  if (alerts.length === 0)
    return (
      <div className="flex items-start gap-2 py-2 text-sm text-ink">
        <ToneIcon tone="good" />
        <div>
          No congestion expected in the next 30 minutes.
          <div className="text-xs text-ink-2">The prediction engine checks every link each cycle.</div>
        </div>
      </div>
    );
  return (
    <ul className="divide-y divide-line">
      {alerts.map((alert) => (
        <li key={alert.link_id} className="py-2.5 first:pt-0">
          <Link href={`/link?id=${alert.link_id}`} className="group flex items-start gap-2">
            <ToneIcon tone={alert.kind === "critical_now" ? "critical" : "serious"} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-ink group-hover:underline">{alert.label}</div>
              <div className="text-xs text-ink-2">{alertHeadline(alert, data.thresholds.critical_pct)}</div>
            </div>
            <span className="whitespace-nowrap text-xs text-ink-2">{alert.confidence_band} confidence</span>
          </Link>
        </li>
      ))}
      {limit && data.alerts.length > limit ? (
        <li className="pt-2 text-xs">
          <Link href="/alerts" className="text-accent-ink hover:underline">
            {data.alerts.length - limit} more…
          </Link>
        </li>
      ) : null}
    </ul>
  );
}

/**
 * One alert with its forecast and the recommended actions the twin has already simulated.
 * `critical`: the configured critical threshold (thresholds.critical_pct of the alerts response).
 */
export function AlertCard({ alert, user, critical = 90 }: { alert: ActiveAlert; user: User | undefined; critical?: number }) {
  const immediate = alert.recommendations.filter((r) => r.advice !== "planning");
  const planning = alert.recommendations.filter((r) => r.advice === "planning");
  return (
    <article className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={alert.kind === "critical_now" ? "critical" : "serious"} label={alert.kind === "critical_now" ? "Critical" : "Congestion predicted"} />
            <Link href={`/link?id=${alert.link_id}`} className="font-semibold text-ink hover:underline">
              {alert.label}
            </Link>
          </div>
          <p className="mt-1.5 text-sm text-ink">{alertHeadline(alert, critical)}.</p>
          <p className="mt-0.5 text-xs text-ink-2">
            Now {fmtPct(alert.current_pct)} · expected around {fmtTime(alert.predicted_time)} WAT · {alert.confidence_band} confidence (
            {Math.round(alert.confidence * 100)}% of the model&apos;s trees agree) · alert since {fmtDateTime(alert.started_at)}
          </p>
        </div>
      </div>

      {alert.trajectory.length ? (
        <div className="mt-3 overflow-x-auto">
          <table className="num text-xs">
            <caption className="sr-only">Forecast for this link</caption>
            <thead>
              <tr className="text-ink-2">
                <th scope="row" className="pr-4 text-left font-medium">
                  In
                </th>
                {alert.trajectory.map((p) => (
                  <th key={p.horizon_minutes} scope="col" className="px-3 text-right font-medium">
                    {p.horizon_minutes} min
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row" className="pr-4 text-left font-normal text-ink-2">
                  Predicted
                </th>
                {alert.trajectory.map((p) => (
                  <td key={p.horizon_minutes} className="px-3 text-right text-ink">
                    {fmtPct(p.predicted_pct, 0)}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row" className="pr-4 text-left font-normal text-ink-2">
                  Reaches {critical}%?
                </th>
                {alert.trajectory.map((p) => (
                  <td key={p.horizon_minutes} className="px-3 text-right text-ink">
                    {p.warning ? `likely (${Math.round(p.confidence * 100)}%)` : "no"}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="mt-4">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <Lightbulb size={15} /> Recommended actions
        </h3>
        {alert.recommendations.length === 0 ? (
          <p className="mt-1 text-sm text-ink-2">
            No change the twin tried would relieve this link without overloading another. Consider the planning options on the Trends page.
          </p>
        ) : (
          <div className="mt-2 space-y-2">
            {immediate.map((r) => (
              <RecommendationRow key={r.result_id} rec={r} user={user} />
            ))}
            {planning.length ? <div className="pt-1 text-xs font-medium text-ink-2">For planning (takes longer to put in place)</div> : null}
            {planning.map((r) => (
              <RecommendationRow key={r.result_id} rec={r} user={user} />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

function RecommendationRow({ rec, user }: { rec: Recommendation; user: User | undefined }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const copy = useMutation({
    // recommendation scenarios belong to the system user, so ask for them explicitly
    mutationFn: () => post<Scenario>(`scenarios/${rec.scenario_id}/copy?include=recommendations`),
    onSuccess: (scenario) => {
      queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      router.push(`/simulation?scenario=${scenario.scenario_id}`);
    },
  });
  return (
    <div className="rounded-md border border-line bg-surface-2 px-3 py-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-ink">
            {rec.rank ? `${rec.rank}. ` : ""}
            {rec.title}
          </div>
          <p className="mt-0.5 text-xs text-ink-2">{rec.summary}</p>
          {rec.link_after_pct != null ? <p className="num mt-0.5 text-xs text-ink">This link would be at {fmtPct(rec.link_after_pct, 0)}.</p> : null}
        </div>
        <div className="flex gap-2">
          <Link href={`/result?id=${rec.result_id}`} className="inline-flex items-center rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-medium text-ink hover:bg-surface-2">
            See simulation
          </Link>
          {user?.role === "senior" ? (
            // isSuccess too: the copy opens on the Simulation page, and until it does a second
            // press would make a second copy (this row is gone once the page has changed)
            <Button size="sm" onClick={() => copy.mutate()} disabled={copy.isPending || copy.isSuccess}>
              Try in simulator
            </Button>
          ) : null}
        </div>
      </div>
      {copy.error ? <p className="mt-1 text-xs text-danger-ink">{copy.error.message}</p> : null}
    </div>
  );
}

/** `critical`: the configured critical threshold (thresholds.critical_pct of the alerts response). */
export function NoAlerts({ critical = 90 }: { critical?: number }) {
  return (
    <Empty>
      <span className="inline-flex items-center gap-2">
        <ToneIcon tone="good" /> No link is expected to reach {critical}% in the next 30 minutes.
      </span>
    </Empty>
  );
}
