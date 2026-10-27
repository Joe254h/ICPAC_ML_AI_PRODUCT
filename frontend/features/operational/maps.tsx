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
import PastWeeks from "@/features/operational/past-weeks";
import { COUNTRIES } from "@/features/routes";
import { SERIES, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ForecastDetail, MapsStatus, Variant } from "@/types/operational";
import {
  ModelScope,
  NoForecast,
  forecastFacts,
  kindOf,
  layersOf,
  layerText,
  mapUrl,
  productReason,
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
        crumbs={[
          { label: "Forecasts", href: "/forecasts" },
          { label: "Rainfall maps" },
        ]}
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
              title={layerText(kindOf(detail))[variant].title}
              action={
                <a
                  className="btn btn-outline btn-sm"
                  href={`${mapUrl(detail, variant, country || undefined)}&format=pdf`}
                >
                  PDF
                </a>
              }
            >
              <MapFigure
                src={mapUrl(detail, variant, country || undefined)}
                alt={`${layerText(kindOf(detail))[variant].title} Week-2 rainfall${country ? ` over ${country}` : ""}`}
                caption={`Valid ${validDays(detail.valid_start, detail.valid_end)}`}
              />
            </Card>
          ) : (
            <InProgress
              key={variant}
              title={layerText(kindOf(detail))[variant].title}
            >
              {productReason(detail.products?.[variant])}
            </InProgress>
          ),
        )}
      </div>
    </>
  );
}

/** The name of the model whose verified forecasts a pooled score uses. */
function modelName(data: MapsStatus): string {
  return (
    data.models?.find((m) => m.model_id === data.model_id)?.model_name ??
    "the model in use"
  );
}

function VerificationMap({ metric }: { metric: string }) {
  const [includeTest, setIncludeTest] = useState(false);
  /** Another model's verified weeks; empty: the model in use. */
  const [model, setModel] = useState<string | null>(null);
  const scope = `include_protected=${includeTest}${model ? `&model_id=${encodeURIComponent(model)}` : ""}`;
  const status = useApi<MapsStatus>(`/verification/maps?${scope}`);
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
          { label: "Verification", href: "/verification" },
          { label: "Error and skill maps" },
        ]}
        subtitle={info.text}
      />
      <nav className="tabs" aria-label="Verification map">
        {Object.entries(METRICS).map(([key, { title }]) => (
          <Link
            key={key}
            href={`/maps/${key}`}
            aria-current={key === metric ? "page" : undefined}
          >
            {title}
          </Link>
        ))}
      </nav>
      {status.loading && <Skeleton height={420} />}
      {status.error && (
        <ErrorState message={status.error} retry={status.reload} />
      )}
      {data && entry && (
        <>
          <ModelScope
            shown={data.model_id}
            models={data.models}
            onChoose={setModel}
          />
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
              subtitle={`${data.cases} verified ${data.cases === 1 ? "forecast" : "forecasts"} of ${modelName(data)}`}
            >
              <MapFigure
                src={`/api/verification/maps/${metric}?variant=${shown}&${scope}`}
                alt={`${info.title} of ${SERIES[shown].label} over verified forecasts`}
              />
            </Card>
          ) : (
            <>
              <InProgress title={`${info.title} map`}>
                A per-cell {info.title.toLowerCase()} needs at least{" "}
                {entry.min_cases} verified{" "}
                {entry.min_cases === 1 ? "forecast" : "forecasts"} of{" "}
                {modelName(data)}; {data.cases}{" "}
                {data.cases === 1 ? "is" : "are"} verified so far. Each weekly
                forecast is verified once CHIRPS covers its week.
              </InProgress>
              <PastWeeks onDone={status.reload} />
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
                  crumbs={[
                    { label: "Forecasts", href: "/forecasts" },
                    { label: "Rainfall maps" },
                  ]}
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
