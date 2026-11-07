"use client";
/** A verified week: the forecast map beside what CHIRPS and the further references
 * observed, with the forecast's RMSE and MAE against each. A week not observed yet says
 * when it will be, and links to the newest week that is. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, MapFigure, Notice, Tabs } from "@/components/ui";
import { SERIES, day, num, signed, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  ForecastDetail,
  ForecastRun,
  Metrics,
  ProbabilisticSummary,
  ReferenceComparison,
  Variant,
} from "@/types/operational";
import {
  coversToday,
  isWeekly,
  layersOf,
  mapUrl,
  ofRecord,
  primaryOf,
} from "@/features/operational/shared";
import { Reliability, Roc, Stat } from "@/features/operational/skill";

/** The page anchor the archive links to. */
export const OBSERVED_ANCHOR = "observed";

/** CHIRPS covers a week about two days after it ends. */
const CHIRPS_DAYS = 2;

type Source = "chirps" | ReferenceComparison["source"];
type Observation = {
  source: Source;
  name: string;
  scores: Partial<Record<Variant, Metrics>>;
};

function Scores({ metrics }: { metrics?: Metrics }) {
  if (!metrics) return <span>No scores for this layer</span>;
  return (
    <span>
      RMSE <strong>{num(metrics.rmse)} mm</strong> · MAE{" "}
      <strong>{num(metrics.mae)} mm</strong>
    </span>
  );
}

/** This week's chance of rainfall above a threshold, from the members, against the
 * observation shown: its reliability diagram and ROC curve. */
function WeekChances({
  forecastId,
  layer,
  source,
}: {
  forecastId: string;
  layer: Variant;
  source: Source;
}) {
  const [threshold, setThreshold] = useState(25);
  const result = useApi<ProbabilisticSummary>(
    `/forecasts/${forecastId}/probabilistic?layer=${layer}&threshold=${threshold}&source=${source}`,
  );
  if (result.status === 404) return null; // an older service
  const data = result.data;
  return (
    <div style={{ marginTop: 22 }}>
      <div className="evidence-controls">
        <h3 style={{ margin: 0, alignSelf: "center" }}>Chance of a wet week</h3>
        <label className="field">
          Rainfall above
          <select
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          >
            {(data?.thresholds_mm ?? [10, 25, 50]).map((t) => (
              <option key={t} value={t}>
                {num(t, 0)} mm
              </option>
            ))}
          </select>
        </label>
      </div>
      {data && data.weeks === 0 && (
        <p className="muted-line" style={{ maxWidth: "none" }}>
          No member probabilities for this week.
        </p>
      )}
      {data && data.weeks > 0 && (
        <>
          <div className="stats" style={{ marginBottom: 18 }}>
            <Stat
              label="ROC area"
              value={num(data.auc, 2)}
              hint="1 perfect, 0.5 no skill"
            />
            <Stat
              label="Brier skill score"
              value={num(data.brier_skill, 2)}
              hint="Above 0: better than climatology"
            />
            <Stat
              label="Observed above"
              value={
                data.base_rate == null
                  ? "—"
                  : `${num(data.base_rate * 100, 0)}%`
              }
              hint={`Share of cells above ${num(threshold, 0)} mm`}
            />
          </div>
          <div className="grid-2">
            <div>
              <h4 style={{ margin: "0 0 4px" }}>Reliability diagram</h4>
              <Reliability data={data} />
            </div>
            <div>
              <h4 style={{ margin: "0 0 4px" }}>ROC curve</h4>
              <Roc data={data} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** The newest verified forecast, a weekly one first. */
function newestVerified(runs: ForecastRun[]): ForecastRun | undefined {
  const verified = ofRecord(runs).filter(
    (r) => !r.synthetic && r.verification_status === "available",
  );
  return verified.find(isWeekly) ?? verified[0];
}

function NotObservedYet({ detail }: { detail: ForecastDetail }) {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const newest = newestVerified(runs.data ?? []);
  const ended = new Date(detail.valid_end).getTime() <= Date.now();
  const from = day(
    new Date(
      new Date(detail.valid_end).getTime() + CHIRPS_DAYS * 86_400_000,
    ).toISOString(),
  );
  return (
    <Card
      id={OBSERVED_ANCHOR}
      eyebrow="Forecast and observed"
      title="What fell that week"
      subtitle={`${validDays(detail.valid_start, detail.valid_end)} ${
        ended
          ? "has ended"
          : coversToday(detail)
            ? "is under way"
            : "has not started yet"
      }. The forecast map beside what CHIRPS and the other observations showed, with the forecast's RMSE and MAE against each, appears here once CHIRPS covers the week, about two days after it ends (from about ${from}).`}
    >
      {newest && newest.forecast_id !== detail.forecast_id && (
        <Link
          className="link-amber"
          href={`/forecasts?id=${newest.forecast_id}#${OBSERVED_ANCHOR}`}
        >
          See the newest verified week,{" "}
          {validDays(newest.valid_start, newest.valid_end)} →
        </Link>
      )}
    </Card>
  );
}

export default function ObservedComparison({
  detail,
}: {
  detail: ForecastDetail;
}) {
  const verified =
    detail.verification.status === "available" && !!detail.verification.domain;
  // A week that has ended may have been checked against the other observations while
  // CHIRPS could not be read yet.
  const ended = Date.parse(detail.valid_end) <= Date.now();
  const compared = useApi<ReferenceComparison[]>(
    verified || ended ? `/forecasts/${detail.forecast_id}/references` : null,
  );
  const layers = layersOf(detail);
  const [layer, setLayer] = useState<Variant>(primaryOf(detail));
  const [source, setSource] = useState<Source>("chirps");
  // The card renders after the forecast loads, so the browser's own jump to the anchor
  // has already happened: jump once it is there.
  useEffect(() => {
    if (window.location.hash === `#${OBSERVED_ANCHOR}`)
      document.getElementById(OBSERVED_ANCHOR)?.scrollIntoView();
  }, [detail.forecast_id]);
  const observations: Observation[] = [
    ...(verified
      ? [
          {
            source: "chirps" as const,
            name: "CHIRPS",
            scores: detail.verification.domain ?? {},
          },
        ]
      : []),
    ...(compared.data ?? [])
      .filter((c) => c.status === "available" && c.domain)
      .map((c) => ({ source: c.source, name: c.name, scores: c.domain ?? {} })),
  ];
  if (!observations.length) return <NotObservedYet detail={detail} />;
  const shown =
    observations.find((o) => o.source === source) ?? observations[0];
  const week = validDays(detail.valid_start, detail.valid_end);
  return (
    <Card
      id={OBSERVED_ANCHOR}
      eyebrow="Forecast and observed"
      title="What fell that week"
      subtitle={`${week} · same colour scale${verified ? "" : " · CHIRPS not read yet"}`}
      action={
        <Tabs
          label="Forecast layer"
          value={layer}
          onChange={setLayer}
          options={layers.map((l) => ({ value: l, label: SERIES[l].label }))}
        />
      }
    >
      {observations.length > 1 && (
        <div style={{ marginBottom: 14 }}>
          <Tabs
            label="Observed rainfall"
            value={shown.source}
            onChange={setSource}
            options={observations.map((o) => ({
              value: o.source,
              label: o.name,
            }))}
          />
        </div>
      )}
      <div className="grid-2">
        <MapFigure
          src={mapUrl(detail, layer)}
          alt={`${SERIES[layer].label} forecast for ${week}`}
          caption={`Forecast · ${SERIES[layer].label}`}
        />
        <MapFigure
          src={`/api/forecasts/${detail.forecast_id}/observed/map?source=${shown.source}`}
          alt={`Rainfall observed by ${shown.name} for ${week}`}
          caption={
            <>
              Observed · {shown.name} · <Scores metrics={shown.scores[layer]} />
            </>
          }
        />
      </div>
      <div className="table-wrap" style={{ marginTop: 18 }}>
        <table className="data">
          <thead>
            <tr>
              <th>Observed by</th>
              <th className="num">Forecast mean</th>
              <th className="num">Observed mean</th>
              <th className="num">RMSE</th>
              <th className="num">MAE</th>
              <th className="num">Bias</th>
              <th className="num">r</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((o) => {
              const m = o.scores[layer];
              return (
                <tr key={o.source}>
                  <td className="strong">{o.name}</td>
                  <td className="num">{num(m?.forecast_mean)}</td>
                  <td className="num">{num(m?.observed_mean)}</td>
                  <td className="num">{num(m?.rmse)}</td>
                  <td className="num">{num(m?.mae)}</td>
                  <td className="num">{signed(m?.bias)}</td>
                  <td className="num">{num(m?.correlation, 3)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted-line" style={{ maxWidth: "none" }}>
        mm over the 11 member states; bias above 0: forecast too wet.
      </p>
      <WeekChances
        forecastId={detail.forecast_id}
        layer={layer}
        source={shown.source}
      />
      {compared.data && compared.data.some((c) => c.status !== "available") && (
        <Notice title="Not every observation is in yet.">
          {compared.data
            .filter((c) => c.status !== "available")
            .map((c) => `${c.name}: ${c.reason ?? "not compared yet"}`)
            .join(" · ")}
        </Notice>
      )}
    </Card>
  );
}
