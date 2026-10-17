"use client";
import Link from "next/link";
import { useCallback, useEffect } from "react";
import {
  Button,
  Card,
  ErrorState,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import { dateTime } from "@/lib/format";
import type { Operation } from "@/types/operational";

type Workspace = {
  capabilities: {
    id: number;
    name: string;
    href: string;
    status: string;
    detail: string;
  }[];
  schedule: { enabled: boolean; hour_utc: number; next_due: string | null };
  last_cycle: Operation | null;
  alerts: {
    code: string;
    message: string;
    operation_id?: string;
    retry_at?: string;
  }[];
  release_mode: string;
};

export default function Automations() {
  const workspace = useApi<Workspace>("/automations");
  const integrations = useApi<{
    feeds: {
      id: string;
      configured: boolean;
      enabled: boolean;
      fetched: number;
      note: string;
    }[];
    hpc: {
      enabled: boolean;
      script_approved: boolean;
      connection_verified: boolean;
      note: string;
      jobs: { id: string; job_id?: string; status: string }[];
    };
  }>("/automations/integrations");
  const latest = useApi<{ forecast_id: string }>("/forecasts/latest");
  const products = useApi<{
    available: string[];
    pending: Record<string, string>;
    summary?: Record<string, { units: string; mean: number }>;
  }>(latest.data ? `/forecasts/${latest.data.forecast_id}/supplemental` : null);
  const reload = useCallback(() => {
    workspace.reload();
    integrations.reload();
    latest.reload();
    products.reload();
  }, [workspace.reload, integrations.reload, latest.reload, products.reload]);
  const task = useOperation(reload);
  useEffect(() => {
    const timer = window.setInterval(reload, 30000);
    return () => window.clearInterval(timer);
  }, [reload]);
  if (workspace.loading && !workspace.data)
    return (
      <div className="wrap page">
        <Skeleton height={420} />
      </div>
    );
  if (workspace.status === 404)
    return (
      <div className="page">
        <div className="wrap">
          <PageBanner
            title="Automation workspace"
            subtitle="The frontend is ready; the matching backend update is pending."
          />
          <Notice>
            The backend needs the automation release before this workspace can
            run. <Link href="/forecasts">Open the current forecasts →</Link>
          </Notice>
        </div>
      </div>
    );
  if (workspace.error)
    return (
      <div className="wrap page">
        <ErrorState message={workspace.error} retry={workspace.reload} />
      </div>
    );
  if (!workspace.data) return null;
  const data = workspace.data;
  const cycle = task.operation ?? data.last_cycle;
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Automation workspace"
          subtitle="Follow the 20 capabilities from source data to products ready for review."
        />
        <Notice tone="amber">
          {data.release_mode === "evaluation" ? "Evaluation release. " : ""}
          Unavailable scientific inputs stay pending. Preparing a bulletin does
          not approve or publish it.
        </Notice>
        <Card
          title="Run the connected workflow"
          subtitle="Select the newest fully published ensemble, issue the available forecast layers, verify due cases, update monitoring, check maps and country summaries, and prepare a frozen bulletin draft."
        >
          <Button
            disabled={task.running}
            onClick={() => task.start("end_to_end", "website automation")}
          >
            {task.running
              ? "Workflow running…"
              : "Prepare forecast and bulletin"}
          </Button>
          {task.error && <p role="alert">{task.error}</p>}
          {cycle && (
            <div aria-live="polite">
              <h3>{cycle.title}</h3>
              <p>
                {cycle.status} · {cycle.attempts ?? 1} attempt(s)
              </p>
              {cycle.retry_at && (
                <p>Next data-availability retry: {dateTime(cycle.retry_at)}</p>
              )}
              <ol>
                {cycle.messages.slice(-8).map((message, i) => (
                  <li key={`${message.time}-${i}`}>{message.text}</li>
                ))}
              </ol>
              {cycle.error && <p role="alert">{cycle.error}</p>}
              {typeof cycle.result?.bulletin_id === "string" && (
                <Link href={`/bulletins?id=${cycle.result.bulletin_id}`}>
                  Open prepared bulletin →
                </Link>
              )}
            </div>
          )}
        </Card>
        <Card
          title="External source integrations"
          subtitle="Reviewed provider requests and server credentials are configured by the operator. Acquired datasets do not silently replace model inputs."
        >
          {integrations.error && (
            <Notice tone="red">{integrations.error}</Notice>
          )}
          {integrations.data?.feeds.map((feed) => (
            <p key={feed.id}>
              <strong>{feed.id.toUpperCase()}</strong> ·{" "}
              {feed.enabled
                ? "Enabled"
                : feed.configured
                  ? "Profile approved; acquisition disabled"
                  : "Awaiting an approved request profile"}{" "}
              · {feed.fetched} datasets held
            </p>
          ))}
          {integrations.data && (
            <>
              <h3>HPC / SLURM</h3>
              <p>
                {integrations.data.hpc.enabled
                  ? integrations.data.hpc.script_approved
                    ? "Job script approved"
                    : "Awaiting approved job script"
                  : "Execution disabled"}{" "}
                ·{" "}
                {integrations.data.hpc.connection_verified
                  ? "Connection checked"
                  : "Live connection not yet verified"}
              </p>
              <p>{integrations.data.hpc.note}</p>
              <ul>
                {integrations.data.hpc.jobs.map((job) => (
                  <li key={job.id}>
                    Job {job.job_id ?? "awaiting reconciliation"}: {job.status}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card
          title="Additional forecast products"
          subtitle="These products require reviewed data for the exact forecast window; climatology, extremes and heat-stress definitions are never guessed."
        >
          {products.error && <Notice tone="red">{products.error}</Notice>}
          {products.data?.available.map((name) => (
            <figure key={name}>
              <figcaption>
                {name.replaceAll("_", " ")}
                {products.data?.summary?.[name] &&
                  ` · domain mean ${products.data.summary[name].mean.toFixed(2)} ${products.data.summary[name].units}`}
              </figcaption>
              <img
                loading="lazy"
                src={`/api/forecasts/${latest.data?.forecast_id}/supplemental/${name}/map`}
                alt={name.replaceAll("_", " ")}
                style={{ width: "100%", maxWidth: 800 }}
              />
            </figure>
          ))}
          <ul>
            {Object.entries(products.data?.pending ?? {}).map(
              ([name, reason]) => (
                <li key={name}>
                  <strong>{name.replaceAll("_", " ")}</strong>: {reason}
                </li>
              ),
            )}
          </ul>
          {!latest.data && (
            <p>A forecast is required before preparing additional products.</p>
          )}
        </Card>
        <Card
          title="Daily schedule"
          subtitle="Scheduling is enabled in the server deployment settings, rather than by public visitors."
        >
          <p>
            {data.schedule.enabled
              ? `Enabled at ${String(data.schedule.hour_utc).padStart(2, "0")}:00 UTC`
              : "Disabled — enable the reviewed schedule in the backend deployment."}
          </p>
          {data.schedule.next_due && (
            <p>Next daily slot: {dateTime(data.schedule.next_due)}</p>
          )}
          <p>
            One durable task per day. Restarts reuse its task record; missed
            days are not replayed.
          </p>
        </Card>
        {!!data.alerts.length && (
          <Card title="Needs attention">
            <ul>
              {data.alerts.map((alert, i) => (
                <li key={`${alert.code}-${i}`}>
                  {alert.message}
                  {alert.operation_id && (
                    <>
                      {" "}
                      <Link href="/data/runs">Open task logs →</Link>
                    </>
                  )}
                  {alert.retry_at && <> Retry at {dateTime(alert.retry_at)}.</>}
                </li>
              ))}
            </ul>
          </Card>
        )}
        <Card
          title="All 20 capabilities"
          subtitle="Available means demonstrated by held products. Ready means implemented but awaiting a successful run; partial and blocked entries name the remaining dependency."
        >
          <div style={{ overflowX: "auto" }}>
            <table style={{ minWidth: 760, width: "100%" }}>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Capability</th>
                  <th scope="col">State</th>
                  <th scope="col">Evidence and next step</th>
                </tr>
              </thead>
              <tbody>
                {data.capabilities.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <th scope="row">
                      <Link href={item.href}>{item.name}</Link>
                    </th>
                    <td>
                      <Status
                        tone={
                          item.status === "available" ||
                          item.status === "enabled"
                            ? "ok"
                            : item.status === "blocked"
                              ? "bad"
                              : "planned"
                        }
                      >
                        {item.status.replaceAll("_", " ")}
                      </Status>
                    </td>
                    <td>{item.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
