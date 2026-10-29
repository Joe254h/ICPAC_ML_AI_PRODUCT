"use client";
/** Every ECMWF run's Week-2 forecast, newest first; earlier versions of a week on request. */
import Link from "next/link";
import { Fragment, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { useActor } from "@/lib/actor";
import { dateTime, day, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type { OperationalModel, ForecastRun } from "@/types/operational";
import { NoForecast, methodName } from "@/features/operational/shared";

/** The forecasts of each ECMWF run: the one of record first, then earlier versions. */
function byRun(runs: ForecastRun[]) {
  const groups = new Map<string, ForecastRun[]>();
  for (const run of runs) {
    const key = run.initialization.slice(0, 10);
    groups.set(key, [...(groups.get(key) ?? []), run]);
  }
  return [...groups.values()].map((items) => {
    const main = items.find((r) => r.of_record) ?? items[0];
    return { main, earlier: items.filter((r) => r !== main) };
  });
}

function Row({
  run,
  latest,
  earlier,
  model,
}: {
  run: ForecastRun;
  latest?: boolean;
  earlier?: boolean;
  /** The model's name, shown for another version of the week. */
  model?: string;
}) {
  return (
    <tr className={earlier ? "earlier-version" : undefined}>
      <td className="strong">
        {earlier ? "Other version" : validDays(run.valid_start, run.valid_end)}
        {latest && (
          <span style={{ marginLeft: 10 }}>
            <Status tone="info">Latest</Status>
          </span>
        )}
      </td>
      <td>{day(run.initialization)}, 00 UTC</td>
      <td>
        {methodName(run)}
        {model && (
          <span style={{ display: "block", color: "var(--muted)" }}>
            {model}
          </span>
        )}
      </td>
      <td>
        {run.verification_status === "available" ? (
          <Status tone="ok">Verified · CHIRPS</Status>
        ) : (
          <Status tone="progress">Awaiting CHIRPS</Status>
        )}
      </td>
      <td style={{ color: "var(--muted)" }}>{dateTime(run.generation_time)}</td>
      <td>
        <Link className="link-amber" href={`/forecasts?id=${run.forecast_id}`}>
          Open →
        </Link>
      </td>
    </tr>
  );
}

export default function Archive() {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const models = useApi<OperationalModel[]>("/models");
  const names = new Map(
    (models.data ?? []).map((m) => [m.model_id, m.model_name] as const),
  );
  const [actor] = useActor();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const task = useOperation(() => runs.reload());
  const groups = byRun(runs.data ?? []);
  const versions = groups.reduce((n, g) => n + g.earlier.length, 0);
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecast Archive"
          crumbs={[
            { label: "Forecasts", href: "/forecasts" },
            { label: "Archive" },
          ]}
          subtitle="One Week-2 forecast for each ECMWF run: the forecast of the model in use. A run forecast again keeps its earlier versions, one click away."
          actions={
            <Button
              variant="amber"
              disabled={task.running}
              onClick={() =>
                task.start("refresh_archive", actor || "Forecaster", {
                  weeks: 12,
                })
              }
              title="Forecast the newest twelve ECMWF runs again with the model in use where it has not forecast them, then verify the weeks CHIRPS covers"
            >
              <RefreshCw size={17} className={task.running ? "spin" : ""} />
              {task.running
                ? "Updating the archive…"
                : "Update to the model in use"}
            </Button>
          }
        />
        {task.operation && (
          <Notice
            tone={task.operation.status === "failed" ? "red" : "green"}
            title={task.operation.title}
          >
            {task.operation.messages.at(-1)?.text} ·{" "}
            <Link href="/data/runs">Task log</Link>
          </Notice>
        )}
        {task.error && <ErrorState message={task.error} />}
        {runs.loading && <Skeleton height={360} />}
        {runs.error && <ErrorState message={runs.error} retry={runs.reload} />}
        {runs.data && !runs.data.length && <NoForecast />}
        {groups.length > 0 && (
          <Card
            title={`${groups.length} forecast week${groups.length === 1 ? "" : "s"}`}
            subtitle={
              versions
                ? `${versions} other version${versions === 1 ? "" : "s"} of these weeks (earlier runs of the model, or other models) are kept for the record.`
                : undefined
            }
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Valid period (days 8–14)</th>
                    <th>ECMWF run</th>
                    <th>Issued from</th>
                    <th>Verification</th>
                    <th>Generated</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {groups.map(({ main, earlier }, index) => {
                    const key = main.initialization.slice(0, 10);
                    const shown = open.has(key);
                    return (
                      <Fragment key={main.forecast_id}>
                        <Row run={main} latest={index === 0} />
                        {earlier.length > 0 && (
                          <tr className="earlier-toggle">
                            <td colSpan={6}>
                              <button
                                type="button"
                                className="link-amber"
                                onClick={() =>
                                  setOpen((now) => {
                                    const next = new Set(now);
                                    if (next.has(key)) next.delete(key);
                                    else next.add(key);
                                    return next;
                                  })
                                }
                              >
                                {shown ? "Hide" : "Show"} {earlier.length} other
                                version
                                {earlier.length === 1 ? "" : "s"} of this week
                              </button>
                            </td>
                          </tr>
                        )}
                        {shown &&
                          earlier.map((run) => (
                            <Row
                              key={run.forecast_id}
                              run={run}
                              earlier
                              model={names.get(run.model_id)}
                            />
                          ))}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
