"use client";
/** The weekly forecasts (Sunday runs), newest first, with this week's and the latest marked;
 * forecasts of other days' runs and earlier versions on request. */
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
import { dateTime, runTime, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type { OperationalModel, ForecastRun } from "@/types/operational";
import {
  NoForecast,
  coversToday,
  isWeekly,
  methodName,
} from "@/features/operational/shared";

/** Weeks shown before "Show all". */
const WEEKS = 12;

type Group = { main: ForecastRun; earlier: ForecastRun[] };

/** The forecasts of each ECMWF run: the one of record first, then earlier versions. */
function byRun(runs: ForecastRun[]): Group[] {
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
        {!earlier && latest && (
          <span style={{ marginLeft: 10 }}>
            <Status tone="info">Latest</Status>
          </span>
        )}
        {!earlier && coversToday(run) && (
          <span style={{ marginLeft: 10 }}>
            <Status tone="ok">This week</Status>
          </span>
        )}
      </td>
      <td>{runTime(run.initialization)}</td>
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

function Weeks({
  groups,
  names,
  latest,
}: {
  groups: Group[];
  names: Map<string, string>;
  latest?: string;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Week (days 8–14)</th>
            <th>ECMWF run</th>
            <th>Issued from</th>
            <th>Verification</th>
            <th>Generated</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {groups.map(({ main, earlier }) => {
            const key = main.initialization.slice(0, 10);
            const shown = open.has(key);
            return (
              <Fragment key={main.forecast_id}>
                <Row run={main} latest={main.forecast_id === latest} />
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
                        {shown ? "Hide" : "Show"} {earlier.length} other version
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
  );
}

export default function Archive() {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const models = useApi<OperationalModel[]>("/models");
  const names = new Map(
    (models.data ?? []).map((m) => [m.model_id, m.model_name] as const),
  );
  const [actor] = useActor();
  const [all, setAll] = useState(false);
  const [others, setOthers] = useState(false);
  const task = useOperation(() => runs.reload());
  const groups = byRun(runs.data ?? []);
  const weekly = groups.filter((g) => isWeekly(g.main));
  const other = groups.filter((g) => !isWeekly(g.main));
  const latest = (
    groups.find((g) => g.main.latest) ??
    weekly[0] ??
    groups[0]
  )?.main.forecast_id;
  const shown = all ? weekly : weekly.slice(0, WEEKS);
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecast Archive"
          crumbs={[
            { label: "Forecasts", href: "/forecasts" },
            { label: "Archive" },
          ]}
          subtitle="The weekly forecast is made every Sunday at midnight (EAT) from that Sunday's ECMWF run, for days 8 to 14: Sunday to Saturday of the week after next."
          actions={
            <Button
              variant="amber"
              disabled={task.running}
              onClick={() =>
                task.start("refresh_archive", actor || "Forecaster", {
                  weeks: WEEKS,
                })
              }
              title="Forecast each of the last twelve Sunday runs the model in use has not forecast yet, then verify the weeks CHIRPS covers"
            >
              <RefreshCw size={17} className={task.running ? "spin" : ""} />
              {task.running
                ? "Filling the last 12 weeks…"
                : "Fill the last 12 weeks"}
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
        {runs.data && runs.data.length > 0 && !weekly.length && (
          <Notice tone="amber" title="No weekly forecast yet">
            No forecast has been made from a Sunday&apos;s ECMWF run yet. Fill the
            last 12 weeks, or wait for Sunday&apos;s run.
          </Notice>
        )}
        {weekly.length > 0 && (
          <Card
            title={`Weekly forecasts · ${shown.length} of ${weekly.length} week${weekly.length === 1 ? "" : "s"}`}
            subtitle="Latest: the newest weekly forecast, which the website shows. This week: the forecast for the days we are in."
          >
            <Weeks groups={shown} names={names} latest={latest} />
            {weekly.length > WEEKS && (
              <Button
                variant="outline"
                style={{ marginTop: 14 }}
                onClick={() => setAll((now) => !now)}
              >
                {all ? `Show the last ${WEEKS} weeks` : "Show all weeks"}
              </Button>
            )}
          </Card>
        )}
        {other.length > 0 && (
          <Card
            title={`Forecasts of other runs · ${other.length}`}
            subtitle="Forecasts made from another day's ECMWF run (on request, or before the weekly schedule) are kept for the record."
          >
            <Button variant="outline" onClick={() => setOthers((now) => !now)}>
              {others ? "Hide them" : "Show them"}
            </Button>
            {others && (
              <div style={{ marginTop: 14 }}>
                <Weeks groups={other} names={names} latest={latest} />
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
