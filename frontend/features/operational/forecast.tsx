"use client";
/** Latest (or ?id=) forecast: all three forecasts, facts, countries, provenance. */
import { AlertTriangle } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  LinkButton,
  MapImage,
  PageHeader,
  SeriesSwatch,
  Skeleton,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import {
  CountryTable,
  Downloads,
  ForecastBadges,
  ForecastFacts,
  NoForecast,
  ProvenanceList,
  VARIANTS,
  VerificationCard,
  forecastSubtitle,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";
import { SERIES, day } from "@/lib/format";

export default function Forecast({ id }: PageProps) {
  const forecast = useForecast(id);
  if (forecast.loading && !forecast.data)
    return <Skeleton className="h-[40rem]" />;
  if (forecast.status === 404) return <NoForecast />;
  if (forecast.error || !forecast.data)
    return (
      <ErrorState
        message={forecast.error ?? "Forecast unavailable"}
        retry={forecast.reload}
      />
    );
  const detail = forecast.data;
  const caveats = [
    ...detail.interpretation.caveats,
    ...detail.notes.filter((n) => !detail.interpretation.caveats.includes(n)),
  ].filter(
    (text) =>
      !(
        detail.map_style === "weekly-v1" &&
        text.startsWith("Rainfall map colours follow a provisional style")
      ),
  );
  return (
    <>
      <PageHeader
        title={`Week-2 forecast · ${day(detail.initialization)}`}
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
        actions={
          <LinkButton href="/forecasts/week-2">All Week-2 forecasts</LinkButton>
        }
      />
      <Card>
        <CardHeader
          title="Raw ECMWF, MBC and MBC + AI"
          description="One colour scale across the three maps; the hybrid is the residual-corrected forecast"
        />
        <CardContent className="grid gap-4 lg:grid-cols-3">
          {VARIANTS.map((variant) => (
            <figure key={variant} className="m-0 grid gap-2">
              <figcaption className="flex items-center gap-2 font-medium">
                <SeriesSwatch series={variant} />
                {SERIES[variant].label}
              </figcaption>
              <MapImage
                src={mapUrl(detail, variant)}
                alt={`${SERIES[variant].label} Week-2 rainfall`}
              />
            </figure>
          ))}
        </CardContent>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Forecast facts" />
          <CardContent className="pt-3">
            <ForecastFacts detail={detail} />
          </CardContent>
        </Card>
        <div className="grid content-start gap-6">
          <Card>
            <CardHeader
              title="Caveats and missing products"
              description="Stated by the backend for this forecast"
            />
            <CardContent className="grid gap-3">
              <ul className="m-0 grid gap-2 pl-0">
                {caveats.map((text) => (
                  <li key={text} className="flex gap-2">
                    <AlertTriangle
                      size={16}
                      className="mt-0.5 shrink-0 text-status-serious-ink"
                    />
                    <span>{text}</span>
                  </li>
                ))}
              </ul>
              <div className="grid gap-1 border-t border-border pt-3 text-[0.9rem] text-muted-foreground">
                {Object.entries(detail.manifest.missing_dependencies)
                  .filter(
                    ([product]) =>
                      product !== "bulletin" ||
                      detail.bulletin_generator?.status !== "ready",
                  )
                  .map(([product, needs]) => (
                    <span key={product}>
                      <strong className="text-foreground">
                        {product[0].toUpperCase() + product.slice(1)}:
                      </strong>{" "}
                      unavailable · needs {needs}
                    </span>
                  ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader
              title="Predicted residual"
              description={`${detail.algorithm} correction added to MBC (CHIRPS − MBC learned on ${detail.model.training_period ?? "the training period"})`}
            />
            <CardContent>
              <MapImage
                src={mapUrl(detail, "residual")}
                alt="Predicted residual map"
              />
            </CardContent>
          </Card>
        </div>
      </div>
      <VerificationCard
        verification={detail.verification}
        forecastId={detail.forecast_id}
      />
      <Card>
        <CardHeader
          title="Country summaries"
          description="MBC + AI median, minimum and maximum over each country's cells"
        />
        <CardContent>
          <CountryTable rows={detail.countries} />
        </CardContent>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Product package"
            description="Stable file names · SHA256 of each file in the manifest"
          />
          <CardContent className="pt-3">
            <Downloads detail={detail} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Provenance" />
          <CardContent className="pt-3">
            <ProvenanceList detail={detail} />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
