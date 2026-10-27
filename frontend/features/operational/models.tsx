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
import { dateTime, num, personName, versionLabel } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type {
  EcmwfReadiness,
  Lifecycle,
  OperationalModel,
} from "@/types/operational";

const NAMES: Record<string, string> = {
  atmos37: "Atmos37",
  catboost: "CatBoost",
  xgboost: "XGBoost",
  lightgbm: "LightGBM",
};

const POLICY: Record<string, string> = {
  catboost_full:
    "MBC plus the full CatBoost correction, never below zero (the web default, chosen after the 2022–2024 test)",
  global_alpha075: "A quarter MBC, three quarters the full correction",
  mam_protected:
    "MBC for March–May initializations, otherwise the 75% blend (preselected on 2020–2021 validation)",
  mbc_only: "MBC alone: the fallback without the AI/ML correction",
};

const STAGES: [keyof Lifecycle["states"], string][] = [
  ["uploaded", "Uploaded"],
  ["integrity_verified", "Integrity verified"],
  ["scientifically_validated", "Independently tested"],
  ["operationally_approved", "Approved for operational use"],
  ["active", "Active"],
];

function LifecycleSteps({ lifecycle }: { lifecycle?: Lifecycle | null }) {
  if (!lifecycle) return null;
  if (lifecycle.states.retired)
    return (
      <p style={{ margin: "0 0 18px" }}>
        <Status tone="planned">Retired</Status>
      </p>
    );
  return (
    <ol className="lifecycle" aria-label="Lifecycle">
      {STAGES.map(([key, label]) => (
        <li key={key} className={lifecycle.states[key] ? "done" : undefined}>
          <Status tone={lifecycle.states[key] ? "ok" : "planned"}>
            {label}
          </Status>
        </li>
      ))}
    </ol>
  );
}

function RealtimeReview({
  model,
  forecastId,
  onClose,
  onSaved,
  withdraw,
}: {
  model: OperationalModel;
  forecastId: string | null;
  onClose: () => void;
  onSaved: () => void;
  withdraw?: boolean;
}) {
  return (
    <ReviewDialog
      title={
        withdraw
          ? "Withdraw the real-time input confirmation"
          : "Confirm the real-time ECMWF input"
      }
      description={
        withdraw
          ? "Runs from 2025 will again be issued from MBC until a reviewer confirms the input."
          : "The model was trained and tested on ECMWF reforecasts. Confirm that the real-time ECMWF Open Data input matches them: the run named below passed every automated input check (members, Days 8–14 accumulation, units, grid and mask, the seven upper-air leads, the 30 predictors, PCA and MBC). The 2022–2024 test scores still describe reforecasts, not real-time skill."
      }
      statement={
        withdraw
          ? "I withdraw the confirmation for this input source."
          : "I reviewed the input checks and the source's model cycle, members, accumulation, units and grid, and confirm the input is compatible."
      }
      onClose={onClose}
      onSubmit={async (review) => {
        await mutate(`/models/${model.model_id}/realtime-review`, {
          ...review,
          source: "ecmwf_opendata",
          forecast_id: withdraw ? null : forecastId,
          withdraw: Boolean(withdraw),
        });
        onSaved();
      }}
    />
  );
}

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
  ready,
}: {
  model: OperationalModel;
  inUse: boolean;
  changed: () => void;
  ready?: EcmwfReadiness | null;
}) {
  const [action, setAction] = useState<string | null>(null);
  const [review, setReview] = useState<"confirm" | "withdraw" | null>(null);
  const [test, setTest] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState<string | null>(null);
  const metrics = model.metrics ?? {};
  const report = model.bundle?.independent_report;
  const gated =
    Boolean(model.model_info?.realtime_gate_from) &&
    model.policy !== "mbc_only";
  const confirmation = model.realtime_reviews?.ecmwf_opendata;
  const evidence =
    ready?.model?.model_id === model.model_id &&
    ready.compatibility.status === "awaiting_review"
      ? (ready.last_run?.forecast_id ?? null)
      : null;
  const states = model.lifecycle?.states;
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
      <LifecycleSteps lifecycle={model.lifecycle} />
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
          value={model.policy === "mbc_only" ? "—" : (model.trees ?? "—")}
          hint={
            model.policy === "mbc_only"
              ? "No AI/ML correction"
              : `${model.feature_count ?? "?"} features`
          }
        />
      </div>
      <KeyValues
        items={[
          [
            "Method",
            model.family === "hybrid7_pc17"
              ? "CatBoost residual correction of MBC from 24 inputs: ensemble rainfall, location, season, MBC and 17 atmospheric components"
              : `${NAMES[model.family ?? ""] ?? model.family ?? ""} ${NAMES[model.algorithm ?? ""] ?? model.algorithm ?? ""} residual correction on the ${model.baseline ?? "MBC"} baseline`,
          ],
          ...(model.policy
            ? ([["Policy", POLICY[model.policy] ?? model.policy]] as [
                string,
                string,
              ][])
            : []),
          ["Training", model.training_period],
          ["Validation", model.validation_period],
          [
            "Independent test",
            `${model.test_period ?? "—"} · ${model.test_status ?? "untested"}`,
          ],
          ...(report
            ? ([
                [
                  "HPC independent report",
                  `RMSE ${num(report.rmse, 3)} mm/week, MAE ${num(report.mae, 3)}, r ${num(report.pearson_r, 3)} over ${report.cases} cases (${report.period}, reforecasts). ${report.selection_note}.`,
                ],
              ] as [string, string][])
            : []),
          ...(model.pressure_steps_hours
            ? ([
                [
                  "Upper-air leads",
                  model.pressure_steps_hours.map((h) => `${h} h`).join(", "),
                ],
              ] as [string, string][])
            : []),
          ...(gated
            ? ([
                [
                  "Real-time input",
                  confirmation
                    ? `Confirmed by ${personName(confirmation.actor)}, ${dateTime(confirmation.timestamp)}`
                    : "Not confirmed: runs from 2025 are issued from MBC until a reviewer confirms the ECMWF Open Data input",
                ],
              ] as [string, string][])
            : []),
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
        {model.status === "experimental" && (
          <Button
            variant="green"
            size="sm"
            onClick={() => setAction("candidate")}
          >
            Approve for operational use
          </Button>
        )}
        {states?.operationally_approved && !inUse && (
          <Button
            variant="green"
            size="sm"
            onClick={() => setAction("activate")}
          >
            Make this the model in use
          </Button>
        )}
        {model.status === "candidate" && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAction("promote")}
          >
            Promote to production
          </Button>
        )}
        {gated && !confirmation && evidence && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReview("confirm")}
          >
            Confirm the real-time input
          </Button>
        )}
        {gated && confirmation && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReview("withdraw")}
          >
            Withdraw the real-time confirmation
          </Button>
        )}
        {model.status !== "production" &&
          model.status !== "retired" &&
          !inUse && (
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
      {review && (
        <RealtimeReview
          model={model}
          forecastId={evidence}
          withdraw={review === "withdraw"}
          onClose={() => setReview(null)}
          onSaved={changed}
        />
      )}
      {action && (
        <ReviewDialog
          title={
            {
              candidate: "Approve for operational use",
              activate: "Make this the model in use",
              promote: "Promote to production",
              retire: "Retire this model",
              rollback: "Roll back to this version",
            }[action] ?? action
          }
          description={
            action === "activate"
              ? `New forecasts will use ${model.model_name ?? "this model"}. The service checks its files and runs a test prediction first; the model in use now stays one click away in the activation history.`
              : action === "candidate"
                ? `Approval does not change the model in use: activating it is a separate decision.`
                : `Confirm this for ${model.model_name ?? "the model"}. The service checks the model's files and the production requirements again before any change.`
          }
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

const POLICY_ORDER = [
  "catboost_full",
  "global_alpha075",
  "mam_protected",
  "mbc_only",
];

/** The model in use first, then a bundle's policies in their order, then the newest. */
function sortModels(
  models: OperationalModel[],
  active?: string,
): OperationalModel[] {
  const rank = (m: OperationalModel) =>
    m.model_id === active ? -1 : m.status === "retired" ? 1 : 0;
  const policy = (m: OperationalModel) => {
    const index = POLICY_ORDER.indexOf(m.policy ?? "");
    return index < 0 ? POLICY_ORDER.length : index;
  };
  return [...models].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      policy(a) - policy(b) ||
      String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")),
  );
}

function ActivationHistory({ models }: { models: OperationalModel[] }) {
  const { current } = useApp();
  const activation = current.data?.activation;
  if (!activation) return null;
  const name = (id: string) =>
    models.find((m) => m.model_id === id)?.model_name ?? "a retired model";
  return (
    <Card
      title="Model in use"
      subtitle="Only a reviewer's activation changes it. Earlier models stay available to reactivate."
    >
      <KeyValues
        items={[
          [
            "Now",
            `${name(activation.model_id)} · since ${dateTime(activation.since)} · ${activation.actor === "registry" ? "kept from before explicit activation" : personName(activation.actor)}`,
          ],
          ...activation.history
            .slice(0, 5)
            .map(
              (h, i) =>
                [
                  i === 0 ? "Before" : "",
                  `${name(h.model_id)} · ${dateTime(h.since)} to ${dateTime(h.until)}`,
                ] as [string, string],
            ),
        ]}
      />
    </Card>
  );
}

export default function Models() {
  const models = useApi<OperationalModel[]>("/models");
  const ready = useApi<EcmwfReadiness>("/data/ecmwf/readiness");
  const { current, config, refresh } = useApp();
  const hybrid = config.data?.operational.hybrid;
  const changed = () => {
    models.reload();
    ready.reload();
    refresh();
  };
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Model Registry"
          crumbs={[
            { label: "Operations", href: "/data/runs" },
            { label: "Model registry" },
          ]}
          subtitle="Every operational model version with its evidence and reviewed status. A newly registered model is never used automatically: a reviewer approves it, then activates it."
        />
        {hybrid?.status === "in_progress" && (
          <Notice title="AI/ML layer in progress.">
            The registered model&apos;s files are verified, but its AI/ML layer
            cannot be produced yet. {hybrid.reason}
          </Notice>
        )}
        {current.data && current.data.role !== "production" && (
          <Notice title="Evaluation model in use.">
            {current.data.note ??
              `Forecasts use ${current.data.model.model_name ?? "the newest candidate"} until a model is promoted.`}{" "}
            Promotion to production needs a passed independent test.
          </Notice>
        )}
        {models.data && <ActivationHistory models={models.data} />}
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
        {models.data &&
          sortModels(models.data, current.data?.model.model_id).map((model) => (
            <ModelCard
              key={model.model_id}
              model={model}
              inUse={current.data?.model.model_id === model.model_id}
              changed={changed}
              ready={ready.data}
            />
          ))}
      </div>
    </div>
  );
}
