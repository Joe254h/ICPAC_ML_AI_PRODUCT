"use client";
/** Bulletin › Weekly product: the forecast's product package and the bulletin status. */
import { FileWarning } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  KeyValues,
  LinkButton,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import {
  Downloads,
  ForecastBadges,
  NoForecast,
  forecastSubtitle,
  useForecast,
} from "@/features/operational/shared";
import { dateTime } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { BulletinStatus } from "@/types/operational";

export default function Bulletin({ id }: PageProps) {
  const forecast = useForecast(id);
  const status = useApi<BulletinStatus>(
    forecast.data ? `/forecasts/${forecast.data.forecast_id}/bulletin` : null,
  );
  if (forecast.loading && !forecast.data) return <Skeleton className="h-96" />;
  if (forecast.status === 404) return <NoForecast />;
  if (forecast.error || !forecast.data)
    return (
      <ErrorState
        message={forecast.error ?? "Forecast unavailable"}
        retry={forecast.reload}
      />
    );
  const detail = forecast.data;
  const generator = status.data?.generator;
  return (
    <>
      <PageHeader
        title="Weekly product"
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
        actions={<LinkButton href="/bulletins">Bulletin drafts</LinkButton>}
      />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Product package"
            description={`Forecast ${detail.forecast_id} · generated ${dateTime(detail.generation_time)}`}
          />
          <CardContent className="pt-3">
            <Downloads detail={detail} />
          </CardContent>
        </Card>
        <div className="grid content-start gap-6">
          <Card>
            <CardHeader
              title={
                <span className="inline-flex items-center gap-2">
                  <FileWarning size={17} /> Word bulletin
                </span>
              }
              description="Draft in the supplied ICPAC weekly bulletin format"
            />
            <CardContent className="pt-3">
              {status.loading && !status.data ? (
                <Skeleton className="h-20" />
              ) : status.error ? (
                <ErrorState message={status.error} retry={status.reload} />
              ) : generator?.status === "ready" ? (
                <div className="space-y-3">
                  <p>
                    Uses the supplied bulletin's headings, page settings,
                    header, footer and figure positions.
                  </p>
                  <p className="text-muted-foreground">{generator.review}</p>
                  <p className="text-muted-foreground">
                    {generator.layout_validation}
                  </p>
                  {status.data?.export && (
                    <a
                      className="inline-flex items-center rounded-md border border-border px-3 py-2 font-medium hover:bg-muted"
                      href={"/api" + status.data.export}
                    >
                      Download Word draft
                    </a>
                  )}
                </div>
              ) : generator ? (
                <KeyValues
                  items={[
                    [
                      "Status",
                      generator.status === "unavailable"
                        ? "Unavailable"
                        : generator.status,
                    ],
                    ["Missing dependency", generator.missing_dependency],
                    ["To enable", generator.how_to_supply],
                  ]}
                />
              ) : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader
              title="Interpretation inputs"
              description="Facts a forecaster or the Copilot can use; no narrative is generated"
            />
            <CardContent className="pt-3">
              <KeyValues
                items={[
                  ["Method", detail.interpretation.method.label],
                  ["Model role", detail.interpretation.model.role],
                  ["Input", detail.interpretation.input.label],
                  [
                    "Anomaly",
                    `unavailable · ${detail.interpretation.anomaly.missing_dependency}`,
                  ],
                  [
                    "Category",
                    `unavailable · ${detail.interpretation.category.missing_dependency}`,
                  ],
                ]}
              />
            </CardContent>
          </Card>
        </div>
      </div>
      {status.data?.sections && (
        <Card>
          <CardHeader
            title="Weekly bulletin draft"
            description="Current package facts in the supplied bulletin's section order. Missing products remain explicit; forecaster review is required."
          />
          <CardContent className="space-y-6 pt-3">
            {status.data.sections.map((section) => (
              <section key={section.key} className="space-y-3">
                <h2 className="text-lg font-semibold">{section.title}</h2>
                {section.text.filter(Boolean).map((text, index) => (
                  <p key={index}>{text}</p>
                ))}
                {section.map && (
                  // Package maps are scientific images served through the binary API proxy.
                  <img
                    src={"/api" + section.map}
                    alt={`${section.title} for this forecast`}
                    loading="lazy"
                    className="mx-auto h-auto w-full max-w-2xl"
                  />
                )}
              </section>
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
