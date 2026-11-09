"use client";
/** Verification of issued forecasts against CHIRPS. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import {
  Button,
  Card,
  Disclosure,
  ErrorState,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { useActor } from "@/lib/actor";
import {
  SERIES,
  day,
  num,
  personName,
  sentence,
  signed,
  validDays,
} from "@/lib/format";
import type { ChatComparison } from "@/types/workflows";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type {
  ExperimentalEvidence,
  ForecastDetail,
  ForecastRun,
  Metrics,
  ReferenceComparison,
  Seasonal,
  Variant,
  VerifiedWeek,
} from "@/types/operational";
import {
  MetricsTable,
  ModelScope,
  VerificationState,
  chirpsFrom,
  observedBy,
  ofRecord,
  primaryOf,
} from "@/features/operational/shared";
import PastWeeks, { PAST_WEEKS } from "@/features/operational/past-weeks";
import {
  ProbabilisticVerification,
  SkillSummary,
} from "@/features/operational/skill";

const SEASONS: Record<string, string> = {
  DJF: "December – February",
  MAM: "March – May",
  JJA: "June – August",
  SON: "September – November",
};

const LAYERS: Variant[] = ["hybrid", "mbc", "raw"];

/** The mean of the weeks' scores (a simple mean: every week counts once). */
function mean(values: (number | null | undefined)[]): number | null {
  const held = values.filter(
    (v): v is number => v != null && Number.isFinite(v),
  );
  return held.length ? held.reduce((a, b) => a + b, 0) / held.length : null;
}

/** Every verified week's scores: CHIRPS, or one of the further observations, against the
 * chosen forecast layer, with raw ECMWF's RMSE beside it. */
function WeeklyScores({ refresh }: { refresh: number }) {
  const weeks = useApi<VerifiedWeek[]>("/verification/weeks");
  const reload = weeks.reload;
  useEffect(() => {
    if (refresh) reload();
  }, [refresh, reload]);
  const [layer, setLayer] = useState<Variant>("hybrid");
  const [observed, setObserved] = useState("best");
  if (weeks.status === 404) return null; // an older service
  const rows = (weeks.data ?? []).map((week) => {
    const best =
      week.best ??
      (Object.keys(week.chirps).length
        ? { source: "chirps", name: "CHIRPS", domain: week.chirps }
        : undefined);
    const reference =
      observed === "best"
        ? best?.domain
        : observed === "chirps"
          ? week.chirps
          : week.references.find((r) => r.source === observed)?.domain;
    return {
      week,
      by: observed === "best" ? best?.name : undefined,
      scores: reference?.[layer],
      raw: reference?.raw,
    };
  });
  const scored = rows.filter((r) => r.scores);
  const names: Record<string, string> = {
    best: "Best available (CHIRPS, ARC 2.0, RFE 2.0, GPM IMERG)",
    chirps: "CHIRPS",
  };
  for (const week of weeks.data ?? [])
    for (const r of week.references) names[r.source] = r.name;
  return (
    <Card
      title="Scores of every verified week"
      subtitle="Over all cells. Lower RMSE and MAE are better; r near 1 is better."
    >
      <div className="evidence-controls">
        <label className="field">
          Forecast layer
          <select
            value={layer}
            onChange={(e) => setLayer(e.target.value as Variant)}
          >
            {LAYERS.map((v) => (
              <option key={v} value={v}>
                {SERIES[v].label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Observed rainfall
          <select
            value={observed}
            onChange={(e) => setObserved(e.target.value)}
          >
            {Object.entries(names).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
                {id === "chirps" ? " (reference)" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {weeks.loading && !weeks.data && <Skeleton height={200} />}
      {weeks.error && <ErrorState message={weeks.error} retry={weeks.reload} />}
      {weeks.data && !scored.length && (
        <p style={{ margin: 0, color: "var(--muted)" }}>
          No verified week has {SERIES[layer].label} scored against{" "}
          {names[observed] ?? observed} yet.
        </p>
      )}
      {scored.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Week (days 8–14)</th>
                <th>ECMWF run</th>
                {observed === "best" && <th>Observed by</th>}
                <th className="num">RMSE</th>
                <th className="num">MAE</th>
                <th className="num">Pearson r</th>
                <th className="num">Bias</th>
                <th className="num">Raw ECMWF RMSE</th>
              </tr>
            </thead>
            <tbody>
              {scored.map(({ week, by, scores, raw }) => (
                <tr key={week.forecast_id}>
                  <td className="strong">
                    <Link href={`/forecasts?id=${week.forecast_id}`}>
                      {validDays(week.valid_start, week.valid_end)}
                    </Link>
                  </td>
                  <td>{day(week.initialization)}</td>
                  {observed === "best" && <td>{by}</td>}
                  <td className="num">{num(scores?.rmse, 2)} mm</td>
                  <td className="num">{num(scores?.mae, 2)} mm</td>
                  <td className="num">{num(scores?.correlation, 3)}</td>
                  <td className="num">{signed(scores?.bias, 2)} mm</td>
                  <td className="num" style={{ color: "var(--muted)" }}>
                    {num(raw?.rmse, 2)} mm
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td className="strong" colSpan={observed === "best" ? 3 : 2}>
                  Mean of {scored.length} week{scored.length === 1 ? "" : "s"}
                </td>
                <td className="num strong">
                  {num(mean(scored.map((r) => r.scores?.rmse)), 2)} mm
                </td>
                <td className="num strong">
                  {num(mean(scored.map((r) => r.scores?.mae)), 2)} mm
                </td>
                <td className="num strong">
                  {num(mean(scored.map((r) => r.scores?.correlation)), 3)}
                </td>
                <td className="num strong">
                  {signed(mean(scored.map((r) => r.scores?.bias)), 2)} mm
                </td>
                <td className="num" style={{ color: "var(--muted)" }}>
                  {num(mean(scored.map((r) => r.raw?.rmse)), 2)} mm
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Card>
  );
}

function readyOn(run: ForecastRun) {
  const end = new Date(run.valid_end).getTime();
  return day(new Date(end + 2 * 86_400_000).toISOString());
}

function LatestVerified({ run }: { run: ForecastRun }) {
  const detail = useApi<ForecastDetail>(`/forecasts/${run.forecast_id}`);
  if (!detail.data) return <Skeleton height={200} />;
  const v = detail.data.verification;
  const sources = observedBy(run);
  return (
    <Disclosure
      title={`Latest week by observation · ${validDays(run.valid_start, run.valid_end)}`}
      subtitle={`ECMWF run of ${day(run.initialization)} · ${sources.join(", ")}`}
    >
      <p style={{ margin: 0 }}>
        <Link href={`/forecasts?id=${run.forecast_id}`}>Open forecast</Link>
      </p>
      {v.domain && <MetricsTable metrics={v.domain} />}
      <OtherObservations run={run} chirps={v.domain ?? undefined} />
    </Disclosure>
  );
}

/** The same week scored against ARC 2.0, RFE 2.0 and GPM IMERG, next to CHIRPS. */
function OtherObservations({
  run,
  chirps,
}: {
  run: ForecastRun;
  chirps?: Partial<Record<Variant, Metrics>>;
}) {
  const compared = useApi<ReferenceComparison[]>(
    `/forecasts/${run.forecast_id}/references`,
  );
  const variant: Variant =
    !chirps || chirps[primaryOf(run)]
      ? primaryOf(run)
      : ((Object.keys(chirps)[0] as Variant | undefined) ?? "raw");
  const rows: {
    name: string;
    metrics?: Metrics;
    reason?: string;
  }[] = [
    {
      name: "CHIRPS (reference)",
      metrics: chirps?.[variant],
      reason: "Not read for this week yet",
    },
    ...(compared.data ?? []).map((c) => ({
      name: c.name,
      metrics: c.status === "available" ? c.domain?.[variant] : undefined,
      reason:
        c.status === "waiting"
          ? "Not published for the whole week yet"
          : sentence(c.reason ?? "Not available"),
    })),
  ];
  return (
    <div style={{ marginTop: 22 }}>
      <h4 style={{ margin: "0 0 10px" }}>
        {SERIES[variant].label} against each observation
      </h4>
      {compared.loading && <Skeleton height={120} />}
      {compared.data && compared.data.length === 0 && (
        <p style={{ margin: 0, fontSize: 14 }}>Compared in the next pass.</p>
      )}
      {compared.data && compared.data.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Observation</th>
                <th className="num">Observed mean</th>
                <th className="num">MAE</th>
                <th className="num">RMSE</th>
                <th className="num">Bias</th>
                <th className="num">Pearson r</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td className="strong">{row.name}</td>
                  {row.metrics ? (
                    <>
                      <td className="num">
                        {num(row.metrics.observed_mean, 1)} mm
                      </td>
                      <td className="num">{num(row.metrics.mae, 2)} mm</td>
                      <td className="num">{num(row.metrics.rmse, 2)} mm</td>
                      <td className="num">{signed(row.metrics.bias, 2)} mm</td>
                      <td className="num">{num(row.metrics.correlation, 3)}</td>
                    </>
                  ) : (
                    <td colSpan={5} style={{ color: "var(--muted)" }}>
                      {row.reason}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Other models' forecasts uploaded in the Copilot, scored with ICPAC's once observed. */
function OtherModels() {
  const uploads = useApi<ChatComparison[]>("/external-forecasts");
  if (!uploads.data?.length) return null;
  return (
    <Disclosure
      title="Other models' forecasts"
      subtitle="Uploaded in the Copilot; scored once observed"
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Model</th>
              <th>Week</th>
              <th>Uploaded by</th>
              <th className="num">Its MAE</th>
              <th className="num">ICPAC MAE</th>
              <th>Closer to CHIRPS</th>
            </tr>
          </thead>
          <tbody>
            {uploads.data.map((upload) => {
              const theirs = upload.scores.find((s) => s.label === upload.name);
              const ours = upload.scores.find(
                (s) => s.label === `ICPAC ${upload.versus?.main_layer}`,
              );
              return (
                <tr key={upload.id}>
                  <td className="strong">{upload.name}</td>
                  <td>{upload.period}</td>
                  <td>{personName(upload.uploaded_by)}</td>
                  <td className="num">
                    {theirs ? `${num(theirs.mae_mm, 2)} mm` : "—"}
                  </td>
                  <td className="num">
                    {ours ? `${num(ours.mae_mm, 2)} mm` : "—"}
                  </td>
                  <td>
                    {upload.status !== "available" ? (
                      <Status tone="progress">Awaiting CHIRPS</Status>
                    ) : theirs && ours ? (
                      theirs.mae_mm < ours.mae_mm ? (
                        upload.name
                      ) : (
                        `ICPAC ${upload.versus?.main_layer}`
                      )
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Disclosure>
  );
}

/** The answer first: how much the correction improves on raw ECMWF on the independent
 * test, and how many live weeks are scored. */
/** The scores in plain words, for readers who are not verification specialists. */
function HowToRead() {
  return (
    <Disclosure title="How to read the scores">
      <dl className="score-terms">
        <div>
          <dt>RMSE and MAE</dt>
          <dd>
            Typical error, mm. RMSE weighs big misses more. Lower is better.
          </dd>
        </div>
        <div>
          <dt>Bias</dt>
          <dd>
            Forecast minus observed: above zero too wet, below zero too dry.
          </dd>
        </div>
        <div>
          <dt>Pearson r</dt>
          <dd>How well wet and dry areas match: 1 perfect, 0 none.</dd>
        </div>
        <div>
          <dt>Raw ECMWF</dt>
          <dd>
            Uncorrected ECMWF. Lower error than raw = the correction helped.
          </dd>
        </div>
      </dl>
      <p className="card-note">
        A few weeks are indicative; a season is firmer.
      </p>
    </Disclosure>
  );
}

function Answer({
  evidence,
  verified,
}: {
  evidence?: ExperimentalEvidence;
  verified: number;
}) {
  const scores = evidence?.regional ?? [];
  const hybrid = scores.find((s) => s.model === "CatBoost");
  const mbc = scores.find((s) => s.model === "MBC");
  if (!evidence || hybrid?.skill_vs_raw == null || mbc?.skill_vs_raw == null)
    return null;
  const percent = (value: number) => `${Math.round(value * 100)}%`;
  const refit = evidence.scope.kind === "retrospective";
  return (
    <section className="card answer-card" aria-label="Verification in brief">
      <p className="answer">
        {refit ? "Final refit" : "MBC + CatBoost"}, 2022–2024 (
        {evidence.scope.cases} cases):{" "}
        <strong>{percent(hybrid.skill_vs_raw)} lower RMSE</strong> than raw
        ECMWF; MBC alone {percent(mbc.skill_vs_raw)}.
      </p>
      <p className="answer-sub">
        {refit ? "Retrospective comparison. " : ""}
        {verified} live week{verified === 1 ? "" : "s"} scored.
      </p>
    </section>
  );
}

/** The frozen 551-case evaluation, kept apart from the live verification above. */
function ExperimentalSummary({
  evidence,
}: {
  evidence: Loaded<ExperimentalEvidence>;
}) {
  return (
    <Disclosure
      title={
        evidence.data?.scope.kind === "retrospective"
          ? "Model evidence: the final refit on 2022–2024"
          : "Model evidence: the independent 2022–2024 test"
      }
      subtitle="551 reforecast cases; not the live scores"
    >
      <p style={{ margin: 0 }}>
        <Link href="/verification/experimental">Full verification</Link>
      </p>
      {evidence.error && (
        <ErrorState message={evidence.error} retry={evidence.reload} />
      )}
      {!evidence.data && !evidence.error && <Skeleton height={200} />}
      {evidence.data && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">RMSE (mm/week)</th>
                <th className="num">MAE</th>
                <th className="num">Bias</th>
                <th className="num">r</th>
                <th className="num">RMSE skill vs raw</th>
              </tr>
            </thead>
            <tbody>
              {evidence.data.regional.map((s) => (
                <tr key={s.model}>
                  <td className="strong">{s.label}</td>
                  <td className="num">{num(s.rmse, 3)}</td>
                  <td className="num">{num(s.mae, 3)}</td>
                  <td className="num">{signed(s.bias, 3)}</td>
                  <td className="num">{num(s.pearson_r, 3)}</td>
                  <td className="num">
                    {s.model === "RawECMWF"
                      ? "—"
                      : `${num((s.skill_vs_raw ?? 0) * 100, 2)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {evidence.data && (
        <p className="card-note">{String(evidence.data.scope.selection)}</p>
      )}
    </Disclosure>
  );
}

function SeasonalTable({ seasonal }: { seasonal: Seasonal }) {
  const rows = Object.entries(seasonal.seasons);
  if (!rows.length)
    return (
      <p style={{ margin: 0 }}>
        Seasonal scores appear once forecasts have been verified.
      </p>
    );
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Season</th>
            <th>Layer</th>
            <th className="num">Weeks</th>
            <th className="num">MAE</th>
            <th className="num">RMSE</th>
            <th className="num">Bias</th>
            <th className="num">r</th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap(([season, variants]) =>
            (Object.entries(variants) as [Variant, Metrics][]).map(
              ([variant, m]) => (
                <tr key={season + variant}>
                  <td className="strong">
                    {season}{" "}
                    <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                      · {SEASONS[season]}
                    </span>
                  </td>
                  <td>{SERIES[variant].label}</td>
                  <td className="num">{m.cases ?? "—"}</td>
                  <td className="num">{num(m.mae, 2)}</td>
                  <td className="num">{num(m.rmse, 2)}</td>
                  <td className="num">{signed(m.bias, 2)}</td>
                  <td className="num">{num(m.correlation, 3)}</td>
                </tr>
              ),
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function Verification() {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const [refresh, setRefresh] = useState(0);
  const [includeTest, setIncludeTest] = useState(false);
  /** Another model's verified weeks; empty: the model in use. */
  const [model, setModel] = useState<string | null>(null);
  const seasonal = useApi<Seasonal>(
    `/verification/seasonal?include_protected=${includeTest}${model ? `&model_id=${encodeURIComponent(model)}` : ""}`,
  );
  const [actor] = useActor();
  const { operation, running, error, start } = useOperation(() => {
    runs.reload();
    seasonal.reload();
    setRefresh((value) => value + 1);
  }, "verification");
  // Each Sunday run's forecast of record: a week is listed once. Other days' runs
  // count only while no Sunday run exists.
  const recorded = ofRecord(runs.data ?? []);
  const sundays = recorded.filter((r) => r.weekly);
  const issued = sundays.length ? sundays : recorded;
  // Verified by CHIRPS, ARC 2.0 or RFE 2.0: CHIRPS first, the others when it cannot be read.
  const verified = issued.filter((r) => observedBy(r).length > 0);
  const unverified = issued.filter((r) => observedBy(r).length === 0);
  // A week CHIRPS should cover already is overdue (it shows why); the others wait for it.
  const overdue = unverified.filter(
    (r) => chirpsFrom(r).getTime() <= Date.now(),
  );
  const waiting = unverified.filter(
    (r) => chirpsFrom(r).getTime() > Date.now(),
  );
  const evidence = useApi<ExperimentalEvidence>("/verification/experimental");
  const nextScores = waiting.map((r) => chirpsFrom(r).toISOString()).sort()[0];
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecast Verification"
          crumbs={[{ label: "Verification" }]}
          subtitle="Each week's forecast against CHIRPS, or ARC 2.0, RFE 2.0 and GPM IMERG when CHIRPS is missing."
          actions={
            <Button
              variant="amber"
              disabled={running}
              onClick={() => start("verify_due", actor || "Forecaster")}
            >
              <CheckCircle2 size={18} />{" "}
              {running ? "Verifying…" : "Verify finished forecasts"}
            </Button>
          }
        />
        {operation && (
          <Notice
            tone={operation.status === "failed" ? "red" : "green"}
            title={operation.title}
          >
            {operation.messages.at(-1)?.text} ·{" "}
            <Link href="/data/runs">Operations log</Link>
          </Notice>
        )}
        {error && <ErrorState message={error} />}
        <Answer evidence={evidence.data} verified={verified.length} />
        <div className="stats">
          <div className="stat">
            <div className="label">Verified forecasts</div>
            <div className="value">{runs.data ? verified.length : "…"}</div>
            <div className="hint">Sunday forecasts</div>
          </div>
          <div className="stat amber">
            <div className="label">Awaiting observations</div>
            <div className="value">{runs.data ? unverified.length : "…"}</div>
            <div className="hint">
              {overdue.length
                ? `${overdue.length} overdue`
                : "About two days after each week"}
            </div>
          </div>
          <div className="stat">
            <div className="label">Next scores</div>
            <div className="value" style={{ fontSize: 22 }}>
              {nextScores ? day(nextScores) : "—"}
            </div>
            <div className="hint">
              {nextScores ? "Next week's observations" : "Nothing waiting"}
            </div>
          </div>
        </div>
        {runs.loading && <Skeleton height={240} />}
        {!verified[0] && runs.data && (
          <Notice title="No forecast verified yet.">
            Weeks are verified about two days after they end.
          </Notice>
        )}
        <WeeklyScores refresh={refresh} />
        {verified[0] && (
          <LatestVerified
            key={`${verified[0].forecast_id}-${refresh}`}
            run={verified[0]}
          />
        )}
        <SkillSummary key={`summary-${refresh}`} />
        <ProbabilisticVerification key={`probability-${refresh}`} />
        {runs.data && verified.length < PAST_WEEKS && (
          <PastWeeks
            onDone={() => {
              runs.reload();
              seasonal.reload();
              setRefresh((value) => value + 1);
            }}
          />
        )}
        <Disclosure
          title="Seasonal scores"
          subtitle="Pooled over verified weeks, using each week's observation of record"
        >
          <label
            style={{
              display: "inline-flex",
              gap: 8,
              alignItems: "center",
              fontSize: 14,
            }}
          >
            <input
              type="checkbox"
              checked={includeTest}
              onChange={(e) => setIncludeTest(e.target.checked)}
            />
            Include 2022–2024 test period
          </label>
          {seasonal.error && (
            <ErrorState message={seasonal.error} retry={seasonal.reload} />
          )}
          {seasonal.data ? (
            <div style={{ display: "grid", gap: 16 }}>
              {seasonal.data.observations && (
                <p className="card-note">
                  Observed rainfall:{" "}
                  {Array.from(
                    new Set(Object.values(seasonal.data.observations)),
                  ).join(", ") || "none yet"}
                  . Different observation products can change the scores.
                </p>
              )}
              <ModelScope
                shown={seasonal.data.model_id}
                models={seasonal.data.models}
                onChoose={setModel}
              />
              <SeasonalTable seasonal={seasonal.data} />
            </div>
          ) : (
            <Skeleton height={140} />
          )}
        </Disclosure>
        {unverified.length > 0 && (
          <Disclosure
            title={`Awaiting observations (${unverified.length})`}
            subtitle="Tried every 3 hours"
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Valid period</th>
                    <th>ECMWF run</th>
                    <th>Observations expected from</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[...overdue, ...waiting].map((run) => (
                    <tr key={run.forecast_id}>
                      <td className="strong">
                        <Link href={`/forecasts?id=${run.forecast_id}`}>
                          {validDays(run.valid_start, run.valid_end)}
                        </Link>
                      </td>
                      <td>{day(run.initialization)}</td>
                      <td>{readyOn(run)}</td>
                      <td>
                        <VerificationState run={run} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Disclosure>
        )}
        <HowToRead />
        <OtherModels />
        <ExperimentalSummary evidence={evidence} />
      </div>
    </div>
  );
}
