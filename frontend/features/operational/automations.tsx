"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { openStaffAccess } from "@/components/bulletin-access";
import {
  Button,
  Card,
  ErrorState,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { request } from "@/services/api";
import { useApi } from "@/services/hooks";
import { useStaff } from "@/services/staff";
import { useOperation } from "@/services/operations";
import { operationActive, operationLabel } from "@/services/operation-state";
import { dateTime } from "@/lib/format";
import type { Operation } from "@/types/operational";

type Workspace = {
  schedule: {
    enabled: boolean;
    when: string;
    verification?: string;
    next_due: string | null;
  };
  last_cycle: Operation | null;
  alerts: {
    code: string;
    message: string;
    operation_id?: string;
    retry_at?: string;
  }[];
  release_mode: string;
};

type Coordinator = {
  configured: boolean;
  destinations: string[];
  secret_set: boolean;
  recent: {
    id: string;
    kind: string;
    time: string;
    status: string;
    detail: string;
  }[];
};

/** n8n: whether the service tells it what happens, the newest deliveries, and a test. */
function Coordination({
  coordinator,
  staff,
  scheduled,
  onSent,
}: {
  coordinator?: Coordinator;
  staff: boolean;
  scheduled: boolean;
  onSent: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [answer, setAnswer] = useState("");
  if (!coordinator) return null;
  const send = async () => {
    setSending(true);
    setAnswer("");
    try {
      const result = await request<{
        deliveries: { status: string; detail: string }[];
      }>("/automations/coordinator/test", { method: "POST" });
      const delivery = result.deliveries[0];
      setAnswer(
        delivery?.status === "delivered"
          ? "n8n received the test event; its message should arrive shortly."
          : `n8n did not accept it (${delivery?.detail ?? "no answer"}).`,
      );
      onSent();
    } catch (failure) {
      setAnswer((failure as Error).message);
    } finally {
      setSending(false);
    }
  };
  return (
    <Card
      title="Coordination with n8n"
      subtitle="n8n starts the weekly run and the verification on schedule, and tells the forecasters what happened."
    >
      {coordinator.configured ? (
        <p>
          <Status tone="ok">Connected</Status> Signed events go to{" "}
          {coordinator.destinations.join(", ")}.
          {scheduled &&
            " The service's own weekly schedule is also on: switch one off so the week is not started twice."}
        </p>
      ) : (
        <p>
          <Status tone="planned">Not connected</Status> Set N8N_WEBHOOK_URL and
          N8N_WEBHOOK_SECRET on the service (deploy/n8n/README.md).
        </p>
      )}
      {coordinator.configured && (
        <div className="row">
          {staff ? (
            <Button variant="outline" disabled={sending} onClick={send}>
              {sending ? "Sending…" : "Send a test event"}
            </Button>
          ) : (
            <Button variant="outline" onClick={openStaffAccess}>
              Staff access to test
            </Button>
          )}
          {answer && <span role="status">{answer}</span>}
        </div>
      )}
      {coordinator.recent.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Sent</th>
              <th scope="col">Event</th>
              <th scope="col">Delivery</th>
            </tr>
          </thead>
          <tbody>
            {coordinator.recent.map((item) => (
              <tr key={item.id}>
                <td>{dateTime(item.time)}</td>
                <td>{item.kind}</td>
                <td>
                  <Status tone={item.status === "delivered" ? "ok" : "bad"}>
                    {item.status}
                  </Status>{" "}
                  {item.detail}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Automations() {
  const workspace = useApi<Workspace>("/automations");
  const integrations = useApi<{
    coordinator?: Coordinator;
  }>("/automations/integrations");
  const { staff } = useStaff();
  const reload = useCallback(() => {
    workspace.reload();
    integrations.reload();
  }, [workspace.reload, integrations.reload]);
  const task = useOperation(reload, "automations");
  useEffect(() => {
    const current = workspace.data?.last_cycle;
    if (current && !task.running && current.id !== task.operation?.id)
      task.follow(current);
  }, [
    workspace.data?.last_cycle,
    task.running,
    task.operation?.id,
    task.follow,
  ]);
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
          subtitle="Newest ensemble, forecast layers, verification, monitoring, maps, bulletin draft."
        >
          {staff || task.running ? (
            <Button
              disabled={task.running}
              onClick={() => task.start("end_to_end", "website automation")}
            >
              {task.running
                ? "Workflow running…"
                : "Prepare forecast and bulletin"}
            </Button>
          ) : (
            <Button variant="outline" onClick={openStaffAccess}>
              Staff access to run it
            </Button>
          )}
          {task.running && (
            <Button
              variant="outline"
              disabled={!!task.operation?.stop_requested}
              onClick={() => task.stop("website automation")}
              style={{ marginLeft: 10 }}
            >
              {task.operation?.stop_requested ? "Stopping…" : "Stop the run"}
            </Button>
          )}
          {task.error && <p role="alert">{task.error}</p>}
          {cycle && (
            <div aria-live="polite">
              <h3>{cycle.title}</h3>
              <p>
                {operationLabel(cycle)} · {cycle.attempts ?? 1} attempt(s)
              </p>
              {cycle.retry_at && (
                <p>Next data-availability retry: {dateTime(cycle.retry_at)}</p>
              )}
              <ol>
                {cycle.messages.slice(-8).map((message, i) => (
                  <li key={`${message.time}-${i}`}>{message.text}</li>
                ))}
              </ol>
              {cycle.error && (
                <Notice tone={operationActive(cycle) ? "amber" : "red"}>
                  {cycle.retry_at
                    ? "The source is temporarily unavailable. This task will retry automatically. "
                    : ""}
                  {cycle.error}
                </Notice>
              )}
              {typeof cycle.result?.bulletin_id === "string" && (
                <Link href={`/bulletins?id=${cycle.result.bulletin_id}`}>
                  Open prepared bulletin →
                </Link>
              )}
            </div>
          )}
        </Card>
        <Coordination
          coordinator={integrations.data?.coordinator}
          staff={staff}
          scheduled={data.schedule.enabled}
          onSent={integrations.reload}
        />
        <Card
          title="Weekly schedule"
          subtitle="Scheduling is enabled in the server deployment settings, rather than by public visitors."
        >
          <p>
            {data.schedule.enabled
              ? `Enabled: ${data.schedule.when}, from that Sunday's ECMWF run.`
              : integrations.data?.coordinator?.configured
                ? "Started by n8n (above); the service's own schedule is off."
                : "Off: connect n8n (above), or switch the service's schedule on in the backend deployment."}
          </p>
          {data.schedule.next_due && (
            <p>Next weekly run: {dateTime(data.schedule.next_due)}</p>
          )}
          {data.schedule.enabled && data.schedule.verification && (
            <p>
              Verification: {data.schedule.verification.toLowerCase()}, the
              weeks that have ended are verified against CHIRPS (about two days
              after a week ends).
            </p>
          )}
          <p>
            One durable task per week. Restarts reuse its task record; missed
            weeks are not replayed. A forecaster can still run the cycle at any
            time on the Operations page, for the latest Sunday or a chosen day.
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
      </div>
    </div>
  );
}
