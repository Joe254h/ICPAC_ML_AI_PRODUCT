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
  ForecastDetail,
  ForecastRun,
  Metrics,
  Seasonal,
  Variant,
} from "@/types/operational";
import { MetricsTable } from "@/features/operational/shared";

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
      subtitle={`Forecast of ${day(run.initialization)} against ${v.observation?.file ?? "CHIRPS"} · ${v.season ?? ""}`}
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
              The first forecast is verified about two days after its Week-2
              window ends, when CHIRPS covers all seven days.
            </Notice>
          )
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
        <Card title="Reference: the independent evaluation">
          <p style={{ marginTop: 0 }}>
            Before operational use the methods were evaluated on 537 independent
            Week-2 cases (2022–2024) over the full domain:
          </p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Method</th>
                  <th className="num">MAE (mm)</th>
                  <th className="num">RMSE (mm)</th>
                  <th className="num">Bias (mm)</th>
                  <th className="num">r</th>
                  <th className="num">RMSE skill vs raw</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Raw ECMWF", "9.055", "17.207", "+1.682", "0.718", "—"],
                  ["MBC", "7.578", "15.289", "−0.203", "0.775", "11.15%"],
                  [
                    "MBC + AI/ML (study model)",
                    "7.420",
                    "14.993",
                    "−0.361",
                    "0.785",
                    "12.87%",
                  ],
                ].map(([name, ...values]) => (
                  <tr key={name}>
                    <td className="strong">{name}</td>
                    {values.map((value, i) => (
                      <td key={i} className="num">
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
            From the ICPAC Week-2 AI/ML study (locked 2022–2024 test). The
            operational MBC + AI/ML model has not yet been tested on that
            period.
          </p>
        </Card>
      </div>
    </div>
  );
}
