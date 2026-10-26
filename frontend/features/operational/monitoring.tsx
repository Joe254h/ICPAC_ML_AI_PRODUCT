"use client";
/** Rainfall monitoring: observed rainfall of the latest dekad from CHIRPS, TAMSAT, ARC 2.0,
 * RFE 2.0 or GPM IMERG, by country. */
import Link from "next/link";
import { useEffect, useState } from "react";
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
import { dateTime, num, period, sentence, shortPeriod } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type { Dekad, Estimate, RainfallEstimate } from "@/types/operational";

type Product = "total" | "percent";
type Source = RainfallEstimate;
const ORDER: Source[] = ["chirps", "tamsat", "arc2", "rfe2", "imerg"];

const SOURCES: Record<
  Source,
  { name: string; product: string; credit: string; about: React.ReactNode }
> = {
  chirps: {
    name: "CHIRPS",
    product: "CHIRPS preliminary",
    credit: "Observed: CHIRPS, Climate Hazards Center (UCSB)",
    about: (
      <p>
        CHIRPS blends satellite rainfall estimates with station observations at
        about 5 km. The preliminary dekad is published a few days after it ends;
        percent of normal compares it with the 1991–2020 average of the same
        dekad.
      </p>
    ),
  },
  tamsat: {
    name: "TAMSAT",
    product: "TAMSAT v3.1",
    credit: "Observed: TAMSAT, University of Reading",
    about: (
      <p>
        TAMSAT estimates rainfall over Africa from Meteosat thermal-infrared
        imagery, calibrated against rain gauges, at about 4 km. It is a second,
        independent estimate: where the two agree the picture is firm, where
        they differ the observations are uncertain.
      </p>
    ),
  },
  arc2: {
    name: "ARC 2.0",
    product: "ARC 2.0 daily totals",
    credit: "Observed: ARC 2.0, NOAA Climate Prediction Center",
    about: (
      <p>
        ARC 2.0, NOAA&apos;s African Rainfall Climatology, merges Meteosat
        infrared estimates with daily rain-gauge reports at 0.1° (about 11 km).
        Its dekad here is the sum of the dekad&apos;s daily files; it is shown
        once every day of the dekad is published.
      </p>
    ),
  },
  rfe2: {
    name: "RFE 2.0",
    product: "RFE 2.0 daily totals",
    credit: "Observed: RFE 2.0, NOAA Climate Prediction Center",
    about: (
      <p>
        RFE 2.0, NOAA&apos;s African Rainfall Estimate, merges Meteosat
        infrared, passive-microwave and rain-gauge data at 0.1° (about 11 km).
        Its dekad here is the sum of the dekad&apos;s daily files; it is shown
        once every day of the dekad is published.
      </p>
    ),
  },
  imerg: {
    name: "GPM IMERG",
    product: "GPM IMERG Late Run daily totals",
    credit: "Observed: GPM IMERG, NASA GES DISC",
    about: (
      <p>
        GPM IMERG combines the microwave and infrared satellites of the Global
        Precipitation Measurement constellation at 0.1° (about 11 km). The Late
        Run is out about a day after each day, without the monthly gauge
        correction of the later Final Run. Its dekad here is the sum of the
        dekad&apos;s daily files.
      </p>
    ),
  },
};

function sourceOf(dekad: Dekad): Source {
  return dekad.source && dekad.source in SOURCES ? dekad.source : "chirps";
}

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
        credit={SOURCES[sourceOf(dekad)].credit}
        hover={(name) => {
          const row = dekad.countries.find((c) => c.country === name);
          if (!row) return null;
          return product === "percent" && row.percent_of_normal != null
            ? `${row.percent_of_normal}% of normal`
            : `Mean ${num(row.mean_mm)} mm · up to ${num(row.max_mm, 0)} mm`;
        }}
      >
        <div className="map-switch" data-map-reserve="top left">
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
        <div className="map-legend-corner light" data-map-reserve="bottom left">
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

function Compare({
  dekad,
  estimates,
}: {
  dekad: Dekad;
  estimates?: Estimate[];
}) {
  const rows = ORDER.map((key) => {
    const entry = estimates?.find((estimate) => estimate.source === key);
    const latest = key === sourceOf(dekad) ? dekad : entry?.latest;
    return { key, latest: latest ?? undefined, entry };
  });
  const held = rows.filter((row) => row.latest);
  const same = held.every((row) => row.latest?.dekad === dekad.dekad);
  return (
    <Card
      title="The estimates compared"
      subtitle={
        held.length < 2
          ? "No other estimate is downloaded yet to compare with."
          : same
            ? "Each estimate of the same dekad."
            : "The latest dekad of each; not every estimate covers the same dekad."
      }
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Estimate</th>
              <th>Dekad</th>
              <th className="num">Mean (mm)</th>
              <th className="num">Below 1 mm</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, latest, entry }) => (
              <tr key={key}>
                <td className="strong">{SOURCES[key].name}</td>
                {latest ? (
                  <>
                    <td>{shortPeriod(latest.start, latest.end)}</td>
                    <td className="num">{num(latest.region.mean_mm)}</td>
                    <td className="num">
                      {Math.round(latest.region.dry_fraction * 100)}%
                    </td>
                  </>
                ) : (
                  <td colSpan={3} style={{ color: "var(--muted)" }}>
                    {entry?.last_check?.status === "failed"
                      ? sentence(entry.last_check.reason ?? "Not available")
                      : "Not downloaded yet"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Body({
  dekad,
  history,
  estimates,
}: {
  dekad: Dekad;
  history?: Dekad[];
  estimates?: Estimate[];
}) {
  const rows = [...dekad.countries].sort((a, b) => b.mean_mm - a.mean_mm);
  const percent = dekad.percent_of_normal.status === "available";
  const source = SOURCES[sourceOf(dekad)];
  return (
    <>
      <div className="stats">
        <Stat
          label="Dekad"
          value={shortPeriod(dekad.start, dekad.end)}
          hint={`${dekad.start.slice(0, 4)} · ${source.product}`}
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
          <Compare dekad={dekad} estimates={estimates} />
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
          <Card title={`About ${source.name}`}>
            {source.about}
            <p>
              Forecasts are verified against the daily CHIRPS files, and also
              compared with ARC 2.0, RFE 2.0 and GPM IMERG, see{" "}
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

function initialSource(): Source {
  if (typeof window === "undefined") return "chirps";
  const asked = new URLSearchParams(window.location.search).get("source");
  return ORDER.find((key) => key === asked) ?? "chirps";
}

export default function Monitoring() {
  const [source, setSource] = useState<Source>("chirps");
  useEffect(() => setSource(initialSource()), []);
  const latest = useApi<Dekad>(`/monitoring/dekads/latest?source=${source}`);
  const history = useApi<Dekad[]>(`/monitoring/dekads?source=${source}`);
  const estimates = useApi<Estimate[]>("/monitoring/estimates");
  const [actor] = useActor();
  const { operation, error, running, start } = useOperation(() => {
    latest.reload();
    history.reload();
    estimates.reload();
  });
  const check = () => start("update_chirps", actor || "Forecaster");
  const choose = (next: Source) => {
    setSource(next);
    const url = new URL(window.location.href);
    if (next === "chirps") url.searchParams.delete("source");
    else url.searchParams.set("source", next);
    window.history.replaceState(null, "", url);
  };
  const dekad =
    latest.data && sourceOf(latest.data) === source ? latest.data : undefined;
  const lastCheck = estimates.data?.find(
    (e) => e.source === source,
  )?.last_check;
  const outcome = operation?.messages
    .map((m) => m.text)
    .filter((text) => !/^(Started|Finished|Looking for)/.test(text))
    .join(". ");
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Rainfall Monitoring"
          crumbs={[{ label: "Monitoring" }]}
          subtitle="Observed rainfall over the Greater Horn of Africa, dekad by dekad, from five satellite estimates: CHIRPS, TAMSAT, ARC 2.0, RFE 2.0 and GPM IMERG."
          actions={
            <Button variant="amber" disabled={running} onClick={check}>
              <RefreshCw size={17} className={running ? "spin" : undefined} />
              {running ? "Checking…" : "Check for new dekads"}
            </Button>
          }
        />
        <div className="source-bar">
          <div
            className="segmented light"
            role="group"
            aria-label="Rainfall estimate"
          >
            {ORDER.map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={source === key}
                onClick={() => choose(key)}
              >
                {SOURCES[key].name}
              </button>
            ))}
          </div>
          {dekad && (
            <p className="source-bar-note">
              Latest dekad {period(dekad.start, dekad.end)} ·{" "}
              {SOURCES[source].product}
            </p>
          )}
        </div>
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
              {operation.status === "complete" ? outcome : operation.error}
            </Notice>
          )}
        {latest.loading && !dekad && <Skeleton height={520} />}
        {latest.status === 404 && (
          <EmptyState
            title={`No ${SOURCES[source].name} dekad downloaded yet`}
            action={
              <Button variant="amber" disabled={running} onClick={check}>
                Download the newest dekads
              </Button>
            }
          >
            <p style={{ margin: 0 }}>
              {lastCheck?.status === "failed"
                ? `Last check ${dateTime(lastCheck.checked_at)}: ${sentence(lastCheck.reason ?? "it failed")}`
                : "The newest dekad of each estimate is downloaded by the weekly cycle and the daily task, or now with the button."}
            </p>
          </EmptyState>
        )}
        {latest.error && latest.status !== 404 && (
          <ErrorState message={latest.error} retry={latest.reload} />
        )}
        {dekad && (
          <Body
            dekad={dekad}
            history={history.data}
            estimates={estimates.data}
          />
        )}
      </div>
    </div>
  );
}
