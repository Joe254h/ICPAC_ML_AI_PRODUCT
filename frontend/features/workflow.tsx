"use client";
import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import type { Config, Selection } from "@/types";
import type { Job } from "@/types/workflows";
import { mutate, request } from "@/services/api";
import Copilot from "@/features/copilot";
import Bulletins from "@/features/bulletins";
import Models from "@/features/models";
export default function Workflow({
  view,
  selection,
  config,
  refresh,
}: {
  view: string;
  selection: Selection;
  config: Config | null;
  refresh: () => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]),
    [components, setComponents] = useState<[string, string][]>([]),
    [error, setError] = useState(""),
    [pending, setPending] = useState(false),
    [executor, setExecutor] = useState("mock_slurm");
  useEffect(() => {
    let mounted = true;
    setError("");
    const load = () => {
      if (view === "jobs")
        request<Job[]>("/jobs")
          .then((data) => {
            if (mounted) setJobs(data);
          })
          .catch((e) => {
            if (mounted) setError(e.message);
          });
      if (view === "health")
        request<{ components: Record<string, string> }>("/health")
          .then((data) => {
            if (mounted) setComponents(Object.entries(data.components));
          })
          .catch((e) => {
            if (mounted) setError(e.message);
          });
    };
    load();
    const timer = view === "jobs" ? setInterval(load, 2000) : null;
    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
    };
  }, [view]);
  if (view === "models")
    return <Models config={config} selection={selection} refresh={refresh} />;
  if (view === "copilot") return <Copilot />;
  if (view === "bulletins") return <Bulletins selection={selection} />;
  if (view === "jobs")
    return (
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Pipeline jobs</h2>
            <p>
              Fixed stages with afterok dependencies · persistent logs and
              status
            </p>
          </div>
          <div className="action-row">
            <label className="compact-select">
              Executor
              <select
                aria-label="Job executor"
                value={executor}
                onChange={(e) => setExecutor(e.target.value)}
              >
                <option value="mock_slurm">Simulated SLURM</option>
                <option value="local">Local CPU pipeline</option>
                <option value="slurm">Configured SLURM cluster</option>
              </select>
            </label>
            <button
              className="button primary"
              disabled={pending}
              onClick={async () => {
                setPending(true);
                setError("");
                try {
                  await mutate("/jobs?executor=" + executor, selection);
                  setJobs(await request("/jobs"));
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setPending(false);
                }
              }}
            >
              <Play size={14} />
              Run pipeline
            </button>
          </div>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>JOB ID</th>
                <th>CYCLE</th>
                <th>STAGE</th>
                <th>EXECUTOR</th>
                <th>STATUS</th>
                <th>LOGS / CONTROL</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>{j.id.slice(0, 8)}</td>
                  <td>{j.cycle}</td>
                  <td>{j.stage}</td>
                  <td>{j.executor}</td>
                  <td>
                    <span
                      className={
                        "badge " + (j.status === "success" ? "green" : "amber")
                      }
                    >
                      {j.status}
                    </span>
                    {j.poll_error && (
                      <p className="subtle-alert">{j.poll_error}</p>
                    )}
                  </td>
                  <td>
                    <details>
                      <summary>View logs and timing</summary>
                      <pre>
                        {j.log}\nStart: {j.start_time ?? "—"}\nEnd:{" "}
                        {j.end_time ?? "—"}\nExit: {j.exit_code ?? "—"}
                      </pre>
                    </details>
                    {["queued", "running"].includes(j.status) && (
                      <button
                        className="button secondary"
                        onClick={async () => {
                          try {
                            await mutate("/jobs/" + j.id + "/cancel", {});
                            setJobs(await request("/jobs"));
                          } catch (e) {
                            setError((e as Error).message);
                          }
                        }}
                      >
                        Cancel pipeline
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!jobs.length && (
          <div className="empty-workflow">
            <h3>No pipeline runs yet</h3>
            <p>
              Simulated SLURM demonstrates scheduling. Local execution performs
              climate calculations and produces files.
            </p>
          </div>
        )}
      </section>
    );
  if (view === "health")
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>System components</h2>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="checks">
          {components.map(([name, status]) => (
            <div key={name}>
              <span>{name}</span>
              <strong>{status}</strong>
            </div>
          ))}
        </div>
        <p className="prose">
          Healthy components support this prototype. Operational data
          connections, identity verification and a cluster require deployment
          configuration.
        </p>
      </section>
    );
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Scientific configuration</h2>
      </div>
      <pre>{JSON.stringify(config?.science, null, 2)}</pre>
      <p className="prose">
        Versioned configuration is managed in Git. Data and model artifacts are
        mounted externally. Lead windows, feature contracts and grid alignment
        are validated by the backend.
      </p>
    </section>
  );
}
