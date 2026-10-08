"use client";
/** Pieces shared by the operational forecast views. */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CalendarClock, CloudOff, Download, ShieldAlert } from "lucide-react";
import Chart from "@/components/chart";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  KeyValues,
  LinkButton,
  ModelStatus,
  SeriesSwatch,
  SyntheticBadge,
  Table,
  TestStatus,
} from "@/components/ui";
import { useApp } from "@/components/shell";
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
import type { SeriesKey } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  CountryRow,
  ForecastDetail,
  Metrics,
  Variant,
  Verification,
} from "@/types/operational";

export const VARIANTS: Variant[] = ["raw", "mbc", "hybrid"];

/** The forecast named in the URL (?id=), else the latest one. */
export function useForecast(id?: string) {
  return useApi<ForecastDetail>(id ? "/forecasts/" + id : "/forecasts/latest");
}

export function NoForecast() {
  return (
    <Card>
      <EmptyState
        icon={<CloudOff size={30} />}
        title="No operational forecast yet"
        action={
          <LinkButton href="/data/runs" variant="primary">
            Go to forecast runs
          </LinkButton>
        }
      >
        A forecast appears here after a run on ECMWF S2S input (or an imported
        HPC product package). Nothing is shown until the backend has produced
        one.
      </EmptyState>
    </Card>
  );
}

export function ForecastBadges({ detail }: { detail: ForecastDetail }) {
  return (
    <>
      <ModelStatus status={detail.model_status} />
      <TestStatus status={detail.model.test_status} />
      {detail.synthetic && <SyntheticBadge />}
      {detail.protected_test_period && (
        <Badge tone="warning" icon={<ShieldAlert size={13} />}>
          2022–2024 test period · display only
        </Badge>
      )}
      <Badge
        tone={detail.verification_status === "available" ? "good" : "neutral"}
      >
        {detail.verification_status === "available"
          ? "Verified against CHIRPS"
          : "Not yet verified"}
      </Badge>
    </>
  );
}

export function forecastSubtitle(detail: ForecastDetail) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2">
      <CalendarClock size={16} className="text-subtle" />
      Initialised {day(detail.initialization)} 00 UTC · valid{" "}
      {validDays(detail.valid_start, detail.valid_end)} (Days 8–14)
    </span>
  );
}

export function ForecastFacts({ detail }: { detail: ForecastDetail }) {
  const p = detail.provenance;
  return (
    <KeyValues
      items={[
        ["Initialization", `${day(detail.initialization)} 00 UTC`],
        [
          "Valid period",
          `${validDays(detail.valid_start, detail.valid_end)} · Days 8–14`,
        ],
        ["Lead", "Week-2: forecast hours 168–336"],
        ["Baseline", detail.baseline],
        ["ML method", `${detail.algorithm} residual on the MBC baseline`],
        [
          "Feature family",
          `${detail.family} · ${detail.model.feature_count ?? "?"} features`,
        ],
        ["Hybrid rainfall", "max(MBC + predicted residual, 0)"],
        ["Model", `${detail.model_id} · ${detail.model_version}`],
        ["Ensemble", `${p.ensemble_members} perturbed members`],
        ["Input", detail.input_label],
        ["Generated", dateTime(detail.generation_time)],
        ["Forecast ID", <code key="id">{detail.forecast_id}</code>],
      ]}
    />
  );
}

export function mapUrl(detail: ForecastDetail, layer: string) {
  return `/api/forecasts/${detail.forecast_id}/map?layer=${layer}`;
}

export function CountryTable({ rows }: { rows: CountryRow[] }) {
  return (
    <Table
      head={[
        "Country",
        <span key="raw" className="inline-flex items-center gap-1.5">
          <SeriesSwatch series="raw" /> Raw mean
        </span>,
        <span key="mbc" className="inline-flex items-center gap-1.5">
          <SeriesSwatch series="mbc" /> MBC mean
        </span>,
        <span key="hybrid" className="inline-flex items-center gap-1.5">
          <SeriesSwatch series="hybrid" /> MBC + AI mean
        </span>,
        "Median",
        "Min",
        "Max",
        "Cells",
      ]}
    >
      {rows.map((row) => (
        <tr key={row.country} className="tabular">
          <td>
            <Link
              className="font-medium hover:underline"
              href={"/countries/" + countrySlug(row.country)}
            >
              {row.country}
            </Link>
          </td>
          <td>{num(row.raw.mean_mm)}</td>
          <td>{num(row.mbc.mean_mm)}</td>
          <td className="font-medium">{num(row.hybrid.mean_mm)}</td>
          <td>{num(row.hybrid.median_mm)}</td>
          <td>{num(row.hybrid.min_mm)}</td>
          <td>{num(row.hybrid.max_mm)}</td>
          <td className="text-muted-foreground">
            {row.cell_count.toLocaleString("en-GB")}
          </td>
        </tr>
      ))}
    </Table>
  );
}

function useSeriesColors() {
  const { dark } = useApp();
  const [colors, setColors] = useState<Record<SeriesKey, string>>({
    raw: "#2a78d6",
    mbc: "#eb6834",
    hybrid: "#1baf7a",
  });
  useEffect(() => {
    const style = getComputedStyle(document.documentElement);
    setColors({
      raw: style.getPropertyValue("--series-raw").trim(),
      mbc: style.getPropertyValue("--series-mbc").trim(),
      hybrid: style.getPropertyValue("--series-hybrid").trim(),
    });
  }, [dark]);
  return { colors, dark };
}

/** Country means of raw, MBC and hybrid rainfall (mm/week) as grouped bars. */
export function CountryChart({ rows }: { rows: CountryRow[] }) {
  const { colors, dark } = useSeriesColors();
  const option = useMemo(() => {
    const sorted = [...rows].sort(
      (a, b) => a.hybrid.mean_mm - b.hybrid.mean_mm,
    );
    const ink = dark ? "#c3c2b7" : "#52514e";
    const grid = dark ? "#2c2c2a" : "#e1e0d9";
    return {
      grid: { left: 92, right: 24, top: 36, bottom: 28 },
      legend: {
        top: 0,
        left: 0,
        itemWidth: 10,
        itemHeight: 10,
        icon: "circle",
        textStyle: { color: ink },
      },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        valueFormatter: (value: unknown) => num(Number(value)) + " mm",
      },
      xAxis: {
        type: "value" as const,
        name: "mm/week",
        nameTextStyle: { color: ink },
        axisLabel: { color: ink },
        splitLine: { lineStyle: { color: grid } },
      },
      yAxis: {
        type: "category" as const,
        data: sorted.map((row) => row.country),
        axisLabel: { color: ink },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: grid } },
      },
      series: (["raw", "mbc", "hybrid"] as SeriesKey[]).map((key) => ({
        name: SERIES[key].label,
        type: "bar" as const,
        barMaxWidth: 9,
        barGap: "25%",
        itemStyle: { color: colors[key], borderRadius: [0, 4, 4, 0] },
        data: sorted.map((row) => row[key].mean_mm),
      })),
    };
  }, [rows, colors, dark]);
  return (
    <Chart
      option={option}
      height={Math.max(320, rows.length * 36 + 70)}
      label="Country mean Week-2 rainfall: raw ECMWF, MBC and MBC + AI (table below)"
    />
  );
}

export function MetricsTable({
  metrics,
}: {
  metrics: Partial<Record<Variant, Metrics>>;
}) {
  return (
    <Table head={["Forecast", "MAE", "RMSE", "Bias", "Pearson r", "Cells"]}>
      {VARIANTS.filter((v) => metrics[v]).map((variant) => {
        const m = metrics[variant] as Metrics;
        return (
          <tr key={variant} className="tabular">
            <td>
              <span className="inline-flex items-center gap-2 font-medium">
                <SeriesSwatch series={variant} />
                {SERIES[variant].label}
              </span>
            </td>
            <td>{num(m.mae, 2)} mm</td>
            <td>{num(m.rmse, 2)} mm</td>
            <td>{signed(m.bias, 2)} mm</td>
            <td>{num(m.correlation, 3)}</td>
            <td className="text-muted-foreground">
              {m.sample_count.toLocaleString("en-GB")}
              {m.cases ? ` · ${m.cases} forecasts` : ""}
            </td>
          </tr>
        );
      })}
    </Table>
  );
}

export function VerificationCard({
  verification,
  forecastId,
}: {
  verification: Verification;
  forecastId: string;
}) {
  return (
    <Card>
      <CardHeader
        title="Verification against CHIRPS"
        description={
          verification.status === "available"
            ? `Spatial metrics over the domain · ${verification.season} · ${verification.use}`
            : "Metrics appear once the observed Week-2 total for this window is supplied"
        }
      />
      <CardContent>
        {verification.status === "available" && verification.domain ? (
          <MetricsTable metrics={verification.domain} />
        ) : (
          <div className="grid gap-2 text-muted-foreground">
            <p className="m-0">{verification.reason}</p>
            <p className="m-0 text-[0.9rem]">Needs: {verification.required}</p>
            <div>
              <LinkButton href={"/verification?id=" + forecastId}>
                Add observations
              </LinkButton>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function Downloads({ detail }: { detail: ForecastDetail }) {
  const names: [string, string][] = [
    ["manifest.json", "Package manifest (checksums, labels)"],
    ["forecast.nc", "Gridded fields: raw, MBC, residual, hybrid (NetCDF4)"],
    ["countries.csv", "Country statistics (CSV)"],
    ["verification.json", "Verification metrics"],
    ["interpretation_inputs.json", "Technical inputs for the bulletin"],
    ["provenance.json", "Provenance record"],
    ["model.json", "Model metadata"],
    ["maps/hybrid.png", "Map: MBC + AI"],
    ["maps/mbc.png", "Map: MBC"],
    ["maps/raw.png", "Map: raw ECMWF"],
    ["maps/residual.png", "Map: CatBoost residual"],
  ];
  return (
    <ul className="m-0 grid min-w-0 grid-cols-1 list-none gap-1 p-0">
      {names.map(([name, label]) => (
        <li key={name}>
          <a
            className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
            href={`/api/forecasts/${detail.forecast_id}/package/${name}`}
          >
            <span className="min-w-0">
              <span className="block truncate font-medium">{label}</span>
              <code className="break-all text-[0.8rem] text-subtle">
                {name}
              </code>
            </span>
            <Download size={15} className="shrink-0 text-subtle" />
          </a>
        </li>
      ))}
    </ul>
  );
}

export function ProvenanceList({ detail }: { detail: ForecastDetail }) {
  const p = detail.provenance;
  const overrides = Object.entries(p.configuration_overrides ?? {});
  return (
    <>
      <KeyValues
        items={[
          [
            "Model checksum",
            <code key="m">{shortHash(p.model_checksum, 16)}</code>,
          ],
          [
            "MBC artifact checksum",
            <code key="b">{shortHash(p.mbc_artifact_checksum, 16)}</code>,
          ],
          [
            "Feature schema",
            <span key="f">
              {p.feature_schema} ·{" "}
              <code>{shortHash(p.feature_schema_checksum, 12)}</code>
            </span>,
          ],
          [
            "Grid",
            `${p.grid_definition.shape.join(" × ")} (latitude × longitude)`,
          ],
          [
            "Domain",
            `${p.domain_definition.cells.toLocaleString("en-GB")} cells · ${p.domain_definition.name}`,
          ],
          ["MBC month", String(p.mbc_month)],
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
      {overrides.length > 0 && (
        <div className="mt-4 rounded-lg border border-status-serious/50 bg-status-serious/10 px-4 py-3 text-status-serious-ink">
          <strong>Configuration overridden for this run:</strong>
          <ul className="mb-0 mt-1 pl-5">
            {overrides.map(([key, value]) => (
              <li key={key}>
                <code>{key}</code> = {JSON.stringify(value.value)} —{" "}
                {value.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <details className="mt-4">
        <summary className="cursor-pointer font-medium text-muted-foreground">
          Full provenance record
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded-lg bg-muted p-3 text-[0.8rem]">
          {JSON.stringify(p, null, 2)}
        </pre>
      </details>
    </>
  );
}
