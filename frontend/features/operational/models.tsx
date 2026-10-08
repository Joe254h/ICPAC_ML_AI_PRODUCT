"use client";
/** Model registry: operational models (candidate vs production) and the demo registry. */
import { useState } from "react";
import { CheckCircle2, Circle, PackagePlus, XCircle } from "lucide-react";
import ReviewDialog from "@/components/review-dialog";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  KeyValues,
  ModelStatus,
  Notice,
  PageHeader,
  Skeleton,
  Table,
  TestStatus,
} from "@/components/ui";
import { DEMO_SELECTION, useApp } from "@/components/shell";
import Models from "@/features/models";
import type { PageProps } from "@/features/view";
import { dateTime, num, shortHash, signed } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { OperationalModel } from "@/types/operational";

const OPERATIONAL = "week2_operational";
const field =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-foreground";

function gate(model: OperationalModel): [string, boolean][] {
  return [
    [
      "Training and validation metrics recorded",
      !!model.metrics && Object.keys(model.metrics).length > 0,
    ],
    ["Artifacts verified at registration", !!model.validated],
    [
      `Independent ${model.test_period} test passed`,
      model.test_status === "passed",
    ],
    ["Inference test passed", model.inference_test?.status === "passed"],
  ];
}

function MetricsList({ model }: { model: OperationalModel }) {
  const m = model.metrics ?? {};
  const rows: [string, string][] = [
    ["Rainfall MAE", num(m.rainfall_MAE, 2) + " mm"],
    ["Rainfall RMSE", num(m.rainfall_RMSE, 2) + " mm"],
    ["Rainfall bias", signed(m.rainfall_bias, 2) + " mm"],
    ["Rainfall Pearson r", num(m.rainfall_pearson_r, 3)],
    ["Residual RMSE", num(m.residual_RMSE, 2) + " mm"],
    ["Residual Pearson r", num(m.residual_pearson_r, 3)],
  ];
  return (
    <div>
      <div className="mb-1 text-muted-foreground">{model.metrics_scope}</div>
      <Table head={["Metric", "Value"]}>
        {rows.map(([label, value]) => (
          <tr key={label} className="tabular">
            <td>{label}</td>
            <td className="font-medium">{value}</td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

function IndependentTestDialog({
  model,
  onClose,
  onSaved,
}: {
  model: OperationalModel;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [status, setStatus] = useState<"passed" | "failed">("passed");
  const [report, setReport] = useState("");
  const [metrics, setMetrics] = useState("");
  const [actor, setActor] = useState("");
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="modal-backdrop">
      <form
        className="review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="test-title"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const parsed = Object.fromEntries(
              metrics
                .split(",")
                .map((pair) => pair.split("=").map((s) => s.trim()))
                .filter(
                  ([key, value]) =>
                    key && value && !Number.isNaN(Number(value)),
                )
                .map(([key, value]) => [key, Number(value)]),
            );
            await mutate(`/models/${model.model_id}/independent-test`, {
              status,
              period: model.test_period,
              report,
              metrics: parsed,
              actor,
              comment,
              confirmed,
            });
            onSaved();
            onClose();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="panel-head">
          <div>
            <h2 id="test-title">
              Record the independent {model.test_period} test
            </h2>
            <p>
              The result comes from the HPC test report and is recorded once;
              any change needs a new model version.
            </p>
          </div>
        </div>
        <div className="form-body">
          <label>
            Result
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as "passed" | "failed")}
            >
              <option value="passed">Passed</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label>
            Report reference
            <input
              required
              minLength={3}
              value={report}
              placeholder="HPC report name or path"
              onChange={(e) => setReport(e.target.value)}
            />
          </label>
          <label>
            Test metrics (optional, e.g. rmse=13.9, mae=6.8)
            <input
              value={metrics}
              onChange={(e) => setMetrics(e.target.value)}
            />
          </label>
          <label>
            Reviewer name
            <input
              required
              minLength={2}
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          <label>
            Justification
            <textarea
              required
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I reviewed the HPC test report and confirm this result.
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="action-row">
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy || !confirmed}>
              {busy ? "Saving…" : "Record result"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function OperationalModelCard({
  model,
  changed,
}: {
  model: OperationalModel;
  changed: () => void;
}) {
  const [action, setAction] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const checks = gate(model);
  const ready = checks.every(([, ok]) => ok);
  const sums = model.artifact_checksums ?? {};
  return (
    <Card>
      <CardHeader
        title={model.model_name}
        description={model.model_id}
        action={
          <div className="flex flex-wrap gap-2">
            <ModelStatus status={model.status} />
            <TestStatus status={model.test_status} />
          </div>
        }
      />
      <CardContent className="grid gap-6 xl:grid-cols-3">
        <KeyValues
          items={[
            ["Version", model.version],
            ["Experiment", model.experiment],
            [
              "Method",
              `${model.baseline} baseline + ${model.algorithm} residual · ${model.trees} trees`,
            ],
            [
              "Feature family",
              `${model.family} · ${model.feature_count} features`,
            ],
            ["Training", model.training_period],
            ["Validation", model.validation_period],
            ["Independent test", model.test_period],
            [
              "Registered",
              `${dateTime(model.created_at)} by ${model.registered_by ?? "?"}`,
            ],
            [
              "Deployed",
              model.deployment_date ? dateTime(model.deployment_date) : "Never",
            ],
          ]}
        />
        <MetricsList model={model} />
        <div className="grid content-start gap-4">
          <div>
            <div className="mb-2 font-medium">Production gate</div>
            <ul className="m-0 grid gap-1.5 p-0">
              {checks.map(([label, ok]) => (
                <li key={label} className="flex items-center gap-2">
                  {ok ? (
                    <CheckCircle2 size={16} className="text-status-good-ink" />
                  ) : model.test_status === "failed" &&
                    label.startsWith("Independent") ? (
                    <XCircle size={16} className="text-status-critical-ink" />
                  ) : (
                    <Circle size={16} className="text-subtle" />
                  )}
                  <span className={ok ? "" : "text-muted-foreground"}>
                    {label}
                  </span>
                </li>
              ))}
              <li className="flex items-center gap-2 text-muted-foreground">
                <Circle size={16} className="text-subtle" />
                Named reviewer approval at promotion
              </li>
            </ul>
          </div>
          <div>
            <div className="mb-1.5 font-medium">Artifact checksums</div>
            <div className="grid gap-0.5 text-[0.86rem] text-muted-foreground">
              {Object.entries(sums).map(([kind, sum]) => (
                <span key={kind}>
                  {kind}: <code>{shortHash(sum, 16)}</code>
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {model.test_status === "untested" && (
              <Button onClick={() => setTesting(true)}>
                Record independent test
              </Button>
            )}
            {model.status === "candidate" && (
              <Button
                variant="primary"
                disabled={!ready}
                title={
                  ready ? undefined : "The production gate is not satisfied"
                }
                onClick={() => setAction("promote")}
              >
                Promote to production
              </Button>
            )}
            {["candidate", "experimental"].includes(model.status) && (
              <Button onClick={() => setAction("retire")}>Retire</Button>
            )}
            {model.status === "retired" && model.deployment_date && (
              <Button onClick={() => setAction("rollback")}>
                Roll back to this version
              </Button>
            )}
          </div>
        </div>
      </CardContent>
      {testing && (
        <IndependentTestDialog
          model={model}
          onClose={() => setTesting(false)}
          onSaved={changed}
        />
      )}
      {action && (
        <ReviewDialog
          title={
            {
              promote: "Promote to production",
              retire: "Retire this model",
              rollback: "Roll back to this version",
            }[action] ?? action
          }
          description={`Confirm ${action} for ${model.model_id}. The backend re-verifies the artifacts and the production gate before any change.`}
          onClose={() => setAction(null)}
          onSubmit={async (review) => {
            await mutate(`/models/${model.model_id}/${action}`, review);
            changed();
          }}
        />
      )}
    </Card>
  );
}

function RegisterDescriptor({ changed }: { changed: () => void }) {
  const [descriptor, setDescriptor] = useState("config/model_registry/");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  return (
    <Card>
      <CardHeader
        title="Register a model version"
        description="From a reviewed descriptor that pins every artifact by SHA256; nothing is recorded unless every check passes. A refitted model is a new version: the candidate is never overwritten."
      />
      <CardContent className="grid gap-3">
        <form
          className="grid gap-4 md:grid-cols-[3fr_1fr_auto] md:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setDone("");
            try {
              const record = await mutate<OperationalModel>(
                "/models/register",
                {
                  descriptor,
                  actor,
                },
              );
              setDone(`Registered ${record.model_id} as ${record.status}.`);
              changed();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="grid gap-1.5 text-muted-foreground">
            Descriptor
            <input
              className={field}
              required
              pattern="[A-Za-z0-9_./-]+\.ya?ml"
              value={descriptor}
              onChange={(e) => setDescriptor(e.target.value)}
            />
          </label>
          <label className="grid gap-1.5 text-muted-foreground">
            Your name
            <input
              className={field}
              required
              minLength={2}
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          <Button variant="primary" type="submit" busy={busy}>
            <PackagePlus size={15} />
            Register
          </Button>
        </form>
        {done && <Notice tone="good">{done}</Notice>}
        {error && <ErrorState message={error} />}
      </CardContent>
    </Card>
  );
}

export default function ModelsPage({ route }: PageProps) {
  const models = useApi<OperationalModel[]>("/models");
  const { config, refresh } = useApp();
  const changed = () => {
    models.reload();
    refresh();
  };
  const operational = (models.data ?? []).filter((m) => m.task === OPERATIONAL);
  const view = route.param ?? "registry";
  const shown =
    view === "candidate"
      ? operational.filter((m) =>
          ["candidate", "experimental"].includes(m.status),
        )
      : view === "production"
        ? operational.filter((m) => m.status === "production")
        : operational;
  const demoConfig = config.data && {
    ...config.data,
    models: config.data.models.filter((m) => m.task !== OPERATIONAL),
  };
  return (
    <>
      <PageHeader
        title={route.title}
        description={
          view === "production"
            ? "The model forecasts use once promoted. Promotion needs metrics, verified artifacts, a passed independent 2022–2024 test, an inference test and a named reviewer."
            : view === "candidate"
              ? "Models under evaluation. A candidate is used for forecasts only while no production model exists, and is always labelled as such."
              : "Operational models on the ICPAC-11 800 × 700 grid, and the demonstration models of the synthetic grid."
        }
        badges={<Badge tone="info">MBC baseline · residual learning</Badge>}
      />
      {models.loading && !models.data ? (
        <Skeleton className="h-80" />
      ) : models.error ? (
        <ErrorState message={models.error} retry={models.reload} />
      ) : shown.length ? (
        shown.map((model) => (
          <OperationalModelCard
            key={model.model_id}
            model={model}
            changed={changed}
          />
        ))
      ) : (
        <Card>
          <EmptyState
            title={
              view === "production"
                ? "No production model yet"
                : "No operational model in this state"
            }
          >
            {view === "production"
              ? "Forecasts use the newest candidate, labelled candidate, until a model passes the production gate."
              : "Register a model version from its descriptor below."}
          </EmptyState>
        </Card>
      )}
      {view === "registry" && (
        <>
          <RegisterDescriptor changed={changed} />
          <div className="legacy">
            {demoConfig ? (
              <Models
                config={demoConfig}
                selection={DEMO_SELECTION}
                refresh={changed}
              />
            ) : null}
          </div>
        </>
      )}
    </>
  );
}
