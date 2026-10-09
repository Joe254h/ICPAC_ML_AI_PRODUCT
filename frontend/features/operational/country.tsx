"use client";
/** One member state: its Week-2 rainfall map, statistics and verification. */
import Link from "next/link";
import { useState } from "react";
import {
  Card,
  ErrorState,
  MapFigure,
  PageBanner,
  Skeleton,
  Stat,
  Tabs,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { COUNTRIES, countrySlug } from "@/features/routes";
import { SERIES, num, validDays } from "@/lib/format";
import type { ForecastDetail, Variant } from "@/types/operational";
import {
  MetricsTable,
  NoForecast,
  forecastFacts,
  layersOf,
  mapUrl,
  primaryOf,
  useForecast,
} from "@/features/operational/shared";

function Body({
  detail,
  country,
}: {
  detail: ForecastDetail;
  country: string;
}) {
  const layers = layersOf(detail);
  const [layer, setLayer] = useState<Variant>(primaryOf(detail));
  const row = detail.countries.find((r) => r.country === country);
  const stats = row?.[layer];
  const rank =
    [...detail.countries]
      .sort((a, b) => (b[layer]?.mean_mm ?? 0) - (a[layer]?.mean_mm ?? 0))
      .findIndex((r) => r.country === country) + 1;
  const verified = detail.verification.countries?.[country];
  return (
    <>
      <PageBanner
        title={country}
        crumbs={[{ label: "Countries" }, { label: country }]}
        subtitle={`Week-2 (days 8–14) rainfall outlook for ${country}, valid ${validDays(detail.valid_start, detail.valid_end)}.`}
        facts={forecastFacts(detail)}
      />
      <Tabs
        label="Forecast layer"
        value={layer}
        onChange={setLayer}
        options={layers.map((v) => ({ value: v, label: SERIES[v].label }))}
      />
      <div className="stats">
        <Stat
          label="Area mean"
          value={num(stats?.mean_mm)}
          unit="mm"
          hint={SERIES[layer].label}
        />
        <Stat label="Median" value={num(stats?.median_mm)} unit="mm" />
        <Stat
          label="Wettest cell"
          value={num(stats?.max_mm, 0)}
          unit="mm"
          tone="amber"
        />
        <Stat
          label="Regional rank"
          value={rank ? `${rank} of ${detail.countries.length}` : "—"}
          hint="By area mean, wettest first"
        />
      </div>
      <div className="split" style={{ alignItems: "start" }}>
        <MapFigure
          src={mapUrl(detail, layer, country)}
          alt={`${SERIES[layer].label} Week-2 rainfall over ${country}`}
          caption={`${SERIES[layer].label} · ${country} · valid ${validDays(detail.valid_start, detail.valid_end)}`}
        />
        <Card title="All layers">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Layer</th>
                  <th className="num">Mean</th>
                  <th className="num">Min</th>
                  <th className="num">Max</th>
                </tr>
              </thead>
              <tbody>
                {layers.map((v) => (
                  <tr key={v}>
                    <td className="strong">{SERIES[v].label}</td>
                    <td className="num">{num(row?.[v]?.mean_mm)} mm</td>
                    <td className="num">{num(row?.[v]?.min_mm)}</td>
                    <td className="num">{num(row?.[v]?.max_mm)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
            {row?.cell_count.toLocaleString("en-GB")} grid cells of 0.05°.
            Anomalies and tercile categories need a Week-2 climatology and are
            not produced yet.
          </p>
          <h3 style={{ margin: "26px 0 12px" }}>Verification</h3>
          {verified ? (
            <MetricsTable metrics={verified} />
          ) : (
            <p style={{ margin: 0 }}>
              Not verified yet: scores appear once CHIRPS covers this
              forecast&apos;s week.
            </p>
          )}
        </Card>
      </div>
      <Card title="Other member states">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {COUNTRIES.filter((c) => c !== country).map((c) => (
            <Link
              key={c}
              className="btn btn-outline btn-sm"
              href={"/countries/" + countrySlug(c)}
            >
              {c}
            </Link>
          ))}
        </div>
      </Card>
    </>
  );
}

export default function Country({ route, id }: PageProps) {
  const country = route.param ?? "Kenya";
  const forecast = useForecast(id);
  return (
    <div className="page">
      <div className="wrap">
        {forecast.loading && <Skeleton height={520} />}
        {forecast.status === 404 && (
          <>
            <PageBanner
              title={country}
              crumbs={[{ label: "Countries" }, { label: country }]}
            />
            <NoForecast />
          </>
        )}
        {forecast.error && forecast.status !== 404 && (
          <ErrorState message={forecast.error} retry={forecast.reload} />
        )}
        {forecast.data && <Body detail={forecast.data} country={country} />}
      </div>
    </div>
  );
}
