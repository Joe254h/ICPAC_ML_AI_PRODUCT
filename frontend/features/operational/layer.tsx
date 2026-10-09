"use client";
/** One forecast layer (raw ECMWF, MBC or MBC + AI/ML): how it is made and its map. */
import Link from "next/link";
import {
  Card,
  ErrorState,
  InProgress,
  LinkButton,
  MapFigure,
  PageBanner,
  Skeleton,
  Stat,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { countrySlug } from "@/features/routes";
import { SERIES, num, validDays } from "@/lib/format";
import { useApp } from "@/components/shell";
import type { ForecastDetail, Variant } from "@/types/operational";
import {
  LAYER_TEXT,
  NoForecast,
  forecastFacts,
  layersOf,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";

const STEPS: Record<Variant, string[]> = {
  raw: [
    "Download the 00 UTC ECMWF ensemble from ECMWF Open Data: total precipitation of the 50 perturbed members at 168 h and 336 h.",
    "Week-2 total per member = precipitation at 336 h minus precipitation at 168 h.",
    "Average the 0.25° fields to the 1.5° grid of the ECMWF S2S forecasts the models were trained on, then interpolate bilinearly to the 0.05° ICPAC grid.",
    "Ensemble mean (the raw forecast) and spread over the members.",
  ],
  mbc: [
    "Start from the raw ECMWF ensemble mean.",
    "Multiply each cell by its locked ratio of CHIRPS to ECMWF rainfall for the initialization month (fitted on 2005–2021, clipped to 0.05–20).",
    "Keep the result at or above zero: MBC = max(0, raw × ratio).",
  ],
  hybrid: [
    "Build 37 predictors per cell: ensemble rainfall mean and spread, location, season, the MBC forecast and atmospheric fields at 850, 700, 500 and 200 hPa (humidity, winds, moisture transport, temperature, geopotential, shear).",
    "A CatBoost model (378 trees) predicts what MBC still gets wrong: the residual CHIRPS − MBC.",
    "MBC + AI/ML = max(MBC + predicted residual, 0).",
  ],
};

function Body({
  detail,
  variant,
}: {
  detail: ForecastDetail;
  variant: Variant;
}) {
  const { config } = useApp();
  const text = LAYER_TEXT[variant];
  const available = layersOf(detail).includes(variant);
  const reason =
    detail.products?.hybrid?.reason ??
    config.data?.operational.hybrid.reason ??
    undefined;
  const mean = detail.interpretation.domain_mean_mm[variant];
  const rows = [...detail.countries].sort(
    (a, b) => (b[variant]?.mean_mm ?? 0) - (a[variant]?.mean_mm ?? 0),
  );
  return (
    <>
      <PageBanner
        title={`${text.title} Week-2 Rainfall`}
        crumbs={[
          { label: "Forecasts", href: "/forecasts" },
          { label: text.title },
        ]}
        subtitle={text.method}
        facts={forecastFacts(detail)}
      />
      {!available ? (
        <>
          <InProgress title="MBC + AI/ML hybrid">
            {reason
              ? `${reason[0].toUpperCase()}${reason.slice(1)}. Forecasts are issued from MBC until then.`
              : "The AI/ML model's inputs are not available yet, so forecasts are issued from MBC."}
          </InProgress>
          <Card title="What is needed to complete it">
            <ol
              style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 10 }}
            >
              <li>
                The seven Week-2 forecast steps at which the training code read
                the pressure-level fields (
                <code>ecmwf.pressure.week2_steps_hours</code> in{" "}
                <code>config/operational.yaml</code>), taken from the HPC
                feature script.
              </li>
              <li>
                ECMWF ensemble fields of specific humidity, winds, temperature
                and geopotential at 850, 700, 500 and 200 hPa for those steps.
              </li>
              <li>
                With both, every run adds the hybrid layer automatically; until
                then the model artifacts are verified but not used for the
                forecast.
              </li>
            </ol>
            <p style={{ margin: "18px 0 0" }}>
              <Link className="link-amber" href="/forecasts/mbc">
                See the MBC forecast in use →
              </Link>
            </p>
          </Card>
        </>
      ) : (
        <>
          <div className="stats">
            <Stat
              label="Regional mean"
              value={num(mean)}
              unit="mm"
              hint="Area mean, days 8–14"
            />
            <Stat
              label="Wettest country"
              value={rows[0]?.country ?? "—"}
              hint={`${num(rows[0]?.[variant]?.mean_mm)} mm`}
              tone="amber"
            />
            <Stat
              label="Driest country"
              value={rows.at(-1)?.country ?? "—"}
              hint={`${num(rows.at(-1)?.[variant]?.mean_mm)} mm`}
            />
          </div>
          <div className="split" style={{ alignItems: "start" }}>
            <MapFigure
              src={mapUrl(detail, variant)}
              alt={`${text.title} Week-2 rainfall map`}
              caption={`${SERIES[variant].label} · valid ${validDays(detail.valid_start, detail.valid_end)}`}
            />
            <Card title="How it is made">
              <ol
                style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 12 }}
              >
                {STEPS[variant].map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </Card>
          </div>
          <Card
            title="By country"
            subtitle={`${text.title} area mean and range (mm).`}
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Country</th>
                    <th className="num">Mean</th>
                    <th className="num">Median</th>
                    <th className="num">Min</th>
                    <th className="num">Max</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.country}>
                      <td className="strong">
                        <Link href={"/countries/" + countrySlug(row.country)}>
                          {row.country}
                        </Link>
                      </td>
                      <td className="num strong">
                        {num(row[variant]?.mean_mm)}
                      </td>
                      <td className="num">{num(row[variant]?.median_mm)}</td>
                      <td className="num">{num(row[variant]?.min_mm)}</td>
                      <td className="num">{num(row[variant]?.max_mm)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <p style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {(["raw", "mbc", "hybrid"] as Variant[])
          .filter((v) => v !== variant)
          .map((v) => (
            <LinkButton
              key={v}
              href={`/forecasts/${v}`}
              variant="outline"
              size="sm"
            >
              {LAYER_TEXT[v].title}
            </LinkButton>
          ))}
      </p>
    </>
  );
}

export default function Layer({ route, id }: PageProps) {
  const variant = (route.param ?? "mbc") as Variant;
  const forecast = useForecast(id);
  return (
    <div className="page">
      <div className="wrap">
        {forecast.loading && <Skeleton height={520} />}
        {forecast.status === 404 && (
          <>
            <PageBanner
              title={`${LAYER_TEXT[variant].title} Week-2 Rainfall`}
              subtitle={LAYER_TEXT[variant].method}
            />
            <NoForecast />
          </>
        )}
        {forecast.error && forecast.status !== 404 && (
          <ErrorState message={forecast.error} retry={forecast.reload} />
        )}
        {forecast.data && <Body detail={forecast.data} variant={variant} />}
      </div>
    </div>
  );
}
