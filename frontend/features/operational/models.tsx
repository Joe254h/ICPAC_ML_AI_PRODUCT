"use client";
/** The operational model registry: versions, evidence and reviewed transitions. */
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import ReviewDialog from "@/components/review-dialog";
import {
  Button,
  Card,
  ErrorState,
  KeyValues,
  ModelStatus,
  Notice,
  PageBanner,
  Skeleton,
  Stat,
  Status,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import { useActor } from "@/lib/actor";
import { dateTime, num } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { OperationalModel } from "@/types/operational";

/** "1.0.0-candidate.1" as "1.0.0 (candidate 1)". */
function versionLabel(version: string): string {
  const match = /^(\d+\.\d+\.\d+)-([a-z]+)\.(\d+)$/.exec(version);
  return match ? `${match[1]} (${match[2]} ${match[3]})` : version;
}

const NAMES: Record<string, string> = {
  atmos37: "Atmos37",
  catboost: "CatBoost",
  xgboost: "XGBoost",
  lightgbm: "LightGBM",
};

function TestStatus({ status }: { status?: string }) {
  if (status === "passed")
    return <Status tone="ok">Independent test passed</Status>;
  if (status === "failed")
    return <Status tone="bad">Independent test failed</Status>;
  return <Status tone="progress">Independent test pending</Status>;
}

function IndependentTest({
  model,
  onClose,
  onSaved,
}: {
  model: OperationalModel;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [saved] = useActor();
  const [status, setStatus] = useState<"passed" | "failed">("passed");
  const [report, setReport] = useState("");
  const [metrics, setMetrics] = useState("");
  const [actor, setActor] = useState(saved);
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
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
        <h2>Record the independent {model.test_period} test</h2>
        <p style={{ margin: 0 }}>
          The result comes from the HPC test report and is recorded once; it can
          never be changed. Production needs a passed test.
        </p>
        <label className="field">
          Outcome
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as "passed" | "failed")}
          >
            <option value="passed">Passed</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <label className="field">
          Test report
          <input
            required
            minLength={3}
            value={report}
            onChange={(e) => setReport(e.target.value)}
            placeholder="HPC report name or path"
          />
        </label>
        <label className="field">
          Metrics (optional)
          <input
            value={metrics}
            onChange={(e) => setMetrics(e.target.value)}
            placeholder="rmse=14.99, mae=7.42"
          />
        </label>
        <label className="field">
          Reviewer name
          <input
            required
            minLength={2}
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
        </label>
        <label className="field">
          Justification
          <textarea
            required
            rows={2}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <label style={{ display: "flex", gap: 10, fontSize: 15 }}>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          I reviewed the HPC test report and confirm this result.
        </label>
        {error && <Notice tone="red">{error}</Notice>}
        <div className="row">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <button
            type="submit"
            className="btn btn-green"
            disabled={busy || !confirmed}
          >
            {busy ? "Saving…" : "Record result"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ModelCard({
  model,
  inUse,
  changed,
}: {
  model: OperationalModel;
  inUse: boolean;
  changed: () => void;
}) {
  const [action, setAction] = useState<string | null>(null);
  const [test, setTest] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState<string | null>(null);
  const metrics = model.metrics ?? {};
  return (
    <Card
      eyebrow={inUse ? "In use for forecasts" : undefined}
      title={model.model_name ?? model.model_id}
      subtitle={`Version ${versionLabel(model.version)}`}
      action={
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            justifyContent: "flex-end",
          }}
        >
          <ModelStatus status={model.status} />
          <TestStatus status={model.test_status} />
        </div>
      }
    >
      <div className="stats" style={{ marginBottom: 22 }}>
        <Stat
          label="Validation RMSE"
          value={num(metrics.rainfall_RMSE ?? metrics.rmse, 2)}
          unit="mm"
          hint={`Period ${model.validation_period}`}
        />
        <Stat
          label="Validation MAE"
          value={num(metrics.rainfall_MAE ?? metrics.mae, 2)}
          unit="mm"
        />
        <Stat
          label="Validation r"
          value={num(metrics.rainfall_pearson_r ?? metrics.correlation, 3)}
        />
        <Stat
          label="Trees"
          value={model.trees ?? "—"}
          hint={`${model.feature_count ?? "?"} features`}
        />
      </div>
      <KeyValues
        items={[
          [
            "Method",
            `${NAMES[model.family ?? ""] ?? model.family ?? ""} ${NAMES[model.algorithm ?? ""] ?? model.algorithm ?? ""} residual correction on the ${model.baseline ?? "MBC"} baseline`,
          ],
          ["Training", model.training_period],
          ["Validation", model.validation_period],
          [
            "Independent test",
            `${model.test_period ?? "—"} · ${model.test_status ?? "untested"}`,
          ],
          [
            "Registered",
            `${dateTime(model.created_at)}${
              model.registered_by === "startup"
                ? ", automatically at start-up"
                : model.registered_by
                  ? ` by ${model.registered_by}`
                  : ""
            }`,
          ],
          [
            "Inference check",
            model.inference_test
              ? `${model.inference_test.status} · ${dateTime(model.inference_test.timestamp)}`
              : "—",
          ],
        ]}
      />
      {checked && (
        <div style={{ marginTop: 16 }}>
          <Notice tone="green">{checked}</Notice>
        </div>
      )}
      <div
        style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 22 }}
      >
        <Button
          variant="outline"
          size="sm"
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            try {
              await mutate(`/models/${model.model_id}/validate`, {});
              setChecked(
                "The model files were checked again and a test prediction succeeded.",
              );
              changed();
            } catch (e) {
              setChecked(null);
              alert((e as Error).message);
            } finally {
              setChecking(false);
            }
          }}
        >
          <ShieldCheck size={15} />{" "}
          {checking ? "Checking…" : "Re-check the model files"}
        </Button>
        {model.test_status === "untested" && (
          <Button variant="outline" size="sm" onClick={() => setTest(true)}>
            Record independent test
          </Button>
        )}
        {model.status === "candidate" && (
          <Button
            variant="green"
            size="sm"
            onClick={() => setAction("promote")}
          >
            Promote to production
          </Button>
        )}
        {model.status !== "production" && model.status !== "retired" && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAction("retire")}
          >
            Retire
          </Button>
        )}
        {model.status === "retired" && model.deployment_date && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAction("rollback")}
          >
            Roll back to this version
          </Button>
        )}
      </div>
      {test && (
        <IndependentTest
          model={model}
          onClose={() => setTest(false)}
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
          description={`Confirm this for ${model.model_name ?? "the model"}. The service checks the model's files and the production requirements again before any change.`}
          statement="I have checked the model's files, scores and test evidence, and confirm this decision."
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

export default function Models() {
  const models = useApi<OperationalModel[]>("/models");
  const { current, config, refresh } = useApp();
  const hybrid = config.data?.operational.hybrid;
  const changed = () => {
    models.reload();
    refresh();
  };
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Model Registry"
          crumbs={[{ label: "Models" }]}
          subtitle="Every operational model version with its evidence and reviewed status. Forecasts use the production model, or the newest candidate until one is promoted."
        />
        {hybrid?.status === "in_progress" && (
          <Notice title="AI/ML layer in progress.">
            The registered model&apos;s files are verified, but its AI/ML layer
            cannot be produced yet. {hybrid.reason}
          </Notice>
        )}
        {current.data && current.data.role !== "production" && (
          <Notice title="Candidate in use.">
            {current.data.note ??
              `Forecasts use ${current.data.model.model_name ?? "the newest candidate"} until a model is promoted.`}{" "}
            Promotion needs a passed independent test.
          </Notice>
        )}
        {models.loading && <Skeleton height={420} />}
        {models.error && (
          <ErrorState message={models.error} retry={models.reload} />
        )}
        {models.data && !models.data.length && (
          <Notice title="No model registered.">
            Models are registered by the service at start-up once their files
            have been checked.
          </Notice>
        )}
        {models.data?.map((model) => (
          <ModelCard
            key={model.model_id}
            model={model}
            inUse={current.data?.model.model_id === model.model_id}
            changed={changed}
          />
        ))}
      </div>
    </div>
  );
}
