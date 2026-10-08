"use client";
/** One forecast layer (raw ECMWF, MBC or MBC + AI) with how it is computed. */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  MapImage,
  PageHeader,
  Skeleton,
  Stat,
  Table,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { countrySlug } from "@/features/routes";
import {
  ForecastBadges,
  NoForecast,
  forecastSubtitle,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";
import { SERIES, num } from "@/lib/format";
import type { ForecastDetail, Variant } from "@/types/operational";

function explanation(variant: Variant, detail: ForecastDetail): string[] {
  const p = detail.provenance;
  if (variant === "raw")
    return [
      `ECMWF S2S extended-range ensemble, ${p.ensemble_members} perturbed members (the control member is left out, as in training).`,
      "Week-2 total per member: accumulated tp at 336 h minus tp at 168 h.",
      "The ensemble mean is feature X_mean; the population standard deviation is X_spread.",
    ];
  if (variant === "mbc")
    return [
      "MBC = max(0, raw × R[month, cell]), the locked multiplicative bias correction.",
      `R holds 12 monthly ratios per domain cell (clipped to 0.05–20) from the locked MBC artifact; month ${p.mbc_month} is the initialization month.`,
      "MBC is feature 37 (MBC_forecast) and the baseline of the residual model.",
    ];
  return [
    `${p.model.algorithm} (${p.model.trees} trees) predicts the residual CHIRPS − MBC from ${detail.model.feature_count ?? 37} features: rainfall mean and spread, location, season and the Atmos37 atmospheric fields (humidity, winds, moisture transport, temperature, geopotential, shear).`,
    "MBC + AI = max(MBC + predicted residual, 0): a hybrid, residual-corrected forecast.",
    `Model ${p.model_id} (${detail.model_status}); trained ${detail.model.training_period ?? "?"}, validated ${detail.model.validation_period ?? "?"}.`,
  ];
}

export default function Layer({ route, id }: PageProps) {
  const variant = (route.param ?? "hybrid") as Variant;
  const forecast = useForecast(id);
  if (forecast.loading && !forecast.data)
    return <Skeleton className="h-[36rem]" />;
  if (forecast.status === 404) return <NoForecast />;
  if (forecast.error || !forecast.data)
    return (
      <ErrorState
        message={forecast.error ?? "Forecast unavailable"}
        retry={forecast.reload}
      />
    );
  const detail = forecast.data;
  const label = SERIES[variant].label;
  return (
    <>
      <PageHeader
        title={`${route.title} · Week-2 rainfall`}
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
      />
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardContent>
            <MapImage
              src={mapUrl(detail, variant)}
              alt={`${label} Week-2 rainfall map`}
            />
          </CardContent>
        </Card>
        <div className="grid content-start gap-4">
          <Stat
            series={variant}
            label={`${label} · domain mean`}
            value={num(detail.interpretation.domain_mean_mm[variant])}
            unit="mm/week"
          />
          <Card>
            <CardHeader title="How this layer is computed" />
            <CardContent className="pt-3">
              <ul className="m-0 grid gap-2.5 pl-4">
                {explanation(variant, detail).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader title={`${label} by country`} />
        <CardContent>
          <Table head={["Country", "Mean", "Median", "Min", "Max"]}>
            {detail.countries.map((row) => (
              <tr key={row.country} className="tabular">
                <td>
                  <Link
                    className="font-medium hover:underline"
                    href={"/countries/" + countrySlug(row.country)}
                  >
                    {row.country}
                  </Link>
                </td>
                <td className="font-medium">{num(row[variant].mean_mm)} mm</td>
                <td>{num(row[variant].median_mm)} mm</td>
                <td>{num(row[variant].min_mm)} mm</td>
                <td>{num(row[variant].max_mm)} mm</td>
              </tr>
            ))}
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
