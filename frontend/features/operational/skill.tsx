"use client";
/** Verification over the weeks: the regional mean rainfall forecast and observed, the mean
 * scores with 95% confidence intervals, and the ensemble's reliability diagram and ROC
 * curve. The intervals resample whole weeks, so they widen honestly when weeks are few. */
import { useMemo, useState } from "react";
import type * as echarts from "echarts";
import Chart from "@/components/chart";
import { Disclosure, Notice, Skeleton } from "@/components/ui";
import { SERIES, day, num, signed } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  MeanInterval,
  ProbabilisticSummary,
  Variant,
  VerificationSummary,
} from "@/types/operational";

const LAYERS: Variant[] = ["raw", "mbc", "hybrid"];
/** The layers' colours (dark mode steps them through the chart theme). */
const COLOURS: Record<Variant, string> = {
  raw: "#2a78d6",
  mbc: "#e0802f",
  hybrid: "#1baf7a",
};
/** Text, axis and grid colours the chart theme maps for the dark page. */
const INK = "#212529";
const AXIS = "#7d848b";
const GRID = "#e4e8eb";
const SOURCES = [
  {
    value: "best",
    label: "Best available (CHIRPS, else ARC 2.0, else RFE 2.0)",
  },
  { value: "chirps", label: "CHIRPS" },
  { value: "arc2", label: "ARC 2.0" },
  { value: "rfe2", label: "RFE 2.0" },
];

function withInterval(
  value: MeanInterval | undefined,
  digits: number,
  unit = "",
  sign = false,
) {
  if (!value || value.mean == null) return "—";
  const show = (v: number) => (sign ? signed(v, digits) : num(v, digits));
  const main = `${show(value.mean)}${unit}`;
  return value.interval
    ? `${main} (${show(value.interval[0])} to ${show(value.interval[1])})`
    : main;
}

function percent(value: number | null | undefined, digits = 1) {
  return value == null ? "—" : `${signed(value * 100, digits)}%`;
}

function SourcePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      Observed rainfall
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {SOURCES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}

const baseOption = {
  textStyle: { fontFamily: "Open Sans, Arial, sans-serif" },
  legend: {
    top: 0,
    left: 0,
    itemWidth: 14,
    itemHeight: 8,
    textStyle: { color: "#474c51" },
  },
};

/** Weekly area means of the region (all member states): observed, and each layer. */
function RegionalMeans({ summary }: { summary: VerificationSummary }) {
  const option = useMemo(() => {
    const weeks = summary.series.map((w) => day(w.valid_start));
    const layers = LAYERS.filter((l) =>
      summary.series.some((w) => w.forecast_mean[l] != null),
    );
    return {
      ...baseOption,
      grid: { left: 52, right: 20, top: 62, bottom: 34 },
      tooltip: {
        trigger: "axis" as const,
        valueFormatter: (value: unknown) =>
          value == null ? "—" : `${num(Number(value))} mm`,
      },
      xAxis: {
        type: "category" as const,
        data: weeks,
        axisLabel: { color: AXIS },
        axisLine: { lineStyle: { color: "#cfd6db" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value" as const,
        name: "mm / week",
        nameTextStyle: { color: AXIS },
        axisLabel: { color: AXIS },
        splitLine: { lineStyle: { color: GRID } },
      },
      series: [
        {
          name: "Observed",
          type: "line" as const,
          data: summary.series.map((w) => w.observed_mean),
          lineStyle: { width: 2, color: INK, type: "dashed" as const },
          itemStyle: { color: INK },
          symbolSize: 8,
        },
        ...layers.map((l) => ({
          name: SERIES[l].label,
          type: "line" as const,
          data: summary.series.map((w) => w.forecast_mean[l] ?? null),
          lineStyle: { width: 2, color: COLOURS[l] },
          itemStyle: { color: COLOURS[l] },
          symbolSize: 8,
        })),
      ],
    };
  }, [summary]);
  return (
    <Chart
      option={option}
      height={300}
      label="Regional mean Week-2 rainfall per verified week, observed and forecast (values in the table below)"
    />
  );
}

/** The regional means and the mean scores of each layer, with 95% intervals. */
export function SkillSummary() {
  const [source, setSource] = useState("best");
  const summary = useApi<VerificationSummary>(
    `/verification/summary?source=${source}`,
  );
  if (summary.status === 404) return null; // an older service
  const data = summary.data;
  return (
    <Disclosure
      title="Regional mean and scores, with 95% confidence intervals"
      subtitle="Forecast and observed area means; mean scores per layer (bootstrap over weeks)"
    >
      <div className="evidence-controls">
        <SourcePicker value={source} onChange={setSource} />
      </div>
      {summary.loading && !data && <Skeleton height={300} />}
      {data && data.weeks === 0 && (
        <p style={{ margin: 0, color: "var(--muted)" }}>
          No week has been verified against this observation yet.
        </p>
      )}
      {data && data.weeks > 0 && (
        <>
          <RegionalMeans summary={data} />
          <div className="table-wrap" style={{ marginTop: 18 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Forecast layer</th>
                  <th className="num">Regional mean (mm)</th>
                  <th className="num">Observed mean (mm)</th>
                  <th className="num">RMSE (mm)</th>
                  <th className="num">MAE (mm)</th>
                  <th className="num">Bias (mm)</th>
                  <th className="num">Pearson r</th>
                  <th className="num">RMSE against raw ECMWF</th>
                </tr>
              </thead>
              <tbody>
                {LAYERS.filter((l) => data.layers[l]).map((l) => {
                  const s = data.layers[l]!;
                  const change = s.rmse_change_vs_raw;
                  return (
                    <tr key={l}>
                      <td className="strong">{SERIES[l].label}</td>
                      <td className="num">
                        {withInterval(s.forecast_mean, 1)}
                      </td>
                      <td className="num">
                        {withInterval(s.observed_mean, 1)}
                      </td>
                      <td className="num">{withInterval(s.rmse, 2)}</td>
                      <td className="num">{withInterval(s.mae, 2)}</td>
                      <td className="num">
                        {withInterval(s.bias, 2, "", true)}
                      </td>
                      <td className="num">{withInterval(s.correlation, 3)}</td>
                      <td className="num">
                        {l === "raw" || !change || change.change == null
                          ? "—"
                          : change.interval
                            ? `${percent(change.change)} (${percent(change.interval[0])} to ${percent(change.interval[1])})`
                            : percent(change.change)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted-line" style={{ maxWidth: "none" }}>
            {data.weeks} week{data.weeks === 1 ? "" : "s"}; 95% interval in
            brackets. RMSE change below zero: better than raw ECMWF.
          </p>
          <details style={{ marginTop: 10 }}>
            <summary>The weekly regional means</summary>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Week starting</th>
                    <th>Observed by</th>
                    <th className="num">Observed (mm)</th>
                    {LAYERS.map((l) => (
                      <th key={l} className="num">
                        {SERIES[l].label} (mm)
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.series.map((w) => (
                    <tr key={w.forecast_id}>
                      <td>{day(w.valid_start)}</td>
                      <td>{w.observed_by}</td>
                      <td className="num">{num(w.observed_mean)}</td>
                      {LAYERS.map((l) => (
                        <td key={l} className="num">
                          {num(w.forecast_mean[l])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </Disclosure>
  );
}

/** Vertical 95% interval bars drawn at (x, low, high) points. */
function intervalBars(
  name: string,
  data: [number, number, number][],
  colour: string,
): echarts.CustomSeriesOption {
  return {
    name,
    type: "custom",
    data,
    encode: { x: 0, y: [1, 2] },
    z: 1,
    itemStyle: { color: colour },
    tooltip: { show: false },
    renderItem: (_params, api) => {
      const x = Number(api.value(0));
      const low = api.coord([x, Number(api.value(1))]);
      const high = api.coord([x, Number(api.value(2))]);
      const style = { stroke: colour, lineWidth: 1.5, opacity: 0.7 };
      return {
        type: "group",
        children: [
          {
            type: "line",
            shape: { x1: low[0], y1: low[1], x2: high[0], y2: high[1] },
            style,
          },
          {
            type: "line",
            shape: { x1: low[0] - 4, y1: low[1], x2: low[0] + 4, y2: low[1] },
            style,
          },
          {
            type: "line",
            shape: {
              x1: high[0] - 4,
              y1: high[1],
              x2: high[0] + 4,
              y2: high[1],
            },
            style,
          },
        ],
      };
    },
  };
}

/** A tooltip on the forecast's own points; the reference lines and bars name themselves. */
function pointTooltip(describe: (x: number, y: number) => string) {
  return {
    trigger: "item" as const,
    formatter: (params: unknown) => {
      const item = params as { seriesName?: string; value?: unknown };
      const value = Array.isArray(item.value) ? item.value.map(Number) : [];
      return item.seriesName === "Forecast" && value.length >= 2
        ? describe(value[0], value[1])
        : (item.seriesName ?? "");
    },
  };
}

function unitAxis(name: string) {
  return {
    type: "value" as const,
    min: 0,
    max: 1,
    name,
    nameLocation: "middle" as const,
    nameGap: 30,
    nameTextStyle: { color: AXIS },
    axisLabel: { color: AXIS },
    splitLine: { lineStyle: { color: GRID } },
  };
}

export function Reliability({ data }: { data: ProbabilisticSummary }) {
  const colour = COLOURS[data.layer];
  const option = useMemo(() => {
    const rows = (data.reliability ?? []).filter((r) => r.count > 0);
    return {
      ...baseOption,
      grid: { left: 52, right: 20, top: 40, bottom: 48 },
      tooltip: pointTooltip(
        (x, y) =>
          `Forecast ${num(x * 100, 0)}%: happened ${num(y * 100, 0)}% of the time`,
      ),
      xAxis: unitAxis("Forecast probability"),
      yAxis: unitAxis("Observed frequency"),
      series: [
        {
          name: "Perfect reliability",
          type: "line" as const,
          data: [
            [0, 0],
            [1, 1],
          ],
          symbol: "none",
          lineStyle: { color: AXIS, type: "dashed" as const, width: 1 },
          itemStyle: { color: AXIS },
        },
        intervalBars(
          "95% interval",
          rows
            .filter((r) => r.interval)
            .map(
              (r) =>
                [r.probability, r.interval![0], r.interval![1]] as [
                  number,
                  number,
                  number,
                ],
            ),
          colour,
        ),
        {
          name: "Forecast",
          type: "line" as const,
          data: rows
            .filter((r) => r.observed != null)
            .map((r) => [r.probability, r.observed]),
          lineStyle: { color: colour, width: 2 },
          itemStyle: { color: colour },
          symbolSize: 8,
          z: 3,
        },
      ],
    };
  }, [data, colour]);
  return (
    <Chart
      option={option}
      height={320}
      label="Reliability diagram: forecast probability against observed frequency, with 95% intervals"
    />
  );
}

function Sharpness({ data }: { data: ProbabilisticSummary }) {
  const colour = COLOURS[data.layer];
  const option = useMemo(() => {
    const rows = data.reliability ?? [];
    const total = rows.reduce((a, r) => a + r.count, 0) || 1;
    return {
      ...baseOption,
      legend: { show: false },
      grid: { left: 52, right: 20, top: 16, bottom: 30 },
      tooltip: {
        trigger: "axis" as const,
        valueFormatter: (value: unknown) =>
          `${num(Number(value) * 100, 1)}% of cells`,
      },
      xAxis: {
        type: "category" as const,
        data: rows.map((r) => `${num(r.probability * 100, 0)}%`),
        axisLabel: { color: AXIS },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cfd6db" } },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: {
          color: AXIS,
          formatter: (v: number) => `${num(v * 100, 0)}%`,
        },
        splitLine: { lineStyle: { color: GRID } },
      },
      series: [
        {
          name: "Share of cells",
          type: "bar" as const,
          data: rows.map((r) => r.count / total),
          barMaxWidth: 18,
          itemStyle: { color: colour, borderRadius: [4, 4, 0, 0] },
        },
      ],
    };
  }, [data, colour]);
  return (
    <Chart
      option={option}
      height={150}
      label="How often each probability was forecast"
    />
  );
}

export function Roc({ data }: { data: ProbabilisticSummary }) {
  const colour = COLOURS[data.layer];
  const option = useMemo(() => {
    const points = (data.roc ?? []).filter(
      (p) => p.false_alarm_rate != null && p.hit_rate != null,
    );
    const curve = [
      [0, 0],
      ...[...points]
        .sort((a, b) => a.false_alarm_rate! - b.false_alarm_rate!)
        .map((p) => [p.false_alarm_rate!, p.hit_rate!]),
      [1, 1],
    ];
    return {
      ...baseOption,
      grid: { left: 52, right: 20, top: 40, bottom: 48 },
      tooltip: pointTooltip(
        (x, y) =>
          `Hit rate ${num(y * 100, 0)}%, false alarms ${num(x * 100, 0)}%`,
      ),
      xAxis: unitAxis("False alarm rate"),
      yAxis: unitAxis("Hit rate"),
      series: [
        {
          name: "No skill",
          type: "line" as const,
          data: [
            [0, 0],
            [1, 1],
          ],
          symbol: "none",
          lineStyle: { color: AXIS, type: "dashed" as const, width: 1 },
          itemStyle: { color: AXIS },
        },
        intervalBars(
          "95% interval of the hit rate",
          points
            .filter((p) => p.hit_rate_interval)
            .map(
              (p) =>
                [
                  p.false_alarm_rate!,
                  p.hit_rate_interval![0],
                  p.hit_rate_interval![1],
                ] as [number, number, number],
            ),
          colour,
        ),
        {
          name: "Forecast",
          type: "line" as const,
          data: curve,
          lineStyle: { color: colour, width: 2 },
          itemStyle: { color: colour },
          symbolSize: 8,
          z: 3,
        },
      ],
    };
  }, [data, colour]);
  return (
    <Chart
      option={option}
      height={320}
      label="ROC curve: hit rate against false alarm rate, with 95% intervals of the hit rate"
    />
  );
}

export function Stat({
  label,
  value,
  interval,
  hint,
}: {
  label: string;
  value: string;
  interval?: string;
  hint: string;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 22 }}>
        {value}
      </div>
      <div className="hint">
        {interval ? `95% interval ${interval}. ` : ""}
        {hint}
      </div>
    </div>
  );
}

function range(interval: [number, number] | null | undefined, digits: number) {
  return interval
    ? `${num(interval[0], digits)} to ${num(interval[1], digits)}`
    : undefined;
}

/** Reliability diagram and ROC curve of the chance that the week's rainfall exceeds a
 * threshold, from how many of the ensemble's members exceed it. */
export function ProbabilisticVerification() {
  // No layer picked yet: the service answers for the best one the weeks hold.
  const [picked, setPicked] = useState<Variant | null>(null);
  const [threshold, setThreshold] = useState(25);
  const [source, setSource] = useState("best");
  const result = useApi<ProbabilisticSummary>(
    `/verification/probabilistic?${picked ? `layer=${picked}&` : ""}threshold=${threshold}&source=${source}`,
  );
  if (result.status === 404) return null; // an older service
  const data = result.data;
  const thresholds = data?.thresholds_mm ?? [10, 25, 50];
  const by = Object.entries(data?.observed_by ?? {})
    .map(([name, weeks]) => `${name} (${weeks})`)
    .join(", ");
  return (
    <Disclosure
      title="Reliability and ROC: the chance of a wet week"
      subtitle="Chance = share of members above the threshold"
    >
      <div className="evidence-controls">
        <label className="field">
          Rainfall above
          <select
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          >
            {thresholds.map((t) => (
              <option key={t} value={t}>
                {num(t, 0)} mm in the week
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Forecast layer
          <select
            value={picked ?? result.data?.layer ?? "hybrid"}
            onChange={(e) => setPicked(e.target.value as Variant)}
          >
            {LAYERS.map((v) => (
              <option key={v} value={v}>
                {SERIES[v].label}
              </option>
            ))}
          </select>
        </label>
        <SourcePicker value={source} onChange={setSource} />
      </div>
      {result.loading && !data && <Skeleton height={320} />}
      {data && data.weeks === 0 && (
        <Notice title="No verified week holds member probabilities yet.">
          Press Start again on the Forecast archive to forecast the last 12
          weeks with them.
        </Notice>
      )}
      {data && data.weeks > 0 && (
        <>
          <div className="stats" style={{ marginBottom: 18 }}>
            <Stat
              label="ROC area"
              value={num(data.auc, 2)}
              interval={range(data.auc_interval, 2)}
              hint="1 is perfect, 0.5 no skill"
            />
            <Stat
              label="Brier skill score"
              value={num(data.brier_skill, 2)}
              interval={range(data.brier_skill_interval, 2)}
              hint="Above 0: better than climatology"
            />
            <Stat
              label="Observed frequency"
              value={
                data.base_rate == null
                  ? "—"
                  : `${num(data.base_rate * 100, 0)}%`
              }
              hint={`Share of cells above ${num(threshold, 0)} mm`}
            />
            <Stat
              label="Weeks"
              value={String(data.weeks)}
              hint={`${data.members} members; observed by ${by}`}
            />
          </div>
          {data.weeks < 3 && (
            <p className="muted-line" style={{ maxWidth: "none" }}>
              The 95% intervals need at least three verified weeks.
            </p>
          )}
          <div className="grid-2">
            <div>
              <h4 style={{ margin: "0 0 4px" }}>Reliability diagram</h4>
              <Reliability data={data} />
              <p className="muted-line" style={{ maxWidth: "none" }}>
                Sharpness:
              </p>
              <Sharpness data={data} />
            </div>
            <div>
              <h4 style={{ margin: "0 0 4px" }}>ROC curve</h4>
              <Roc data={data} />
            </div>
          </div>
          <details style={{ marginTop: 10 }}>
            <summary>The numbers behind the curves</summary>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">Forecast probability</th>
                    <th className="num">Cells</th>
                    <th className="num">Observed frequency (95% interval)</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.reliability ?? []).map((r) => (
                    <tr key={r.probability}>
                      <td className="num">{num(r.probability * 100, 0)}%</td>
                      <td className="num">{r.count.toLocaleString("en-GB")}</td>
                      <td className="num">
                        {r.observed == null
                          ? "—"
                          : `${num(r.observed * 100, 1)}%${r.interval ? ` (${num(r.interval[0] * 100, 1)} to ${num(r.interval[1] * 100, 1)})` : ""}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </Disclosure>
  );
}
