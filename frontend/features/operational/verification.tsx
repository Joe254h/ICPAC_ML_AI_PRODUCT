"use client";
/** Verification of issued forecasts against CHIRPS. */
import Link from "next/link";
import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  LinkButton,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { useActor } from "@/lib/actor";
import { SERIES, day, num, signed, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type {
  ExperimentalEvidence,
  ForecastDetail,
  ForecastRun,
  Metrics,
  Seasonal,
  Variant,
} from "@/types/operational";
import { MetricsTable } from "@/features/operational/shared";
import PastWeeks, { PAST_WEEKS } from "@/features/operational/past-weeks";

const SEASONS: Record<string, string> = {
  DJF: "December – February",
  MAM: "March – May",
  JJA: "June – August",
  SON: "September – November",
};

function readyOn(run: ForecastRun) {
  const end = new Date(run.valid_end).getTime();
  return day(new Date(end + 2 * 86_400_000).toISOString());
}

function LatestVerified({ run }: { run: ForecastRun }) {
  const detail = useApi<ForecastDetail>(`/forecasts/${run.forecast_id}`);
  if (!detail.data) return <Skeleton height={200} />;
  const v = detail.data.verification;
  return (
    <Card
      eyebrow="Latest verified week"
      title={validDays(run.valid_start, run.valid_end)}
      subtitle={`Forecast from the ECMWF run of ${day(run.initialization)}, scored against CHIRPS${v.season ? ` · ${SEASONS[v.season] ?? v.season}` : ""}`}
      action={
        <LinkButton
          href={`/forecasts?id=${run.forecast_id}`}
          variant="outline"
          size="sm"
        >
          Open forecast
        </LinkButton>
      }
    >
      {v.domain && <MetricsTable metrics={v.domain} />}
      {v.use && (
        <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
          Spatial scores over one week ({v.use}); they do not by themselves
          establish skill.
        </p>
      )}
    </Card>
  );
}

/** The frozen 551-case evaluation, kept apart from the live verification above. */
function ExperimentalSummary() {
  const evidence = useApi<ExperimentalEvidence>("/verification/experimental");
  return (
    <Card
      title="Experimental evidence: the independent 2022–2024 test"
      subtitle="The frozen pre-refit models on 551 reforecast cases. These are not the scores of the forecasts above, and they do not transfer to a refitted model."
      action={
        <LinkButton
          href="/verification/experimental"
          variant="outline"
          size="sm"
        >
          Full verification
        </LinkButton>
      }
    >
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
      <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
        The full CatBoost correction had the lowest RMSE; the MAM-protected
        policy, preselected on 2020–2021 validation, did not beat it on the
        independent period.
      </p>
    </Card>
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
  const [includeTest, setIncludeTest] = useState(false);
  const seasonal = useApi<Seasonal>(
    `/verification/seasonal?include_protected=${includeTest}`,
  );
  const [actor] = useActor();
  const { operation, running, error, start } = useOperation(() => {
    runs.reload();
    seasonal.reload();
  });
  const verified =
    runs.data?.filter((r) => r.verification_status === "available") ?? [];
  const waiting =
    runs.data?.filter((r) => r.verification_status !== "available") ?? [];
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecast Verification"
          crumbs={[{ label: "Verification" }]}
          subtitle="Each Week-2 forecast is scored against CHIRPS once its week has passed: the seven daily CHIRPS totals are summed on the same 0.05° grid and compared cell by cell."
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
        <div className="stats">
          <div className="stat">
            <div className="label">Verified forecasts</div>
            <div className="value">{runs.data ? verified.length : "…"}</div>
            <div className="hint">Against CHIRPS v2.0</div>
          </div>
          <div className="stat amber">
            <div className="label">Awaiting CHIRPS</div>
            <div className="value">{runs.data ? waiting.length : "…"}</div>
            <div className="hint">CHIRPS lags about two days</div>
          </div>
          <div className="stat">
            <div className="label">Metrics</div>
            <div className="value" style={{ fontSize: 22 }}>
              MAE · RMSE · bias · r
            </div>
            <div className="hint">Per week, pooled by season</div>
          </div>
        </div>
        {runs.loading && <Skeleton height={240} />}
        {verified[0] ? (
          <LatestVerified run={verified[0]} />
        ) : (
          runs.data && (
            <Notice title="No forecast verified yet.">
              A forecast is verified about two days after its Week-2 window
              ends, when CHIRPS covers all seven days. Past weeks can be
              forecast and verified now.
            </Notice>
          )
        )}
        {runs.data && verified.length < PAST_WEEKS && (
          <PastWeeks
            onDone={() => {
              runs.reload();
              seasonal.reload();
            }}
          />
        )}
        <Card
          title="Seasonal scores"
          subtitle="Cell-based scores pooled over every verified week of each season."
          action={
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
          }
        >
          {seasonal.data ? (
            <SeasonalTable seasonal={seasonal.data} />
          ) : (
            <Skeleton height={140} />
          )}
        </Card>
        {waiting.length > 0 && (
          <Card title="Awaiting observations">
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Valid period</th>
                    <th>ECMWF run</th>
                    <th>CHIRPS expected from</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {waiting.map((run) => (
                    <tr key={run.forecast_id}>
                      <td className="strong">
                        <Link href={`/forecasts?id=${run.forecast_id}`}>
                          {validDays(run.valid_start, run.valid_end)}
                        </Link>
                      </td>
                      <td>{day(run.initialization)}</td>
                      <td>{readyOn(run)}</td>
                      <td>
                        <Status tone="progress">Awaiting CHIRPS</Status>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
        <ExperimentalSummary />
      </div>
    </div>
  );
}
