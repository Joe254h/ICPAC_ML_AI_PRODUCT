"use client";
import { useState } from "react";
import { mutate, query, request } from "@/services/api";
import type { Analysis, Config, Selection } from "@/types";
import ReviewDialog from "@/components/review-dialog";
const empty = {
  model_id: "",
  model_name: "",
  version: "1.0.0",
  model_type: "abc",
  artifact_path: "",
  feature_schema: "rainfall_total_v1",
  training_period: "not supplied",
  validation_period: "not supplied",
  notes: "",
};
export default function Models({
  config,
  selection,
  refresh,
}: {
  config: Config | null;
  selection: Selection;
  refresh: () => void;
}) {
  const [action, setAction] = useState<{ id: string; action: string } | null>(
      null,
    ),
    [error, setError] = useState(""),
    [pending, setPending] = useState(false),
    [form, setForm] = useState(empty),
    [comparison, setComparison] = useState<Analysis | null>(null);
  async function validate(id: string) {
    setPending(true);
    setError("");
    try {
      await mutate("/models/" + id + "/validate", selection);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Demonstration models</h2>
            <p>
              Synthetic grid · versioned artifacts · explicit validation ·
              confirmed deployment changes
            </p>
          </div>
          <span className="badge green">
            {config?.models.find((m) => m.status === "production")
              ?.model_name ?? "No production model"}
          </span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="product-grid">
          {config?.models.map((m) => (
            <div className="product-card" key={m.model_id}>
              <span
                className={
                  "badge " + (m.status === "production" ? "green" : "amber")
                }
              >
                {m.status}
              </span>
              <h3>{m.model_name}</h3>
              <p>
                Version {m.version} · {m.model_type}
              </p>
              <dl>
                <dt>Feature schema</dt>
                <dd>{m.feature_schema}</dd>
                <dt>Training / validation</dt>
                <dd>
                  {m.training_period}
                  <br />
                  {m.validation_period}
                </dd>
                <dt>Artifact</dt>
                <dd>{m.artifact_path ?? "Built-in demonstration"}</dd>
                <dt>Checksum</dt>
                <dd>{m.checksum}</dd>
              </dl>
              <div className="action-row">
                <button
                  className="button secondary"
                  disabled={pending}
                  onClick={async () => {
                    try {
                      setComparison(
                        await request<Analysis>(
                          "/analysis?" +
                            query({ ...selection, model: m.model_id }),
                        ),
                      );
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  Compare
                </button>
                {m.status === "experimental" && (
                  <>
                    <button
                      className="button secondary"
                      disabled={pending}
                      onClick={() => validate(m.model_id)}
                    >
                      Validate case
                    </button>
                    {!!m.validated && (
                      <button
                        className="button secondary"
                        onClick={() =>
                          setAction({ id: m.model_id, action: "candidate" })
                        }
                      >
                        Mark candidate
                      </button>
                    )}
                  </>
                )}
                {m.status === "candidate" && (
                  <button
                    className="button primary"
                    onClick={() =>
                      setAction({ id: m.model_id, action: "promote" })
                    }
                  >
                    Promote
                  </button>
                )}
                {m.status === "retired" && !!m.deployment_date && (
                  <button
                    className="button secondary"
                    onClick={() =>
                      setAction({ id: m.model_id, action: "rollback" })
                    }
                  >
                    Rollback
                  </button>
                )}
              </div>
              <details>
                <summary>View full metadata</summary>
                <pre>{JSON.stringify(m, null, 2)}</pre>
              </details>
            </div>
          ))}
        </div>
        <details className="registration">
          <summary>Register a mounted native artifact</summary>
          <p>
            Use a file mounted inside ARTIFACT_ROOT. Native CatBoost, LightGBM
            and XGBoost require their optional Python runtime. ABC uses a
            validated affine correction JSON contract.
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setPending(true);
              setError("");
              try {
                await mutate("/models/register", form);
                setForm(empty);
                refresh();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setPending(false);
              }
            }}
          >
            <div className="registration-grid">
              {Object.entries(form)
                .filter(([key]) => key !== "model_type")
                .map(([key, value]) => (
                  <label key={key}>
                    {key.replaceAll("_", " ")}
                    <input
                      required
                      value={value}
                      onChange={(e) =>
                        setForm((old) => ({ ...old, [key]: e.target.value }))
                      }
                    />
                  </label>
                ))}
              <label>
                Model type
                <select
                  value={form.model_type}
                  onChange={(e) =>
                    setForm((old) => ({ ...old, model_type: e.target.value }))
                  }
                >
                  {["abc", "catboost", "lightgbm", "xgboost"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
            </div>
            <button className="button primary" disabled={pending}>
              Register artifact
            </button>
          </form>
        </details>
      </section>
      {comparison && (
        <section className="panel">
          <div className="panel-head">
            <h2>Candidate comparison · {comparison.selection.country}</h2>
            <span className="badge amber">Single synthetic forecast case</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>MODEL</th>
                <th>RMSE mm</th>
                <th>MAE mm</th>
                <th>BIAS mm</th>
              </tr>
            </thead>
            <tbody>
              {comparison.model_comparison.map((m) => (
                <tr key={m.model}>
                  <td>{m.model}</td>
                  <td>{m.rmse.toFixed(2)}</td>
                  <td>{m.mae.toFixed(2)}</td>
                  <td>{m.bias.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="prose">
            This comparison supports prototype review. A production decision
            also needs independent validation, artifact trust and documented
            scientific assessment.
          </p>
        </section>
      )}
      {action && (
        <ReviewDialog
          title={
            {
              candidate: "Mark validated model candidate",
              promote: "Promote model to production",
              rollback: "Restore previous production model",
            }[action.action] ?? action.action
          }
          description={
            "Confirm " +
            action.action +
            " for " +
            action.id +
            ". Review validation periods, feature schema, artifact checksum and independent evidence. This prototype records your name without authenticating identity."
          }
          onClose={() => setAction(null)}
          onSubmit={async (review) => {
            await mutate("/models/" + action.id + "/" + action.action, review);
            refresh();
          }}
        />
      )}
    </>
  );
}
