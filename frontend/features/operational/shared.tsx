"use client";
/** Pieces shared by the forecast pages. */
import Link from "next/link";
import { useMemo } from "react";
import { Download } from "lucide-react";
import Chart from "@/components/chart";
import {
  Card,
  EmptyState,
  InProgress,
  KeyValues,
  LinkButton,
  Notice,
  Status,
} from "@/components/ui";
import { countrySlug } from "@/features/routes";
import { SERIES, dateTime, day, num, signed, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  CountryRow,
  ForecastDetail,
  ForecastRun,
  Metrics,
  Variant,
} from "@/types/operational";

export const VARIANTS: Variant[] = ["raw", "mbc", "hybrid"];

export const LAYER_TEXT: Record<Variant, { title: string; method: string }> = {
  raw: {
    title: "Raw ECMWF",
    method:
      "The ECMWF ensemble mean of Week-2 total rainfall: 50 perturbed members, accumulated between forecast hours 168 and 336, averaged to the 1.5° training grid and interpolated to the 0.05° ICPAC grid.",
  },
  mbc: {
    title: "MBC",
    method:
      "Multiplicative bias correction: the ECMWF ensemble mean times the locked 2005–2021 ratio of CHIRPS to ECMWF rainfall for the same calendar month and grid cell. On the 2022–2024 independent test it reduced RMSE by 11.2% against raw ECMWF.",
  },
  hybrid: {
    title: "MBC + AI/ML",
    method:
      "The MBC forecast plus a CatBoost correction learned from 37 predictors (ensemble rainfall and atmospheric fields at 850, 700, 500 and 200 hPa), added to MBC and kept at or above zero.",
  },
};

/** The forecast named in the URL (?id=), else the latest one. */
export function useForecast(id?: string) {
  return useApi<ForecastDetail>(id ? "/forecasts/" + id : "/forecasts/latest");
}

export function layersOf(run: Pick<ForecastRun, "layers">): Variant[] {
  const layers = run.layers ?? ["hybrid", "mbc", "raw"];
  return VARIANTS.filter((v) => layers.includes(v));
}

export function primaryOf(run: Pick<ForecastRun, "primary_layer">): Variant {
  return run.primary_layer ?? "hybrid";
}

export function methodName(run: Pick<ForecastRun, "primary_layer">): string {
  return primaryOf(run) === "mbc"
    ? "ECMWF ensemble + MBC"
    : "MBC + AI/ML hybrid";
}

export function NoForecast() {
  return (
    <EmptyState
      title="No forecast has been issued yet"
      action={
        <LinkButton href="/data/runs" variant="amber">
          Run the weekly forecast
        </LinkButton>
      }
    >
      <p style={{ margin: 0 }}>
        The first forecast appears here once the latest ECMWF ensemble has been
        downloaded and processed. Operations runs both steps in one go.
      </p>
    </EmptyState>
  );
}

/** A model's registry status in words. */
export function modelState(status?: string | null): string {
  if (status === "production") return "production model";
  if (status === "candidate") return "candidate model, under evaluation";
  return status ? `${status} model` : "registered model";
}

export function forecastFacts(detail: ForecastRun): string[] {
  return [
    `Valid ${validDays(detail.valid_start, detail.valid_end)}`,
    `ECMWF run ${day(detail.initialization)}, 00 UTC`,
    methodName(detail),
  ];
}

export function ProductStatusList({ detail }: { detail: ForecastRun }) {
  const products = detail.products ?? {};
  return (
    <div className="grid-3">
      {VARIANTS.map((variant) => {
        const state =
          products[variant]?.status ??
          (layersOf(detail).includes(variant) ? "available" : "in_progress");
        return state === "available" ? (
          <div
            key={variant}
            className="pending-card"
            style={{ borderStyle: "solid", background: "#fff" }}
          >
            <Status tone="ok">Available</Status>
            <h3>{LAYER_TEXT[variant].title}</h3>
            <p>{LAYER_TEXT[variant].method}</p>
          </div>
        ) : (
          <InProgress key={variant} title={LAYER_TEXT[variant].title}>
            {products[variant]?.reason
              ? `Waiting for ${products[variant]?.reason}.`
              : "Its inputs are not available yet."}
          </InProgress>
        );
      })}
    </div>
  );
}

export function ForecastFacts({ detail }: { detail: ForecastDetail }) {
  const p = detail.provenance;
  return (
    <KeyValues
      items={[
        ["ECMWF run", `${day(detail.initialization)}, 00 UTC`],
        [
          "Valid period",
          `${validDays(detail.valid_start, detail.valid_end)} (days 8–14)`,
        ],
        ["Lead time", "Week-2: forecast hours 168–336"],
        ["Issued from", methodName(detail)],
        ["Ensemble", `${p.ensemble_members} perturbed members`],
        ["Input", detail.input_label],
        [
          "Model",
          `${detail.model?.model_name ?? "Registered model"} (${modelState(detail.model_status)})`,
        ],
        ["Issued", dateTime(detail.generation_time)],
      ]}
    />
  );
}

/** A bulletin-style map image of a layer (optionally one country). */
export function mapUrl(
  detail: ForecastDetail,
  layer: string,
  country?: string,
) {
  const path =
    detail.maps?.[layer] ??
    `/forecasts/${detail.forecast_id}/map?layer=${layer}`;
  return (
    "/api" + path + (country ? `&country=${encodeURIComponent(country)}` : "")
  );
}

export function CountryTable({
  rows,
  layers,
}: {
  rows: CountryRow[];
  layers: Variant[];
}) {
  const main = layers.includes("hybrid") ? "hybrid" : "mbc";
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Country</th>
            {layers.map((layer) => (
              <th key={layer} className="num">
                {SERIES[layer].label} mean
              </th>
            ))}
            <th className="num">Median</th>
            <th className="num">Min</th>
            <th className="num">Max</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const stats = row[main];
            return (
              <tr key={row.country}>
                <td className="strong">
                  <Link href={"/countries/" + countrySlug(row.country)}>
                    {row.country}
                  </Link>
                </td>
                {layers.map((layer) => (
                  <td
                    key={layer}
                    className={layer === main ? "num strong" : "num"}
                  >
                    {num(row[layer]?.mean_mm)}
                  </td>
                ))}
                <td className="num">{num(stats?.median_mm)}</td>
                <td className="num">{num(stats?.min_mm)}</td>
                <td className="num">{num(stats?.max_mm)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const COLOURS: Record<Variant, string> = {
  raw: "#2a78d6",
  mbc: "#e0802f",
  hybrid: "#1baf7a",
};

/** Country means (mm/week) as grouped horizontal bars. */
export function CountryChart({
  rows,
  layers,
}: {
  rows: CountryRow[];
  layers: Variant[];
}) {
  const option = useMemo(() => {
    const main = layers.includes("hybrid") ? "hybrid" : "mbc";
    const sorted = [...rows].sort(
      (a, b) => (a[main]?.mean_mm ?? 0) - (b[main]?.mean_mm ?? 0),
    );
    return {
      textStyle: { fontFamily: "Open Sans, Arial, sans-serif" },
      grid: { left: 96, right: 28, top: 40, bottom: 30 },
      legend: {
        top: 0,
        left: 0,
        itemWidth: 12,
        itemHeight: 12,
        icon: "roundRect",
        textStyle: { color: "#474c51" },
      },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        valueFormatter: (value: unknown) => num(Number(value)) + " mm",
      },
      xAxis: {
        type: "value" as const,
        name: "mm / week",
        nameTextStyle: { color: "#7d848b" },
        axisLabel: { color: "#7d848b" },
        splitLine: { lineStyle: { color: "#e4e8eb" } },
      },
      yAxis: {
        type: "category" as const,
        data: sorted.map((row) => row.country),
        axisLabel: { color: "#212529", fontWeight: 600 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cfd6db" } },
      },
      series: layers.map((key) => ({
        name: SERIES[key].label,
        type: "bar" as const,
        barMaxWidth: 10,
        barGap: "30%",
        itemStyle: { color: COLOURS[key], borderRadius: [0, 4, 4, 0] },
        data: sorted.map((row) => row[key]?.mean_mm ?? null),
      })),
    };
  }, [rows, layers]);
  return (
    <Chart
      option={option}
      height={Math.max(340, rows.length * 38 + 80)}
      label="Country mean Week-2 rainfall by forecast layer (values in the table)"
    />
  );
}

export function MetricsTable({
  metrics,
}: {
  metrics: Partial<Record<Variant, Metrics>>;
}) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Forecast</th>
            <th className="num">MAE</th>
            <th className="num">RMSE</th>
            <th className="num">Bias</th>
            <th className="num">Pearson r</th>
            <th className="num">Cells</th>
          </tr>
        </thead>
        <tbody>
          {VARIANTS.filter((v) => metrics[v]).map((variant) => {
            const m = metrics[variant] as Metrics;
            return (
              <tr key={variant}>
                <td className="strong">
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 3,
                        background: COLOURS[variant],
                      }}
                    />
                    {SERIES[variant].label}
                  </span>
                </td>
                <td className="num">{num(m.mae, 2)} mm</td>
                <td className="num">{num(m.rmse, 2)} mm</td>
                <td className="num">{signed(m.bias, 2)} mm</td>
                <td className="num">{num(m.correlation, 3)}</td>
                <td className="num" style={{ color: "var(--muted)" }}>
                  {m.sample_count.toLocaleString("en-GB")}
                  {m.cases ? ` · ${m.cases} forecasts` : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function VerificationSummary({ detail }: { detail: ForecastDetail }) {
  const verification = detail.verification;
  if (verification.status === "available" && verification.domain)
    return (
      <>
        <p style={{ marginTop: 0 }}>
          Verified against CHIRPS daily rainfall. Scores over the eleven member
          states for this single week; they do not by themselves establish
          forecast skill.
        </p>
        <MetricsTable metrics={verification.domain} />
      </>
    );
  return (
    <Notice title="Not verified yet.">
      CHIRPS covers the window {validDays(detail.valid_start, detail.valid_end)}{" "}
      about two days after it ends; the forecast is then verified automatically
      by the weekly cycle in <Link href="/data/runs">Operations</Link>.
    </Notice>
  );
}

const FILES: [string, string, string][] = [
  ["forecast.nc", "Gridded forecast", "NetCDF, every layer on the 0.05° grid"],
  ["countries.csv", "Country statistics", "Spreadsheet of the country figures"],
  ["maps/mbc.png", "Map: MBC", "Image"],
  ["maps/hybrid.png", "Map: MBC + AI/ML", "Image"],
  ["maps/raw.png", "Map: raw ECMWF", "Image"],
];

export function Downloads({ detail }: { detail: ForecastDetail }) {
  const available = new Set(Object.keys(detail.files ?? {}));
  return (
    <ul className="download-list">
      {FILES.filter(([name]) => available.has(name)).map(
        ([name, label, kind]) => (
          <li key={name}>
            <a href={`/api/forecasts/${detail.forecast_id}/package/${name}`}>
              <span>
                <strong>{label}</strong>
                <small>{kind}</small>
              </span>
              <Download size={17} aria-hidden />
            </a>
          </li>
        ),
      )}
    </ul>
  );
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** How the forecast was made, in words. */
export function ProvenanceList({ detail }: { detail: ForecastDetail }) {
  const p = detail.provenance;
  return (
    <KeyValues
      items={[
        [
          "Grid",
          `${p.grid_definition.shape.join(" × ")} cells at 0.05° (about 5 km)`,
        ],
        [
          "Area",
          `${p.domain_definition.cells.toLocaleString("en-GB")} land cells over the eleven member states`,
        ],
        [
          "Ensemble",
          `${p.ensemble_members} perturbed members of the ECMWF ensemble`,
        ],
        [
          "Bias correction",
          `Ratios for ${MONTHS[(p.mbc_month ?? 1) - 1]}, from 2005–2021 CHIRPS and ECMWF rainfall`,
        ],
        ["Input", detail.input_label],
      ]}
    />
  );
}

export function NotesCard({ detail }: { detail: ForecastDetail }) {
  if (!detail.notes?.length) return null;
  return (
    <Card title="Notes on this forecast">
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        {detail.notes.map((note) => (
          <li key={note} style={{ marginBottom: 6 }}>
            {note}
          </li>
        ))}
      </ul>
    </Card>
  );
}
