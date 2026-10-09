"use client";
/** Operations: run the weekly cycle (or one step) and follow every task. */
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  CloudDownload,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  KeyValues,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import type { Tone } from "@/components/ui";
import { useApp } from "@/components/shell";
import { useActor } from "@/lib/actor";
import { dateTime } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type { Operation, OperationAction } from "@/types/operational";

const TONE: Record<Operation["status"], Tone> = {
  queued: "info",
  running: "progress",
  complete: "ok",
  failed: "bad",
  interrupted: "bad",
};

const STEPS: {
  action: OperationAction;
  title: string;
  text: string;
  icon: typeof Play;
}[] = [
  {
    action: "fetch_ecmwf",
    title: "Download ECMWF only",
    text: "Fetch the ensemble rainfall of a 00 UTC run.",
    icon: CloudDownload,
  },
  {
    action: "run_forecast",
    title: "Run the forecast only",
    text: "Forecast from a run (downloaded first if needed).",
    icon: Play,
  },
  {
    action: "verify_due",
    title: "Verify finished forecasts",
    text: "Fetch CHIRPS for every week that has ended.",
    icon: CheckCircle2,
  },
  {
    action: "update_chirps",
    title: "Update rainfall monitoring",
    text: "Download the newest CHIRPS dekad, if there is one.",
    icon: BarChart3,
  },
];

function duration(operation: Operation) {
  if (!operation.started_at) return "—";
  const end = operation.finished_at
    ? new Date(operation.finished_at)
    : new Date();
  const seconds = Math.max(
    0,
    (end.getTime() - new Date(operation.started_at).getTime()) / 1000,
  );
  return seconds < 90
    ? `${Math.round(seconds)} s`
    : `${Math.round(seconds / 60)} min`;
}

function Timeline({ operation }: { operation: Operation }) {
  return (
    <ol className="timeline">
      {operation.messages.map((message, index) => (
        <li key={index}>
          <time>{message.time.slice(11, 19)} UTC</time>
          {message.text}
        </li>
      ))}
    </ol>
  );
}

function resultLink(operation: Operation) {
  const forecast = operation.result?.forecast_id;
  if (typeof forecast === "string")
    return (
      <Link className="link-amber" href={`/forecasts?id=${forecast}`}>
        Open forecast →
      </Link>
    );
  return null;
}

export default function Operations() {
  const history = useApi<Operation[]>("/operations");
  const { refresh } = useApp();
  const [actor, setActor] = useActor();
  const [date, setDate] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const { operation, error, running, start, follow } = useOperation(() => {
    history.reload();
    refresh();
  });

  // A task started elsewhere (another tab, the scheduler) is followed here too.
  useEffect(() => {
    const active = history.data?.find(
      (o) => o.status === "running" || o.status === "queued",
    );
    if (active && !operation) follow(active);
  }, [history.data, operation, follow]);

  const name = actor.trim();
  const launch = (action: OperationAction) =>
    start(action, name || "Forecaster", date ? { initialization: date } : {});

  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Operations"
          crumbs={[
            { label: "Data & Tools", href: "/data" },
            { label: "Operations" },
          ]}
          subtitle="Run the weekly Week-2 cycle: download the newest ECMWF ensemble, issue the forecast and verify finished forecasts against CHIRPS. Every task is recorded with who started it."
        />
        <div className="split" style={{ alignItems: "stretch" }}>
          <Card eyebrow="Weekly cycle" title="Issue this week's forecast">
            <ol
              style={{
                margin: "0 0 20px",
                paddingLeft: 22,
                display: "grid",
                gap: 8,
              }}
            >
              <li>
                Download the newest 00 UTC ECMWF ensemble (or the date chosen
                below).
              </li>
              <li>
                Run the Week-2 forecast and publish its product package, maps
                and bulletin inputs.
              </li>
              <li>
                Verify every earlier forecast whose week CHIRPS now covers, and
                download the newest CHIRPS dekad for rainfall monitoring.
              </li>
            </ol>
            <div className="grid-2" style={{ gap: 14 }}>
              <label className="field">
                Your name
                <input
                  value={actor}
                  placeholder="e.g. Joel Nyongesa"
                  onChange={(e) => setActor(e.target.value)}
                />
                <span className="hint">Recorded with the tasks you start.</span>
              </label>
              <label className="field">
                ECMWF run (optional)
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
                <span className="hint">Empty: the newest published run.</span>
              </label>
            </div>
            <div style={{ marginTop: 22 }}>
              <Button
                variant="amber"
                disabled={running || name.length < 2}
                onClick={() => launch("cycle")}
                title={name.length < 2 ? "Enter your name first" : undefined}
              >
                {running ? (
                  <Loader2 size={18} className="spin" />
                ) : (
                  <Play size={18} />
                )}
                {running ? "Running…" : "Run the weekly cycle"}
              </Button>
            </div>
          </Card>
          <Card
            eyebrow="Progress"
            title={operation ? operation.title : "No task running"}
          >
            {error && <ErrorState message={error} />}
            {!operation && !error && (
              <p style={{ margin: 0, color: "var(--muted)" }}>
                Start the weekly cycle or a single step; its progress appears
                here.
              </p>
            )}
            {operation && (
              <>
                <p style={{ marginTop: 0 }}>
                  <Status tone={TONE[operation.status]}>
                    {operation.status}
                  </Status>{" "}
                  <span
                    style={{
                      color: "var(--muted)",
                      fontSize: 14,
                      marginLeft: 6,
                    }}
                  >
                    started by {operation.created_by} · {duration(operation)}
                  </span>
                </p>
                <Timeline operation={operation} />
                {operation.error && (
                  <Notice tone="red">{operation.error}</Notice>
                )}
                {resultLink(operation)}
              </>
            )}
          </Card>
        </div>
        <div className="grid-4">
          {STEPS.map(({ action, title, text, icon: Icon }) => (
            <div
              key={action}
              className="card"
              style={{ display: "flex", flexDirection: "column", gap: 10 }}
            >
              <Icon size={28} style={{ color: "var(--green-700)" }} />
              <h3 style={{ fontSize: 19 }}>{title}</h3>
              <p style={{ margin: 0, fontSize: 15 }}>{text}</p>
              <div style={{ marginTop: "auto" }}>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={running || name.length < 2}
                  onClick={() => launch(action)}
                >
                  Start
                </Button>
              </div>
            </div>
          ))}
        </div>
        <Card
          title="Task history"
          action={
            <Button variant="outline" size="sm" onClick={history.reload}>
              <RefreshCw size={15} /> Refresh
            </Button>
          }
        >
          {history.loading && !history.data && <Skeleton height={180} />}
          {history.error && (
            <ErrorState message={history.error} retry={history.reload} />
          )}
          {history.data && !history.data.length && (
            <p style={{ margin: 0 }}>No task has been run yet.</p>
          )}
          {history.data && history.data.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>By</th>
                    <th className="num">Duration</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((row) => (
                    <Fragment key={row.id}>
                      <tr>
                        <td className="strong">{row.title}</td>
                        <td>
                          <Status tone={TONE[row.status]}>
                            {row.status === "failed" ? (
                              <XCircle size={12} />
                            ) : null}
                            {row.status}
                          </Status>
                        </td>
                        <td>{dateTime(row.started_at ?? row.created_at)}</td>
                        <td>{row.created_by}</td>
                        <td className="num">{duration(row)}</td>
                        <td>
                          <button
                            type="button"
                            className="link-amber"
                            style={{
                              background: "none",
                              border: 0,
                              cursor: "pointer",
                            }}
                            onClick={() =>
                              setExpanded(expanded === row.id ? null : row.id)
                            }
                          >
                            {expanded === row.id ? "Hide" : "Details"}
                          </button>
                        </td>
                      </tr>
                      {expanded === row.id && (
                        <tr>
                          <td
                            colSpan={6}
                            style={{ background: "var(--ground)" }}
                          >
                            <Timeline operation={row} />
                            {row.error && (
                              <Notice tone="red">{row.error}</Notice>
                            )}
                            {resultLink(row)}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="Schedule">
          <KeyValues
            items={[
              [
                "Weekly",
                "Run the cycle once ECMWF has published the 00 UTC run of the issue day (about 09:00 UTC).",
              ],
              [
                "Daily",
                "Check for a new CHIRPS dekad and verify the forecasts it now covers, as ICPAC's climate monitoring does each morning.",
              ],
              [
                "Unattended",
                "Both can run on a schedule without anyone opening this page; your system administrator sets that up (see the service's operations guide).",
              ],
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
