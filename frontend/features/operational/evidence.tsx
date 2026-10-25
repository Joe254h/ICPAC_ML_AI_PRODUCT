"use client";
/** The frozen experimental verification of the pre-refit model (independent 2022–2024). */
import { useMemo, useState } from "react";
import Chart from "@/components/chart";
import {
  Card,
  ErrorState,
  KeyValues,
  Notice,
  PageBanner,
  Skeleton,
  Tabs,
} from "@/components/ui";
import { num, signed } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  EvidenceScore,
  ExperimentalEvidence,
  RocCurve,
} from "@/types/operational";

const COLOURS: Record<string, string> = {
  RawECMWF: "#2a78d6",
  TrainingClimatology: "#8a939b",
  MBC: "#e0802f",
  LightGBM: "#7a5cc4",
  CatBoost: "#1baf7a",
  GlobalAlpha075: "#128a8a",
  MAMProtected: "#b0487a",
  ECMWF: "#2a78d6",
};
/** Column headings where seven models share a table. */
const SHORT: Record<string, string> = {
  RawECMWF: "Raw",
  TrainingClimatology: "Climatology",
  MBC: "MBC",
  LightGBM: "LightGBM",
  CatBoost: "CatBoost",
  GlobalAlpha075: "Alpha 0.75",
  MAMProtected: "MAM-protected",
};
const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const AXIS = {
  axisLabel: { color: "#212529" },
  splitLine: { lineStyle: { color: "#e8ecef" } },
};

type Tab =
  | "overview"
  | "time"
  | "countries"
  | "events"
  | "roc"
  | "ensemble"
  | "uncertainty"
  | "maps";

function Swatch({ model }: { model: string }) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: 3,
        marginRight: 8,
        background: COLOURS[model] ?? "#999",
      }}
    />
  );
}

function best(items: EvidenceScore[], key: "rmse" | "mae"): string {
  return [...items].sort((a, b) => a[key] - b[key])[0]?.model ?? "";
}

function ScoreTable({
  items,
  skill = false,
}: {
  items: EvidenceScore[];
  skill?: boolean;
}) {
  const lowest = best(items, "rmse");
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Model</th>
            <th className="num">RMSE</th>
            <th className="num">MAE</th>
            <th className="num">Bias</th>
            <th className="num">Pearson r</th>
            <th className="num">Anomaly corr.</th>
            {skill && <th className="num">Skill vs raw</th>}
            {skill && <th className="num">Skill vs MBC</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.model}>
              <td className="strong">
                <Swatch model={s.model} />
                {s.label}
              </td>
              <td
                className="num"
                style={s.model === lowest ? { fontWeight: 700 } : undefined}
              >
                {num(s.rmse, 3)}
              </td>
              <td className="num">{num(s.mae, 3)}</td>
              <td className="num">{signed(s.bias, 3)}</td>
              <td className="num">{num(s.pearson_r, 3)}</td>
              <td className="num">{num(s.anomaly_correlation, 3)}</td>
              {skill && (
                <td className="num">
                  {s.model === "RawECMWF"
                    ? "—"
                    : `${num((s.skill_vs_raw ?? 0) * 100, 2)}%`}
                </td>
              )}
              {skill && (
                <td className="num">
                  {s.model === "MBC"
                    ? "—"
                    : `${num((s.skill_vs_mbc ?? 0) * 100, 2)}%`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Groups (rows) × models (columns) for one score. */
function Matrix({
  groups,
  metric,
  label,
  names,
}: {
  groups: Record<string, EvidenceScore[]>;
  metric: "rmse" | "mae" | "bias";
  label: string;
  names?: (group: string) => string;
}) {
  const entries = Object.entries(groups);
  const models = entries[0]?.[1] ?? [];
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>{label}</th>
            {models.map((m) => (
              <th key={m.model} className="num" title={m.label}>
                {SHORT[m.model] ?? m.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(([group, items]) => {
            const lowest = metric === "bias" ? "" : best(items, metric);
            return (
              <tr key={group}>
                <td className="strong">{names ? names(group) : group}</td>
                {items.map((s) => (
                  <td
                    key={s.model}
                    className="num"
                    style={s.model === lowest ? { fontWeight: 700 } : undefined}
                  >
                    {metric === "bias" ? signed(s.bias, 2) : num(s[metric], 2)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Overview({ e }: { e: ExperimentalEvidence }) {
  const option = useMemo(
    () => ({
      grid: { left: 180, right: 40, top: 10, bottom: 30 },
      tooltip: { trigger: "axis" as const },
      xAxis: { type: "value" as const, min: 14, name: "mm/week", ...AXIS },
      yAxis: {
        type: "category" as const,
        data: e.regional.map((s) => s.label),
        inverse: true,
        axisLabel: { color: "#212529", fontWeight: 600 },
      },
      series: [
        {
          type: "bar" as const,
          barMaxWidth: 18,
          data: e.regional.map((s) => ({
            value: Number(s.rmse.toFixed(3)),
            itemStyle: { color: COLOURS[s.model], borderRadius: [0, 4, 4, 0] },
          })),
          label: {
            show: true,
            position: "right" as const,
            formatter: (item: { value: unknown }) =>
              Number(item.value).toFixed(3),
          },
        },
      ],
    }),
    [e],
  );
  return (
    <>
      <Card
        title="Regional scores, 551 independent cases"
        subtitle="Area-weighted over every matched cell of the eleven member states (113,285,600 cell observations). Lowest RMSE in bold."
      >
        <Chart
          option={option}
          height={300}
          label="RMSE by model over the independent 2022–2024 period (values in the table)"
        />
        <ScoreTable items={e.regional} skill />
      </Card>
      <Card
        title="Validation and independent periods"
        subtitle="Scores fall from the 2020–2021 validation to the independent 2022–2024 period: both are shown, nothing is re-tuned."
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">Validation RMSE</th>
                <th className="num">Validation MAE</th>
                <th className="num">Independent RMSE</th>
                <th className="num">Independent MAE</th>
                <th className="num">Independent anomaly corr.</th>
              </tr>
            </thead>
            <tbody>
              {e.foundational.map((f) => (
                <tr key={f.model}>
                  <td className="strong">
                    <Swatch model={f.model} />
                    {f.label}
                  </td>
                  <td className="num">{num(f.validation_rmse, 3)}</td>
                  <td className="num">{num(f.validation_mae, 3)}</td>
                  <td className="num">{num(f.independent_rmse, 3)}</td>
                  <td className="num">{num(f.independent_mae, 3)}</td>
                  <td className="num">
                    {num(f.independent_anomaly_correlation, 3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function OverTime({ e }: { e: ExperimentalEvidence }) {
  const [metric, setMetric] = useState<"rmse" | "mae" | "bias">("rmse");
  const shown = ["RawECMWF", "MBC", "CatBoost", "MAMProtected"];
  const option = useMemo(
    () => ({
      grid: { left: 60, right: 20, top: 40, bottom: 30 },
      tooltip: { trigger: "axis" as const },
      legend: { top: 0 },
      xAxis: { type: "category" as const, data: MONTHS, ...AXIS },
      yAxis: {
        type: "value" as const,
        name: metric === "bias" ? "mm/week (forecast − CHIRPS)" : "mm/week",
        scale: true,
        ...AXIS,
      },
      series: shown.map((model) => ({
        name: e.regional.find((s) => s.model === model)?.label ?? model,
        type: "line" as const,
        symbolSize: 6,
        itemStyle: { color: COLOURS[model] },
        data: MONTHS.map((_, i) => {
          const items = e.monthly[String(i + 1).padStart(2, "0")] ?? [];
          const value = items.find((s) => s.model === model)?.[metric];
          return value == null ? null : Number(value.toFixed(3));
        }),
      })),
    }),
    [e, metric],
  );
  return (
    <>
      <Tabs
        label="Score"
        value={metric}
        onChange={setMetric}
        options={[
          { value: "rmse", label: "RMSE" },
          { value: "mae", label: "MAE" },
          { value: "bias", label: "Bias" },
        ]}
      />
      <Card
        title="By initialization month"
        subtitle="Pooled exactly from the per-case sums of the 551 cases (about 46 per month). Correlation cannot be pooled from those sums, so it is not shown here."
      >
        <Chart
          option={option}
          height={320}
          label="Monthly scores of four models (values in the tables)"
        />
      </Card>
      <Card title="By year">
        <Matrix groups={e.annual} metric={metric} label="Year" />
      </Card>
      <Card
        title="By season"
        subtitle="Seasons of the initialization month: DJF December–February, MAM March–May, JJA June–August, SON September–November."
      >
        <Matrix groups={e.seasonal} metric={metric} label="Season" />
      </Card>
      <Card
        title="By year and season"
        subtitle="Twelve groups of about 46 cases: individual groups are noisy."
      >
        <Matrix
          groups={e.year_season}
          metric={metric}
          label="Year and season"
        />
      </Card>
    </>
  );
}

function Countries({ e }: { e: ExperimentalEvidence }) {
  const [metric, setMetric] = useState<"rmse" | "mae" | "bias">("rmse");
  const [country, setCountry] = useState(e.country_maps[0] ?? "Kenya");
  const gains = Object.entries(e.countries)
    .map(([name, items]) => {
      const mbc = items.find((s) => s.model === "MBC")?.rmse ?? NaN;
      const cat = items.find((s) => s.model === "CatBoost")?.rmse ?? NaN;
      return { name, gain: (1 - cat / mbc) * 100 };
    })
    .sort((a, b) => b.gain - a.gain);
  return (
    <>
      <Tabs
        label="Score"
        value={metric}
        onChange={setMetric}
        options={[
          { value: "rmse", label: "RMSE" },
          { value: "mae", label: "MAE" },
          { value: "bias", label: "Bias" },
        ]}
      />
      <Card
        title="Member states"
        subtitle="Cells of each country in the authoritative scoring mask; lowest score in bold."
      >
        <Matrix groups={e.countries} metric={metric} label="Country" />
      </Card>
      <div className="grid-2">
        <Card
          title="CatBoost against MBC"
          subtitle="RMSE reduction of the full CatBoost correction relative to MBC alone. A negative value means the correction made RMSE worse."
        >
          <KeyValues
            items={gains.map(
              (g) => [g.name, `${signed(g.gain, 2)}%`] as [string, string],
            )}
          />
        </Card>
        <Card title="Country performance map">
          <label className="field" style={{ marginBottom: 12 }}>
            Country
            <select
              value={country}
              onChange={(ev) => setCountry(ev.target.value)}
            >
              {e.country_maps.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
          <img
            src={`/api/verification/experimental/maps/country-${country.toLowerCase().replace(/ /g, "-")}`}
            alt={`Frozen 2022–2024 verification maps for ${country}`}
            style={{ width: "100%", height: "auto", borderRadius: 8 }}
          />
        </Card>
      </div>
    </>
  );
}

function Events({ e }: { e: ExperimentalEvidence }) {
  const [threshold, setThreshold] = useState(String(e.thresholds_mmweek[1]));
  const rows = e.contingency
    .filter((c) => String(c.threshold_mmweek) === threshold)
    .sort(
      (a, b) =>
        Object.keys(COLOURS).indexOf(a.model) -
        Object.keys(COLOURS).indexOf(b.model),
    );
  return (
    <>
      <Tabs
        label="Event threshold"
        value={threshold}
        onChange={setThreshold}
        options={e.thresholds_mmweek.map((t) => ({
          value: String(t),
          label: `≥ ${t} mm/week`,
        }))}
      />
      <Card
        title={`Week-2 rainfall of at least ${threshold} mm`}
        subtitle="Deterministic yes/no events from each model's rainfall, against CHIRPS, area-weighted over all cells and cases."
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">POD</th>
                <th className="num">FAR</th>
                <th className="num">CSI</th>
                <th className="num">ETS</th>
                <th className="num">HSS</th>
                <th className="num">Frequency bias</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.model}>
                  <td className="strong">
                    <Swatch model={c.model} />
                    {c.label}
                  </td>
                  <td className="num">{num(c.pod, 3)}</td>
                  <td className="num">{num(c.far, 3)}</td>
                  <td className="num">{num(c.csi, 3)}</td>
                  <td className="num">{num(c.ets, 3)}</td>
                  <td className="num">{num(c.hss, 3)}</td>
                  <td className="num">{num(c.frequency_bias, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {threshold === "100" && (
          <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
            Weeks of 100 mm or more are rarely detected by any model (POD below
            0.1): the models are not suited to extreme-rainfall warnings.
          </p>
        )}
      </Card>
      <Card
        title="By observed rainfall amount"
        subtitle="Scores within bins of the observed Week-2 total (mm/week)."
      >
        <Matrix groups={e.intensity} metric="bias" label="Observed (mm/week)" />
        <div style={{ marginTop: 18 }}>
          <Matrix
            groups={e.intensity}
            metric="rmse"
            label="Observed (mm/week)"
          />
        </div>
      </Card>
    </>
  );
}

function rocOption(curves: RocCurve[]) {
  return {
    grid: { left: 60, right: 20, top: 30, bottom: 120 },
    tooltip: { trigger: "item" as const },
    legend: { bottom: 0, left: 0, itemGap: 14 },
    xAxis: {
      type: "value" as const,
      min: 0,
      max: 1,
      name: "False alarm rate",
      nameLocation: "middle" as const,
      nameGap: 30,
      ...AXIS,
    },
    yAxis: {
      type: "value" as const,
      min: 0,
      max: 1,
      name: "Hit rate",
      ...AXIS,
    },
    series: [
      ...curves.map((c) => ({
        name: c.label,
        type: "line" as const,
        showSymbol: false,
        itemStyle: { color: COLOURS[c.model] },
        data: c.curve,
      })),
      {
        name: "No discrimination",
        type: "line" as const,
        showSymbol: false,
        lineStyle: { type: "dashed" as const, color: "#adb5bd" },
        data: [
          [0, 0],
          [1, 1],
        ],
      },
    ],
  };
}

function Discrimination({ e }: { e: ExperimentalEvidence }) {
  const [threshold, setThreshold] = useState(String(e.thresholds_mmweek[1]));
  const curves = e.deterministic_roc.filter(
    (c) => String(c.event_mmweek) === threshold,
  );
  const ensemble = e.ensemble.roc.filter(
    (c) => String(c.event_mmweek) === threshold,
  );
  return (
    <>
      <Tabs
        label="Event threshold"
        value={threshold}
        onChange={setThreshold}
        options={e.thresholds_mmweek.map((t) => ({
          value: String(t),
          label: `≥ ${t} mm/week`,
        }))}
      />
      <Notice title="Deterministic scores.">{e.deterministic_note}</Notice>
      <div className="grid-2">
        <Card
          title="Deterministic-score ROC"
          subtitle="Each model's rainfall amount used as the score; 1 mm/week bins, approximate AUC."
        >
          <Chart
            option={rocOption(curves)}
            height={460}
            label="ROC curves of the deterministic models (AUC in the table)"
          />
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="num">AUC</th>
                </tr>
              </thead>
              <tbody>
                {curves.map((c) => (
                  <tr key={c.model}>
                    <td className="strong">
                      <Swatch model={c.model} />
                      {c.label}
                    </td>
                    <td className="num">{num(c.auc, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card
          title="ECMWF ensemble-probability ROC"
          subtitle="The fraction of the ten members above the threshold: a genuine ensemble probability."
        >
          <Chart
            option={rocOption(ensemble)}
            height={460}
            label="ROC curve of the ECMWF ensemble probability"
          />
        </Card>
      </div>
    </>
  );
}

function Ensemble({ e }: { e: ExperimentalEvidence }) {
  const [threshold, setThreshold] = useState(String(e.thresholds_mmweek[1]));
  const points = e.ensemble.reliability[threshold] ?? [];
  const option = useMemo(
    () => ({
      grid: { left: 60, right: 20, top: 30, bottom: 50 },
      tooltip: { trigger: "item" as const },
      xAxis: {
        type: "value" as const,
        min: 0,
        max: 1,
        name: "Forecast probability",
        nameLocation: "middle" as const,
        nameGap: 30,
        ...AXIS,
      },
      yAxis: {
        type: "value" as const,
        min: 0,
        max: 1,
        name: "Observed frequency",
        ...AXIS,
      },
      series: [
        {
          name: "ECMWF ensemble",
          type: "line" as const,
          symbolSize: 8,
          itemStyle: { color: COLOURS.ECMWF },
          data: points.map((p) => [
            Number(p.probability.toFixed(3)),
            Number(p.observed.toFixed(3)),
          ]),
        },
        {
          name: "Perfect reliability",
          type: "line" as const,
          showSymbol: false,
          lineStyle: { type: "dashed" as const, color: "#adb5bd" },
          data: [
            [0, 0],
            [1, 1],
          ],
        },
      ],
    }),
    [points],
  );
  const crps = e.ensemble.crps;
  const brier = e.ensemble.brier.filter((b) => b.group === "global");
  return (
    <>
      <Notice title="ECMWF ensemble only.">
        {e.ensemble.label}. {e.ensemble.note} The CatBoost and MBC forecasts are
        deterministic and have no probabilistic scores.
      </Notice>
      <div className="grid-2">
        <Card
          title="CRPS"
          subtitle="Continuous ranked probability score of the ten-member Week-2 rainfall (mm/week, lower is better)."
        >
          <KeyValues
            items={crps.map(
              (c) =>
                [
                  c.group === "global" ? "All 551 cases" : c.id,
                  `${num(c.crps_mmweek, 3)} mm/week`,
                ] as [string, string],
            )}
          />
        </Card>
        <Card
          title="Brier score"
          subtitle="Ensemble probability of the event, all cells and cases (lower is better)."
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Event</th>
                  <th className="num">Brier score</th>
                  <th className="num">Mean probability</th>
                </tr>
              </thead>
              <tbody>
                {brier
                  .sort((a, b) => a.event_mmweek - b.event_mmweek)
                  .map((b) => (
                    <tr key={b.event_mmweek}>
                      <td className="strong">≥ {b.event_mmweek} mm/week</td>
                      <td className="num">{num(b.brier_score, 4)}</td>
                      <td className="num">{num(b.mean_probability, 3)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <Card
        title="Reliability"
        subtitle="Observed frequency against the ensemble probability, by probability level."
        action={
          <Tabs
            label="Event threshold"
            value={threshold}
            onChange={setThreshold}
            options={e.thresholds_mmweek.map((t) => ({
              value: String(t),
              label: `≥ ${t}`,
            }))}
          />
        }
      >
        <Chart
          option={option}
          height={360}
          label="Reliability diagram of the ECMWF ensemble probability"
        />
      </Card>
    </>
  );
}

function Uncertainty({ e }: { e: ExperimentalEvidence }) {
  return (
    <Card title="Paired block bootstrap" subtitle={e.bootstrap.method}>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Comparison</th>
              <th className="num">RMSE difference</th>
              <th className="num">95% interval</th>
              <th>Reading</th>
            </tr>
          </thead>
          <tbody>
            {e.bootstrap.items.map((b) => {
              const clear = b.low > 0 || b.high < 0;
              return (
                <tr key={b.comparator}>
                  <td className="strong">
                    {b.primary} − {b.comparator}
                  </td>
                  <td className="num">{signed(b.delta_rmse, 3)}</td>
                  <td className="num">
                    {signed(b.low, 3)} to {signed(b.high, 3)}
                  </td>
                  <td>
                    {!clear
                      ? "No clear difference"
                      : b.delta_rmse < 0
                        ? `${b.primary} lower`
                        : `${b.comparator} lower`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
        Negative differences favour the MAM-protected policy. Its interval
        against the full CatBoost correction is above zero: on the independent
        period the full correction was better, although MAM-protected was the
        policy preselected on validation.
      </p>
    </Card>
  );
}

function Maps({ e }: { e: ExperimentalEvidence }) {
  const [map, setMap] = useState(e.maps[0]?.id ?? "rmse");
  return (
    <Card
      title="Spatial verification"
      subtitle="Frozen maps of the 551-case period, official ICPAC outlines and logo."
    >
      <Tabs
        label="Map"
        value={map}
        onChange={setMap}
        options={e.maps.map((m) => ({ value: m.id, label: m.title }))}
      />
      <img
        src={`/api/verification/experimental/maps/${map}`}
        alt={e.maps.find((m) => m.id === map)?.title ?? "Verification map"}
        style={{
          width: "100%",
          height: "auto",
          marginTop: 16,
          borderRadius: 8,
        }}
      />
      <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 0 }}>
        {e.sudan.note}
      </p>
    </Card>
  );
}

export default function Evidence() {
  const evidence = useApi<ExperimentalEvidence>("/verification/experimental");
  const [tab, setTab] = useState<Tab>("overview");
  const e = evidence.data;
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Experimental Verification, 2022–2024"
          crumbs={[
            { label: "Verification", href: "/verification" },
            { label: "Experimental verification" },
          ]}
          subtitle="The frozen pre-refit models on 551 independent Week-2 reforecast cases, against CHIRPS on the 0.05° ICPAC grid. Experimental evidence, not the skill of live forecasts."
          facts={[
            "Trained 2005–2019",
            "Validated 2020–2021",
            "Independent 2022–2024",
          ]}
        />
        {evidence.loading && <Skeleton height={420} />}
        {evidence.error && (
          <ErrorState message={evidence.error} retry={evidence.reload} />
        )}
        {e && (
          <>
            <Notice title="What these scores are.">
              {String(e.scope.statement)} {String(e.scope.selection)}
            </Notice>
            <Tabs
              label="Section"
              value={tab}
              onChange={setTab}
              options={[
                { value: "overview", label: "Overview" },
                { value: "time", label: "Over time" },
                { value: "countries", label: "Countries" },
                { value: "events", label: "Rainfall events" },
                { value: "roc", label: "Discrimination" },
                { value: "ensemble", label: "ECMWF ensemble" },
                { value: "uncertainty", label: "Uncertainty" },
                { value: "maps", label: "Maps" },
              ]}
            />
            <div style={{ display: "grid", gap: 24, marginTop: 20 }}>
              {tab === "overview" && <Overview e={e} />}
              {tab === "time" && <OverTime e={e} />}
              {tab === "countries" && <Countries e={e} />}
              {tab === "events" && <Events e={e} />}
              {tab === "roc" && <Discrimination e={e} />}
              {tab === "ensemble" && <Ensemble e={e} />}
              {tab === "uncertainty" && <Uncertainty e={e} />}
              {tab === "maps" && <Maps e={e} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
