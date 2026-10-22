"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertCard, ForecastAvailability, NoAlerts } from "@/components/alerts";
import { DataTable } from "@/components/DataTable";
import { Card, ErrorNote, Loading, PageHeader, Segmented, StatusBadge } from "@/components/ui";
import { fmtDateTime, fmtMinutes, fmtPct, minutesBetween } from "@/lib/format";
import { useActiveAlerts, useAlertHistory, useMe } from "@/lib/queries";
import type { AlertHistory } from "@/lib/types";

type HistoryRow = AlertHistory["episodes"][number];

export function AlertsView() {
  const alerts = useActiveAlerts();
  const me = useMe();
  const [hours, setHours] = useState(24);
  const history = useAlertHistory(hours);
  const critical = alerts.data?.thresholds.critical_pct ?? 90;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Predictive congestion alerts"
        description={`The prediction engine forecasts every link 5, 10, 15 and 30 minutes ahead each cycle. An alert opens when a link is likely to reach ${critical}% and closes after five quiet cycles below 85%. For each new alert the twin simulates possible fixes and lists those that help.`}
      />

      {alerts.isPending ? (
        <Loading />
      ) : alerts.error || !alerts.data ? (
        <ErrorNote error={alerts.error} />
      ) : (
        <>
          <ForecastAvailability data={alerts.data} />
          {alerts.data.model ? (
            // the version name is for the System page and support; here it is only a tooltip (NFR3)
            <p className="text-xs text-ink-2" title={`Model version: ${alerts.data.model}`}>
              Model in use: {alerts.data.model_kind === "full" ? "full model (uses yesterday's pattern)" : "short-history model"}
              {/* the training run's own clock, as on the System page */}
              {alerts.data.model_trained_at ? `, trained ${fmtDateTime(alerts.data.model_trained_at)} (server clock)` : ""}
            </p>
          ) : null}
          {alerts.data.alerts.length === 0 && alerts.data.model ? (
            <Card>
              <NoAlerts critical={critical} />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {alerts.data.alerts.map((alert) => (
                <AlertCard key={alert.link_id} alert={alert} user={me.data} critical={critical} />
              ))}
            </div>
          )}
        </>
      )}

      <Card
        title="Alert history"
        subtitle="Episodes rebuilt from the stored predictions with the same rule the engine uses"
        actions={
          <Segmented
            label="Period"
            value={hours}
            onChange={setHours}
            options={[
              { value: 24, label: "24 h" },
              { value: 48, label: "48 h" },
            ]}
          />
        }
      >
        {history.error ? (
          <ErrorNote error={history.error} />
        ) : history.isPending ? (
          <Loading />
        ) : (
          <DataTable<HistoryRow>
            rows={history.data?.episodes ?? []}
            rowKey={(e) => `${e.link_id}-${e.started_at}`}
            initialSort={{ key: "start", desc: true }}
            maxHeight={480}
            empty="No alerts in this period."
            columns={[
              { key: "start", header: "Started (WAT)", sort: (e) => e.started_at, cell: (e) => fmtDateTime(e.started_at) },
              {
                key: "link",
                header: "Link",
                sort: (e) => e.label,
                cell: (e) => (
                  <Link href={`/link?id=${e.link_id}`} className="text-accent-ink hover:underline">
                    {e.label}
                  </Link>
                ),
              },
              {
                key: "state",
                header: "State",
                sort: (e) => (e.active ? 0 : 1),
                cell: (e) =>
                  e.active ? <StatusBadge tone="serious" label="Active" /> : <StatusBadge tone="good" label="Ended" />,
              },
              { key: "peak", header: "Highest forecast", numeric: true, sort: (e) => e.peak_predicted, cell: (e) => fmtPct(e.peak_predicted) },
              {
                key: "duration",
                header: "Duration",
                numeric: true,
                sort: (e) => minutesBetween(e.started_at, e.ended_at ?? e.last_warning_at),
                cell: (e) => {
                  const minutes = minutesBetween(e.started_at, e.ended_at ?? e.last_warning_at);
                  // an alert that warned in one cycle only started and last warned at the same time
                  return minutes != null && minutes < 1 ? "under 1 min" : fmtMinutes(minutes);
                },
              },
              { key: "conf", header: "Confidence", numeric: true, sort: (e) => e.confidence, cell: (e) => `${Math.round(e.confidence * 100)}%` },
            ]}
          />
        )}
      </Card>
    </div>
  );
}
