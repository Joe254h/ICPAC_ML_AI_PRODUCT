"use client";
/** The eleven member states side by side: Week-2 rainfall of each, wettest first. */
import CountryCards from "@/components/country-cards";
import { Card, ErrorState, PageBanner, Skeleton } from "@/components/ui";
import type { PageProps } from "@/features/view";
import { SERIES, num, validDays } from "@/lib/format";
import type { ForecastDetail } from "@/types/operational";
import {
  NoForecast,
  forecastFacts,
  layersOf,
  primaryOf,
  useForecast,
} from "@/features/operational/shared";

const TITLE = "Member States";
const CRUMBS = [{ label: "Countries" }];

function Body({ detail }: { detail: ForecastDetail }) {
  const layers = layersOf(detail);
  const primary = primaryOf(detail);
  const rows = [...detail.countries].sort(
    (a, b) => (b[primary]?.mean_mm ?? 0) - (a[primary]?.mean_mm ?? 0),
  );
  return (
    <>
      <PageBanner
        title={TITLE}
        crumbs={CRUMBS}
        subtitle={`Week-2 (days 8–14) rainfall outlook for the eleven ICPAC member states, valid ${validDays(detail.valid_start, detail.valid_end)}.`}
        facts={forecastFacts(detail)}
      />
      <CountryCards detail={detail} />
      <Card
        title="Every layer, by country"
        subtitle="Area means and the highest local totals, wettest first."
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Country</th>
                {layers.map((v) => (
                  <th key={v} className="num">
                    {SERIES[v].label} mean (mm)
                  </th>
                ))}
                <th className="num">{SERIES[primary].label} highest (mm)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.country}>
                  <td className="strong">{row.country}</td>
                  {layers.map((v) => (
                    <td key={v} className="num">
                      {num(row[v]?.mean_mm)}
                    </td>
                  ))}
                  <td className="num">{num(row[primary]?.max_mm, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

export default function Countries({ id }: PageProps) {
  const forecast = useForecast(id);
  return (
    <div className="page">
      <div className="wrap">
        {forecast.loading && <Skeleton height={520} />}
        {forecast.status === 404 && (
          <>
            <PageBanner title={TITLE} crumbs={CRUMBS} />
            <NoForecast />
          </>
        )}
        {forecast.error && forecast.status !== 404 && (
          <ErrorState message={forecast.error} retry={forecast.reload} />
        )}
        {forecast.data && <Body detail={forecast.data} />}
      </div>
    </div>
  );
}
