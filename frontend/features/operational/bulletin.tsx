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
import { dateTime, validDays } from "@/lib/format";
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
        title="Weekly forecast bulletin"
        description={forecastSubtitle(detail)}
        badges={<ForecastBadges detail={detail} />}
        actions={
          <>
            {generator?.status === "ready" && status.data?.export && (
              <LinkButton href={"/api" + status.data.export}>
                Download Word draft
              </LinkButton>
            )}
            <LinkButton href="/bulletins">Bulletin drafts</LinkButton>
          </>
        }
      />
      {status.data?.sections && (
        <article
          className="bulletin-paper"
          aria-label="Weekly forecast bulletin preview"
        >
          <header>
            <p className="bulletin-organization">
              IGAD Climate Prediction and Applications Centre
            </p>
            <h1>
              {status.data.title ??
                `Weekly Forecast for ${validDays(detail.valid_start, detail.valid_end)}`}
            </h1>
            <p>
              Draft for forecaster review
              {detail.synthetic ? " · Synthetic test inputs" : ""}
            </p>
          </header>
          {status.data.sections.map((section) => (
            <section key={section.key}>
              <h2>{section.title}</h2>
              {section.text.map((text, index) => {
                if (!text) return null;
                // The reference's bold lead ("Heavy rainfall (above 200 mm)").
                const lead = section.leads?.[index] ?? "";
                return (
                  <p key={index}>
                    {lead && text.startsWith(lead) ? (
                      <>
                        <strong>{lead}</strong>
                        {text.slice(lead.length)}
                      </>
                    ) : (
                      text
                    )}
                  </p>
                );
              })}
              {section.map ? (
                // Scientific images are served through the binary API proxy.
                <img
                  src={"/api" + section.map}
                  alt={`${section.title} for this forecast`}
                  loading="lazy"
                />
              ) : section.missing_dependency ? (
                <div className="bulletin-missing-map">
                  <strong>{section.title} map unavailable</strong>
                  <p>{section.missing_dependency}</p>
                </div>
              ) : null}
            </section>
          ))}
          <footer>
            IGAD | ICPAC · Forecast {detail.forecast_id} · Human review required
            before release
          </footer>
        </article>
      )}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Product package"
            description={`Forecast ${detail.forecast_id} · generated ${dateTime(detail.generation_time)}`}
          />
          <CardContent className="pt-3">
            <Downloads detail={detail} />
          </CardContent>
        </Card>
        <div className="grid min-w-0 grid-cols-1 content-start gap-6">
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
    </>
  );
}
