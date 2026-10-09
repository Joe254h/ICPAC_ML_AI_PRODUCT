"use client";
/** Rainfall monitoring: observed rainfall of the latest CHIRPS dekad, by country. */
import Link from "next/link";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import RainMap, { LegendBar } from "@/components/rain-map";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  InProgress,
  Notice,
  PageBanner,
  Skeleton,
  Stat,
} from "@/components/ui";
import { useActor } from "@/lib/actor";
import { num, period, shortPeriod } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type { Dekad } from "@/types/operational";

type Product = "total" | "percent";

const CLASSES: Record<
  Product,
  { title: string; unit?: string; classes: [string, string][] }
> = {
  total: {
    title: "Dekad rainfall",
    unit: "mm",
    classes: [
      ["#ffffff", "<1"],
      ["#c0c0c0", "1–5"],
      ["#ff8c00", "5–10"],
      ["#ffff00", "10–25"],
      ["#98fb98", "25–50"],
      ["#00fa9a", "50–100"],
      ["#00ff00", "100–200"],
      ["#006400", ">200"],
    ],
  },
  percent: {
    title: "Percent of normal",
    unit: "%",
    classes: [
      ["#ffffff", "<1"],
      ["#ffa500", "1–25"],
      ["#ffff00", "25–75"],
      ["#add8e6", "75–125"],
      ["#90ee90", "125–175"],
      ["#228b22", ">175"],
    ],
  },
};

const LATER = [
  "Monthly rainfall totals and percent of normal",
  "Seasonal rainfall totals and anomalies",
  "Standardised Precipitation Index (SPI), monthly and seasonal",
];

function DekadMap({ dekad }: { dekad: Dekad }) {
  const percent = dekad.percent_of_normal.status === "available";
  const [product, setProduct] = useState<Product>("total");
  if (!dekad.overlays || !dekad.overlay_bounds) return null;
  const legend = CLASSES[product];
  return (
    <Card flush>
      <RainMap
        overlay={dekad.overlays[product] ?? dekad.overlays.total}
        bounds={dekad.overlay_bounds}
        height={620}
        credit="Observed: CHIRPS, Climate Hazards Center (UCSB)"
        hover={(name) => {
          const row = dekad.countries.find((c) => c.country === name);
          if (!row) return null;
          return product === "percent" && row.percent_of_normal != null
            ? `${row.percent_of_normal}% of normal`
            : `Mean ${num(row.mean_mm)} mm · up to ${num(row.max_mm, 0)} mm`;
        }}
      >
        <div className="map-switch">
          <div className="segmented light" role="group" aria-label="Product">
            <button
              type="button"
              aria-pressed={product === "total"}
              onClick={() => setProduct("total")}
            >
              Total rainfall
            </button>
            <button
              type="button"
              aria-pressed={product === "percent"}
              disabled={!percent}
              title={percent ? undefined : "In progress"}
              onClick={() => setProduct("percent")}
            >
              Percent of normal
              {!percent && <small>in progress</small>}
            </button>
          </div>
        </div>
        <div className="map-legend-corner light">
          <LegendBar
            title={legend.title}
            unit={legend.unit}
            classes={legend.classes}
          />
        </div>
      </RainMap>
    </Card>
  );
}

function Body({ dekad, history }: { dekad: Dekad; history?: Dekad[] }) {
  const rows = [...dekad.countries].sort((a, b) => b.mean_mm - a.mean_mm);
  const percent = dekad.percent_of_normal.status === "available";
  return (
    <>
      <div className="stats">
        <Stat
          label="Dekad"
          value={shortPeriod(dekad.start, dekad.end)}
          hint={`${dekad.start.slice(0, 4)} · CHIRPS preliminary`}
        />
        <Stat
          label="Regional mean"
          value={num(dekad.region.mean_mm)}
          unit="mm"
          hint="Area average over the eleven member states"
        />
        <Stat
          label="Wettest country"
          value={rows[0]?.country ?? "—"}
          hint={rows[0] ? `Mean ${num(rows[0].mean_mm)} mm` : undefined}
        />
        <Stat
          label="Area below 1 mm"
          value={`${Math.round(dekad.region.dry_fraction * 100)}%`}
          tone="amber"
          hint="Of the region's grid cells"
        />
      </div>
      <DekadMap dekad={dekad} />
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Card
          title="Member states"
          subtitle="Area means of the dekad, wettest first."
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Country</th>
                  <th className="num">Mean (mm)</th>
                  <th className="num">Highest (mm)</th>
                  <th className="num">Below 1 mm</th>
                  {percent && <th className="num">% of normal</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.country}>
                    <td className="strong">{row.country}</td>
                    <td className="num">{num(row.mean_mm)}</td>
                    <td className="num">{num(row.max_mm, 0)}</td>
                    <td className="num">
                      {Math.round(row.dry_fraction * 100)}%
                    </td>
                    {percent && (
                      <td className="num">
                        {row.percent_of_normal != null
                          ? `${row.percent_of_normal}%`
                          : "—"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <div style={{ display: "grid", gap: 20 }}>
          {!percent && (
            <InProgress title="Percent of normal">
              {dekad.percent_of_normal.reason ??
                "It needs the 1991–2020 long-term mean of each dekad."}
            </InProgress>
          )}
          <Card
            title="Coming later"
            subtitle="The other products of ICPAC's climate monitoring."
          >
            <ul style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}>
              {LATER.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </Card>
          <Card title="About the data">
            <p>
              CHIRPS combines satellite rainfall estimates with station
              observations at about 5 km. The preliminary dekad is published a
              few days after it ends; percent of normal compares it with the
              1991–2020 average of the same dekad.
            </p>
            <p>
              Forecasts are verified against the daily CHIRPS files, see{" "}
              <Link href="/verification">Verification</Link>.
            </p>
          </Card>
        </div>
      </div>
      {history && history.length > 1 && (
        <Card title="Earlier dekads">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Dekad</th>
                  <th className="num">Regional mean (mm)</th>
                  <th>Wettest country</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item) => {
                  const wettest = [...item.countries].sort(
                    (a, b) => b.mean_mm - a.mean_mm,
                  )[0];
                  return (
                    <tr key={item.dekad}>
                      <td className="strong">{period(item.start, item.end)}</td>
                      <td className="num">{num(item.region.mean_mm)}</td>
                      <td>
                        {wettest
                          ? `${wettest.country} (${num(wettest.mean_mm)} mm)`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

export default function Monitoring() {
  const latest = useApi<Dekad>("/monitoring/dekads/latest");
  const history = useApi<Dekad[]>("/monitoring/dekads");
  const [actor] = useActor();
  const { operation, error, running, start } = useOperation(() => {
    latest.reload();
    history.reload();
  });
  const check = () => start("update_chirps", actor || "Forecaster");
  const dekad = latest.data;
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Rainfall Monitoring"
          crumbs={[{ label: "Monitoring" }]}
          subtitle="Observed rainfall over the Greater Horn of Africa from CHIRPS, dekad by dekad, as ICPAC's climate monitoring presents it."
          facts={
            dekad
              ? [
                  `Latest dekad ${period(dekad.start, dekad.end)}`,
                  "CHIRPS preliminary",
                  "Checked daily",
                ]
              : ["CHIRPS preliminary", "Checked daily"]
          }
          actions={
            <Button variant="amber" disabled={running} onClick={check}>
              <RefreshCw size={17} className={running ? "spin" : undefined} />
              {running ? "Checking…" : "Check for a new dekad"}
            </Button>
          }
        />
        {error && <ErrorState message={error} />}
        {operation &&
          operation.status !== "running" &&
          operation.status !== "queued" && (
            <Notice
              tone={operation.status === "complete" ? "green" : "red"}
              title={
                operation.status === "complete"
                  ? "Checked."
                  : "The check failed."
              }
            >
              {operation.status === "complete"
                ? operation.messages.at(-2)?.text
                : operation.error}
            </Notice>
          )}
        {latest.loading && <Skeleton height={520} />}
        {latest.status === 404 && (
          <EmptyState
            title="No dekad downloaded yet"
            action={
              <Button variant="amber" disabled={running} onClick={check}>
                Download the newest dekad
              </Button>
            }
          >
            <p style={{ margin: 0 }}>
              The newest CHIRPS dekad is downloaded by the weekly cycle and the
              daily task, or now with the button.
            </p>
          </EmptyState>
        )}
        {latest.error && latest.status !== 404 && (
          <ErrorState message={latest.error} retry={latest.reload} />
        )}
        {dekad && <Body dekad={dekad} history={history.data} />}
      </div>
    </div>
  );
}
