"use client";
/** A verified week: the forecast map beside what CHIRPS and the further references
 * observed, with the forecast's RMSE and MAE against each. */
import { useState } from "react";
import { Card, MapFigure, Notice, Tabs } from "@/components/ui";
import { SERIES, num, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  ForecastDetail,
  Metrics,
  ReferenceComparison,
  Variant,
} from "@/types/operational";
import { layersOf, mapUrl, primaryOf } from "@/features/operational/shared";

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
  if (!verified) return null;
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
  const shown = observations.find((o) => o.source === source) ?? observations[0];
  const week = validDays(detail.valid_start, detail.valid_end);
  return (
    <Card
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
      {compared.data &&
        compared.data.some((c) => c.status !== "available") && (
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
