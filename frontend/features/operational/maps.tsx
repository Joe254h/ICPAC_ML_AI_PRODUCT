"use client";
/** Rainfall maps of the latest forecast and verification maps over verified forecasts. */
import Link from "next/link";
import { useState } from "react";
import {
  Card,
  ErrorState,
  InProgress,
  MapFigure,
  Notice,
  PageBanner,
  Skeleton,
  Tabs,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { COUNTRIES } from "@/features/routes";
import { SERIES, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ForecastDetail, MapsStatus, Variant } from "@/types/operational";
import {
  LAYER_TEXT,
  NoForecast,
  forecastFacts,
  layersOf,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";

const METRICS: Record<string, { title: string; text: string }> = {
  bias: {
    title: "Bias",
    text: "Mean forecast minus observed Week-2 rainfall per cell: positive where the forecast is too wet, negative where it is too dry.",
  },
  rmse: {
    title: "RMSE",
    text: "Root-mean-square error per cell: the typical size of the Week-2 rainfall error, weighting large errors more.",
  },
  correlation: {
    title: "Correlation",
    text: "Pearson correlation between forecast and observed Week-2 rainfall across verified weeks, per cell.",
  },
  skill: {
    title: "Skill",
    text: "RMSE improvement over raw ECMWF per cell: where the correction helps (positive) or hurts (negative).",
  },
};

function RainfallMaps({ detail }: { detail: ForecastDetail }) {
  const layers = layersOf(detail);
  const [country, setCountry] = useState("");
  return (
    <>
      <PageBanner
        title="Rainfall Maps"
        crumbs={[{ label: "Maps" }, { label: "Rainfall" }]}
        subtitle="Week-2 total rainfall in the ICPAC weekly bulletin's colour classes, for the region or one member state."
        facts={forecastFacts(detail)}
      />
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 14,
          alignItems: "end",
        }}
      >
        <label className="field" style={{ minWidth: 260 }}>
          Area
          <select value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">Eastern Africa (all eleven countries)</option>
            {COUNTRIES.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid-3">
        {(["raw", "mbc", "hybrid"] as Variant[]).map((variant) =>
          layers.includes(variant) ? (
            <Card
              key={variant}
              eyebrow={SERIES[variant].label}
              title={LAYER_TEXT[variant].title}
            >
              <MapFigure
                src={mapUrl(detail, variant, country || undefined)}
                alt={`${LAYER_TEXT[variant].title} Week-2 rainfall${country ? ` over ${country}` : ""}`}
                caption={`Valid ${validDays(detail.valid_start, detail.valid_end)}`}
              />
            </Card>
          ) : (
            <InProgress key={variant} title={LAYER_TEXT[variant].title}>
              {detail.products?.hybrid?.reason
                ? `Waiting for ${detail.products.hybrid.reason}.`
                : "Its inputs are not available yet."}
            </InProgress>
          ),
        )}
      </div>
    </>
  );
}

function VerificationMap({ metric }: { metric: string }) {
  const [includeTest, setIncludeTest] = useState(false);
  const status = useApi<MapsStatus>(
    `/verification/maps?include_protected=${includeTest}`,
  );
  const [variant, setVariant] = useState<Variant | null>(null);
  const info = METRICS[metric];
  const data = status.data;
  const entry = data?.metrics[metric];
  const shown =
    variant &&
    data?.variants.includes(variant) &&
    !(metric === "skill" && variant === "raw")
      ? variant
      : (data?.default_variant ?? "mbc");
  return (
    <>
      <PageBanner
        title={`${info.title} Maps`}
        crumbs={[
          { label: "Maps", href: "/maps/rainfall" },
          { label: info.title },
        ]}
        subtitle={info.text}
      />
      {status.loading && <Skeleton height={420} />}
      {status.error && (
        <ErrorState message={status.error} retry={status.reload} />
      )}
      {data && entry && (
        <>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 14,
              alignItems: "center",
            }}
          >
            <Tabs
              label="Forecast layer"
              value={shown}
              onChange={setVariant}
              options={(["raw", "mbc", "hybrid"] as Variant[]).map((v) => ({
                value: v,
                label: SERIES[v].label,
                disabled:
                  !data.variants.includes(v) ||
                  (metric === "skill" && v === "raw"),
              }))}
            />
            <label
              style={{
                display: "inline-flex",
                gap: 8,
                alignItems: "center",
                fontSize: 15,
              }}
            >
              <input
                type="checkbox"
                checked={includeTest}
                onChange={(e) => setIncludeTest(e.target.checked)}
              />
              Include the 2022–2024 independent test period (display only)
            </label>
          </div>
          {entry.available ? (
            <Card
              title={`${info.title} · ${SERIES[shown].label}`}
              subtitle={`${data.cases} verified forecasts of the model in use`}
            >
              <MapFigure
                src={`/api/verification/maps/${metric}?variant=${shown}&include_protected=${includeTest}`}
                alt={`${info.title} of ${SERIES[shown].label} over verified forecasts`}
              />
            </Card>
          ) : (
            <>
              <InProgress title={`${info.title} map`}>
                A per-cell {info.title.toLowerCase()} needs at least{" "}
                {entry.min_cases} verified forecasts; {data.cases}{" "}
                {data.cases === 1 ? "is" : "are"} verified so far. Each weekly
                forecast is verified once CHIRPS covers its week.
              </InProgress>
              <Notice tone="green">
                Verification runs automatically in the weekly cycle (
                <Link href="/data/runs">Operations</Link>); see{" "}
                <Link href="/verification">Verification</Link> for single-week
                scores.
              </Notice>
            </>
          )}
        </>
      )}
    </>
  );
}

export default function Maps({ route, id }: PageProps) {
  const metric = route.param ?? "rainfall";
  const forecast = useForecast(metric === "rainfall" ? id : undefined);
  return (
    <div className="page">
      <div className="wrap">
        {metric !== "rainfall" ? (
          <VerificationMap metric={metric} />
        ) : (
          <>
            {forecast.loading && <Skeleton height={520} />}
            {forecast.status === 404 && (
              <>
                <PageBanner
                  title="Rainfall Maps"
                  crumbs={[{ label: "Maps" }]}
                />
                <NoForecast />
              </>
            )}
            {forecast.error && forecast.status !== 404 && (
              <ErrorState message={forecast.error} retry={forecast.reload} />
            )}
            {forecast.data && <RainfallMaps detail={forecast.data} />}
          </>
        )}
      </div>
    </div>
  );
}
