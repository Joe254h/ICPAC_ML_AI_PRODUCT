"use client";
/** A verified week: the forecast map beside what CHIRPS and the further references
 * observed, with the forecast's RMSE and MAE against each. A week not observed yet says
 * when it will be, and links to the newest week that is. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, MapFigure, Notice, Tabs } from "@/components/ui";
import { SERIES, day, num, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  ForecastDetail,
  ForecastRun,
  Metrics,
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
  const compared = useApi<ReferenceComparison[]>(
    verified ? `/forecasts/${detail.forecast_id}/references` : null,
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
  if (!verified) return <NotObservedYet detail={detail} />;
  const observations: Observation[] = [
    {
      source: "chirps",
      name: "CHIRPS",
      scores: detail.verification.domain ?? {},
    },
    ...(compared.data ?? [])
      .filter((c) => c.status === "available" && c.domain)
      .map((c) => ({ source: c.source, name: c.name, scores: c.domain ?? {} })),
  ];
  const shown =
    observations.find((o) => o.source === source) ?? observations[0];
  const week = validDays(detail.valid_start, detail.valid_end);
  return (
    <Card
      id={OBSERVED_ANCHOR}
      eyebrow="Forecast and observed"
      title="What fell that week"
      subtitle={`${week}: the forecast beside the observed rainfall, on the same colour scale. RMSE and MAE are the forecast's errors against each observation, over the member states.`}
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
              <th className="num">RMSE (mm)</th>
              <th className="num">MAE (mm)</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((o) => (
              <tr key={o.source}>
                <td className="strong">{o.name}</td>
                <td className="num">{num(o.scores[layer]?.rmse)}</td>
                <td className="num">{num(o.scores[layer]?.mae)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
