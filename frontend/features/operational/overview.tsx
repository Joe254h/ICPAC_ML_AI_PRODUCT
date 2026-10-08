"use client";
/** Overview: the latest Week-2 forecast with the map as the primary product. */
import { useState } from "react";
import { ArrowRight, Info } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  KeyValues,
  LinkButton,
  MapImage,
  ModelStatus,
  PageHeader,
  Segmented,
  SeriesSwatch,
  Skeleton,
  Stat,
  Table,
  TestStatus,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import type { PageProps } from "@/features/view";
import {
  CountryChart,
  CountryTable,
  ForecastBadges,
  NoForecast,
  VerificationCard,
  forecastSubtitle,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";
import { SERIES, num, signed } from "@/lib/format";
import type { SeriesKey } from "@/lib/format";
import type { OperationalModel, Variant } from "@/types/operational";

const LAYERS: { value: Variant; label: string }[] = [
  { value: "hybrid", label: "MBC + AI" },
  { value: "mbc", label: "MBC" },
  { value: "raw", label: "Raw ECMWF" },
];

/** Validation metrics come from the model's metrics.json (via the registry). */
export function ValidationCard({ model }: { model?: OperationalModel }) {
  const m = model?.metrics ?? {};
  const rows: [SeriesKey, string, Record<string, number> | null][] = [
    ["raw", "Raw ECMWF", null],
    ["mbc", "MBC", null],
    [
      "hybrid",
      "MBC + AI",
      "rainfall_MAE" in m
        ? {
            mae: m.rainfall_MAE,
            rmse: m.rainfall_RMSE,
            bias: m.rainfall_bias,
            r: m.rainfall_pearson_r,
          }
        : null,
    ],
  ];
  return (
    <Card>
      <CardHeader
        title="Validation skill of the model"
        description={
          model?.metrics_scope
            ? `${model.metrics_scope} · ${model.model_id}`
            : "From the model's metrics.json"
        }
      />
      <CardContent>
        <Table head={["Forecast", "MAE", "RMSE", "Bias", "Pearson r"]}>
          {rows.map(([key, label, values]) => (
            <tr key={key} className="tabular">
              <td>
                <span className="inline-flex items-center gap-2 font-medium">
                  <SeriesSwatch series={key} />
                  {label}
                </span>
              </td>
              {values ? (
                <>
                  <td>{num(values.mae, 2)} mm</td>
                  <td>{num(values.rmse, 2)} mm</td>
                  <td>{signed(values.bias, 2)} mm</td>
                  <td>{num(values.r, 3)}</td>
                </>
              ) : (
                <td colSpan={4} className="text-muted-foreground">
                  Not supplied with the HPC artifacts
                </td>
              )}
            </tr>
          ))}
        </Table>
        <p className="mb-0 mt-3 flex gap-2 text-[0.88rem] text-subtle">
          <Info size={15} className="mt-0.5 shrink-0" />
          Validation period only. The independent 2022–2024 test is run on the
          HPC and recorded once in the model registry.
        </p>
      </CardContent>
    </Card>
  );
}

export function ModelCard({ model }: { model?: OperationalModel }) {
  if (!model) return null;
  return (
    <Card>
      <CardHeader
        title="Model in use"
        action={<ModelStatus status={model.status} />}
      />
      <CardContent className="pt-3">
        <KeyValues
          items={[
            ["Model", model.model_id],
            ["Version", model.version],
            [
              "Method",
              `${model.baseline} baseline + ${model.algorithm} residual (${model.trees} trees)`,
            ],
            [
              "Feature family",
              `${model.family} · ${model.feature_count} features`,
            ],
            ["Training", model.training_period],
            ["Validation", model.validation_period],
            [
              "Independent test",
              <TestStatus key="t" status={model.test_status} />,
            ],
          ]}
        />
      </CardContent>
    </Card>
  );
}

export default function Overview({ id }: PageProps) {
  const forecast = useForecast(id);
  const { current } = useApp();
  const [layer, setLayer] = useState<Variant>("hybrid");
  if (forecast.loading && !forecast.data)
    return (
      <div className="grid gap-6">
        <Skeleton className="h-16" />
        <div className="grid gap-6 lg:grid-cols-3">
          <Skeleton className="h-[34rem] lg:col-span-2" />
          <Skeleton className="h-[34rem]" />
        </div>
      </div>
    );
  if (forecast.status === 404)
    return (
      <>
        <PageHeader
          title="Week-2 rainfall forecast"
          description="Days 8–14 rainfall for the eleven ICPAC member states."
        />
        <NoForecast />
        <div className="grid gap-6 lg:grid-cols-2">
          <ModelCard model={current.data?.model} />
          <ValidationCard model={current.data?.model} />
        </div>
      </>
    );
  if (forecast.error || !forecast.data)
    return (
      <ErrorState
        message={forecast.error ?? "Forecast unavailable"}
        retry={forecast.reload}
      />
    );
  const detail = forecast.data;
  const means = detail.interpretation.domain_mean_mm;
  return (
    <>
      <PageHeader
        title="Week-2 rainfall forecast"
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
        actions={
          <>
            <LinkButton href={"/forecasts?id=" + detail.forecast_id}>
              Forecast details
            </LinkButton>
            <LinkButton href="/bulletin" variant="primary">
              Weekly product <ArrowRight size={15} />
            </LinkButton>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title={`${SERIES[layer].label} · Week-2 rainfall`}
            description="ICPAC official boundaries · full Somalia extent · authoritative 205,999-cell domain · one colour scale for all three forecasts"
            action={
              <Segmented
                label="Forecast layer"
                options={LAYERS}
                value={layer}
                onChange={setLayer}
              />
            }
          />
          <CardContent>
            <MapImage
              src={mapUrl(detail, layer)}
              alt={`${SERIES[layer].label} Week-2 rainfall map, initialised ${detail.initialization}`}
            />
          </CardContent>
        </Card>
        <div className="grid content-start gap-4">
          {(["raw", "mbc", "hybrid"] as SeriesKey[]).map((key) => (
            <Stat
              key={key}
              series={key}
              label={`${SERIES[key].label} · domain mean`}
              value={num(means[key])}
              unit="mm/week"
              hint="Cos-latitude weighted over the 205,999 domain cells"
            />
          ))}
          <Card>
            <CardContent className="grid gap-1 text-[0.93rem]">
              <span className="text-muted-foreground">
                How MBC + AI is formed
              </span>
              <span>
                CatBoost predicts the residual CHIRPS − MBC from 37 Atmos37
                features; MBC + AI = max(MBC + residual, 0). Domain-mean
                residual: <strong>{signed(means.residual)} mm</strong>.
              </span>
            </CardContent>
          </Card>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <VerificationCard
          verification={detail.verification}
          forecastId={detail.forecast_id}
        />
        <ValidationCard model={current.data?.model} />
      </div>
      <Card>
        <CardHeader
          title="Country summaries"
          description="Week-2 totals over each country's cells in the authoritative country mapping"
          action={
            <LinkButton
              href={`/api/forecasts/${detail.forecast_id}/countries?format=csv`}
            >
              Download CSV
            </LinkButton>
          }
        />
        <CardContent className="grid gap-6 xl:grid-cols-2">
          <CountryChart rows={detail.countries} />
          <CountryTable rows={detail.countries} />
        </CardContent>
      </Card>
      <ModelCard model={current.data?.model} />
    </>
  );
}
