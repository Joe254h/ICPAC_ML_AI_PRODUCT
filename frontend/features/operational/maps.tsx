"use client";
/** Maps: forecast rainfall, and gridded verification metrics over verified forecasts. */
import { useState } from "react";
import { MapPinned } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  LinkButton,
  MapImage,
  Notice,
  PageHeader,
  Segmented,
  SeriesSwatch,
  Skeleton,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import {
  ForecastBadges,
  NoForecast,
  VARIANTS,
  forecastSubtitle,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";
import { SERIES } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { MapsStatus, Variant } from "@/types/operational";

const ABOUT: Record<string, string> = {
  bias: "Mean of forecast − CHIRPS in each cell over the verified forecasts (mm/week). Positive: the forecast is too wet.",
  rmse: "Root mean square error in each cell over the verified forecasts (mm/week).",
  correlation:
    "Pearson correlation between forecast and CHIRPS in each cell across the verified forecasts.",
  skill:
    "Relative RMSE improvement over raw ECMWF in each cell: 1 − RMSE / RMSE(raw ECMWF). Positive values beat the raw forecast.",
};

function RainfallMaps({ id }: { id?: string }) {
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
  return (
    <>
      <PageHeader
        title="Rainfall maps"
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
      />
      <div className="grid gap-6 lg:grid-cols-2">
        {[...VARIANTS].reverse().map((variant) => (
          <Card key={variant}>
            <CardHeader
              title={
                <span className="inline-flex items-center gap-2">
                  <SeriesSwatch series={variant} />
                  {SERIES[variant].label}
                </span>
              }
            />
            <CardContent>
              <MapImage
                src={mapUrl(detail, variant)}
                alt={`${SERIES[variant].label} Week-2 rainfall`}
              />
            </CardContent>
          </Card>
        ))}
        <Card>
          <CardHeader
            title="Predicted residual"
            description="CatBoost correction added to MBC"
          />
          <CardContent>
            <MapImage
              src={mapUrl(detail, "residual")}
              alt="Predicted residual"
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function VerificationMap({ metric, title }: { metric: string; title: string }) {
  const [variant, setVariant] = useState<Variant>("hybrid");
  const [protectedPeriod, setProtectedPeriod] = useState(false);
  const status = useApi<MapsStatus>(
    "/verification/maps?include_protected=" + protectedPeriod,
  );
  const info = status.data?.metrics[metric];
  const shown = metric === "skill" && variant === "raw" ? "hybrid" : variant;
  return (
    <>
      <PageHeader
        title={`${title} map`}
        description={ABOUT[metric]}
        actions={
          <label className="inline-flex items-center gap-2 text-muted-foreground">
            <input
              type="checkbox"
              checked={protectedPeriod}
              onChange={(e) => setProtectedPeriod(e.target.checked)}
              className="accent-primary"
            />
            Include the 2022–2024 test period (display only)
          </label>
        }
      />
      {status.loading && !status.data ? (
        <Skeleton className="h-[30rem]" />
      ) : status.status === 404 ? (
        <Card>
          <EmptyState
            icon={<MapPinned size={30} />}
            title="No operational model"
          >
            Register an operational model first.
          </EmptyState>
        </Card>
      ) : status.error || !status.data || !info ? (
        <ErrorState
          message={status.error ?? "Unavailable"}
          retry={status.reload}
        />
      ) : !info.available ? (
        <Card>
          <EmptyState
            icon={<MapPinned size={30} />}
            title={`${title} needs ${info.min_cases} verified forecast${info.min_cases > 1 ? "s" : ""}`}
            action={
              <LinkButton href="/verification">Verify forecasts</LinkButton>
            }
          >
            {status.data.cases} verified forecast
            {status.data.cases === 1 ? "" : "s"} of {status.data.model_id} so
            far
            {status.data.excluded_protected_period
              ? ` (${status.data.excluded_protected_period} more in the protected test period)`
              : ""}
            . A forecast is verified once the observed CHIRPS Week-2 total for
            its window is supplied.
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <CardHeader
            title={`${title} · ${SERIES[shown].label}`}
            description={`${status.data.cases} verified forecasts of ${status.data.model_id}`}
            action={
              <Segmented
                label="Forecast"
                value={shown}
                onChange={setVariant}
                options={VARIANTS.map((v) => ({
                  value: v,
                  label: SERIES[v].label,
                  disabled: metric === "skill" && v === "raw",
                }))}
              />
            }
          />
          <CardContent className="grid gap-3">
            {protectedPeriod && (
              <Notice tone="warning">
                Includes forecasts valid in the protected 2022–2024 test period:
                for display only, never for model selection.
              </Notice>
            )}
            <MapImage
              src={`/api/verification/maps/${metric}?variant=${shown}&include_protected=${protectedPeriod}`}
              alt={`${title} map for ${SERIES[shown].label}`}
            />
          </CardContent>
        </Card>
      )}
    </>
  );
}

export default function Maps({ route, id }: PageProps) {
  if (route.param === "rainfall") return <RainfallMaps id={id} />;
  return <VerificationMap metric={route.param ?? "rmse"} title={route.title} />;
}
