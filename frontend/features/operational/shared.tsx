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
import {
  SERIES,
  dateTime,
  day,
  num,
  shortHash,
  signed,
  validDays,
} from "@/lib/format";
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
      "The MBC forecast plus a CatBoost correction learned from 37 predictors (ensemble rainfall and atmospheric fields at 850, 700, 500 and 200 hPa): max(MBC + residual, 0).",
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
          "Model registry entry",
          `${detail.model_id} · ${detail.model_version} (${detail.model_status})`,
        ],
        ["Generated", dateTime(detail.generation_time)],
        ["Forecast ID", <code key="id">{detail.forecast_id}</code>],
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
            <th className="num">Grid cells</th>
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
                <td className="num" style={{ color: "var(--muted)" }}>
                  {row.cell_count.toLocaleString("en-GB")}
                </td>
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
          Verified against CHIRPS{" "}
          {verification.observation?.file
            ? `(${verification.observation.file})`
            : ""}
          . Spatial scores over the 205,999-cell domain for this single week;
          they do not by themselves establish forecast skill.
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

const FILES: [string, string][] = [
  ["forecast.nc", "Gridded forecast fields (NetCDF4)"],
  ["countries.csv", "Country statistics (CSV)"],
  ["maps/mbc.png", "Map: MBC"],
  ["maps/hybrid.png", "Map: MBC + AI/ML"],
  ["maps/raw.png", "Map: raw ECMWF"],
  ["maps/residual.png", "Map: AI/ML residual"],
  ["verification.json", "Verification scores"],
  ["provenance.json", "Provenance record"],
  ["manifest.json", "Package manifest with checksums"],
];

export function Downloads({ detail }: { detail: ForecastDetail }) {
  const available = new Set(Object.keys(detail.files ?? {}));
  return (
    <ul
      style={{
        listStyle: "none",
        margin: 0,
        padding: 0,
        display: "grid",
        gap: 4,
      }}
    >
      {FILES.filter(([name]) => available.has(name)).map(([name, label]) => (
        <li key={name}>
          <a
            href={`/api/forecasts/${detail.forecast_id}/package/${name}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              padding: "10px 12px",
              borderRadius: 10,
              color: "var(--ink)",
            }}
            className="hover:bg-[var(--green-50)]"
          >
            <span>
              <strong style={{ display: "block", fontWeight: 600 }}>
                {label}
              </strong>
              <code style={{ fontSize: 12.5, color: "var(--muted)" }}>
                {name}
              </code>
            </span>
            <Download
              size={17}
              style={{ color: "var(--green-700)", flex: "none" }}
            />
          </a>
        </li>
      ))}
    </ul>
  );
}

export function ProvenanceList({ detail }: { detail: ForecastDetail }) {
  const p = detail.provenance;
  return (
    <>
      <KeyValues
        items={[
          [
            "Grid",
            `${p.grid_definition.shape.join(" × ")} cells (latitude × longitude), 0.05°`,
          ],
          [
            "Domain",
            `${p.domain_definition.cells.toLocaleString("en-GB")} cells · ${p.domain_definition.name}`,
          ],
          ["MBC month", String(p.mbc_month)],
          [
            "MBC artifact",
            <code key="b">{shortHash(p.mbc_artifact_checksum, 16)}</code>,
          ],
          [
            "Input files",
            p.input_source.inputs.map((i) => i.path).join(", ") || "—",
          ],
          [
            "Software",
            `${p.software_version.package} · ${shortHash(p.software_version.git_commit, 10)}`,
          ],
        ]}
      />
      <details style={{ marginTop: 16 }}>
        <summary
          style={{
            cursor: "pointer",
            fontWeight: 600,
            color: "var(--green-700)",
          }}
        >
          Full provenance record
        </summary>
        <pre
          style={{
            marginTop: 10,
            maxHeight: 380,
            overflow: "auto",
            background: "var(--ground)",
            borderRadius: 12,
            padding: 14,
            fontSize: 12.5,
          }}
        >
          {JSON.stringify(p, null, 2)}
        </pre>
      </details>
    </>
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
