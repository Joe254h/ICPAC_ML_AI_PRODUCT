"use client";
/** One country: forecast statistics, verification and the missing references. */
import { CircleSlash } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  MapImage,
  PageHeader,
  SeriesSwatch,
  Skeleton,
  Stat,
  Table,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import {
  ForecastBadges,
  MetricsTable,
  NoForecast,
  VARIANTS,
  forecastSubtitle,
  mapUrl,
  useForecast,
} from "@/features/operational/shared";
import { SERIES, num } from "@/lib/format";

export default function Country({ route, id }: PageProps) {
  const name = route.param ?? route.title;
  const forecast = useForecast(id);
  if (forecast.loading && !forecast.data)
    return <Skeleton className="h-[30rem]" />;
  if (forecast.status === 404)
    return (
      <>
        <PageHeader title={name} description="Week-2 rainfall outlook" />
        <NoForecast />
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
  const row = detail.countries.find((c) => c.country === name);
  if (!row)
    return (
      <Card>
        <EmptyState title={`${name} is not in this forecast`}>
          The authoritative country mapping of this forecast has no cells for{" "}
          {name}.
        </EmptyState>
      </Card>
    );
  const verification = detail.verification.countries?.[name];
  return (
    <>
      <PageHeader
        title={name}
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          series="hybrid"
          label="MBC + AI · mean"
          value={num(row.hybrid.mean_mm)}
          unit="mm/week"
          hint={`Cos-latitude weighted over ${row.cell_count.toLocaleString("en-GB")} cells`}
        />
        <Stat
          label="MBC + AI · median"
          value={num(row.hybrid.median_mm)}
          unit="mm/week"
        />
        <Stat
          label="MBC + AI · minimum"
          value={num(row.hybrid.min_mm)}
          unit="mm/week"
        />
        <Stat
          label="MBC + AI · maximum"
          value={num(row.hybrid.max_mm)}
          unit="mm/week"
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Raw ECMWF, MBC and MBC + AI"
            description="Week-2 totals over the country's cells (mm/week)"
          />
          <CardContent>
            <Table head={["Forecast", "Mean", "Median", "Min", "Max"]}>
              {VARIANTS.map((variant) => (
                <tr key={variant} className="tabular">
                  <td>
                    <span className="inline-flex items-center gap-2 font-medium">
                      <SeriesSwatch series={variant} />
                      {SERIES[variant].label}
                    </span>
                  </td>
                  <td className="font-medium">{num(row[variant].mean_mm)}</td>
                  <td>{num(row[variant].median_mm)}</td>
                  <td>{num(row[variant].min_mm)}</td>
                  <td>{num(row[variant].max_mm)}</td>
                </tr>
              ))}
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader
            title="Anomaly and forecast category"
            description="Not computed: their references are not among the HPC artifacts"
          />
          <CardContent className="grid gap-3">
            {[
              [
                "Anomaly",
                row.anomaly.reason,
                detail.interpretation.anomaly.missing_dependency,
              ],
              [
                "Category (tercile)",
                row.category.reason,
                detail.interpretation.category.missing_dependency,
              ],
            ].map(([label, reason, needs]) => (
              <div key={label} className="flex gap-3">
                <CircleSlash
                  size={18}
                  className="mt-0.5 shrink-0 text-subtle"
                />
                <div>
                  <div className="font-medium">{label}: unavailable</div>
                  <div className="text-muted-foreground">
                    {reason} · needs {needs}
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader
          title={`Verification over ${name}`}
          description={
            verification
              ? `Against CHIRPS · ${detail.verification.season} · ${detail.verification.use}`
              : "Appears once this forecast is verified against CHIRPS"
          }
        />
        <CardContent>
          {verification ? (
            <MetricsTable metrics={verification} />
          ) : (
            <p className="m-0 text-muted-foreground">
              No observed Week-2 total has been supplied for this window yet.
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader
          title="MBC + AI across the region"
          description="Regional map in the ICPAC standard"
        />
        <CardContent>
          <MapImage
            src={mapUrl(detail, "hybrid")}
            alt="MBC + AI Week-2 rainfall"
            className="mx-auto max-w-3xl"
          />
        </CardContent>
      </Card>
    </>
  );
}
