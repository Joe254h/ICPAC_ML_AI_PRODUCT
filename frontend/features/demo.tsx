"use client";
/**
 * Demonstration workspace on the synthetic 60 x 60 grid (the first release's views):
 * observations, verification, bulletins and jobs can be exercised without HPC data.
 * Nothing here is a forecast; every view is labelled DEMO DATA.
 */
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowDownToLine, FlaskConical, Play, RefreshCw } from "lucide-react";
import Chart from "@/components/chart";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  KeyValues,
  Notice,
  PageHeader,
  Skeleton,
  Stat,
  Table,
  cx,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import type { PageProps } from "@/features/view";
import { num } from "@/lib/format";
import { mutate, query, request } from "@/services/api";
import type { Analysis, Selection } from "@/types";

const ClimateMap = dynamic(() => import("@/components/map"), {
  ssr: false,
  loading: () => <Skeleton className="h-[26rem]" />,
});

const VIEWS = [
  ["demo", "Overview"],
  ["monitoring", "Monitoring"],
  ["observations", "Observations"],
  ["products", "Products"],
] as const;

const LAYERS: Record<string, string> = {
  corrected: "Corrected",
  raw: "Raw",
  observed: "Observed",
  anomaly: "Anomaly",
  bias: "Bias",
  rmse: "Error",
  improvement: "Improvement",
};

function Select({
  label,
  value,
  options,
  change,
}: {
  label: string;
  value: string;
  options: (string | { value: string; label: string })[];
  change: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-muted-foreground">
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => change(e.target.value)}
        className="h-9 rounded-md border border-input bg-card px-3 text-foreground"
      >
        {options.map((o) => {
          const v = typeof o === "string" ? o : o.value;
          return (
            <option key={v} value={v}>
              {typeof o === "string" ? o : o.label}
            </option>
          );
        })}
      </select>
    </label>
  );
}

export default function Demo({ route }: PageProps) {
  const view = route.param ?? "overview";
  const { config, selection, setSelection } = useApp();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof Selection, value: string) =>
    setSelection((old) => ({ ...old, [key]: value }));
  useEffect(() => {
    if (view === "monitoring")
      setSelection((old) => ({ ...old, layer: "observed" }));
  }, [view, setSelection]);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    request<Analysis>("/analysis?" + query(selection), { signal: abort.signal })
      .then((data) => {
        setAnalysis(data);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => abort.abort();
  }, [selection, refresh]);
  const comparison = useMemo(
    () =>
      analysis && {
        grid: { left: 45, right: 16, top: 24, bottom: 32 },
        tooltip: { trigger: "axis" as const },
        xAxis: {
          type: "category" as const,
          data: analysis.model_comparison.map((x) => x.model),
          axisTick: { show: false },
        },
        yAxis: { type: "value" as const, name: "RMSE mm" },
        series: [
          {
            type: "bar" as const,
            barMaxWidth: 24,
            itemStyle: { color: "#2a78d6", borderRadius: [4, 4, 0, 0] },
            label: { show: true, position: "top" as const },
            data: analysis.model_comparison.map((x) =>
              Number(x.rmse.toFixed(2)),
            ),
          },
        ],
      },
    [analysis],
  );
  async function verify() {
    setBusy(true);
    try {
      await mutate("/verification/run", selection);
      setNotice(
        "Verification run saved with dataset, model and configuration provenance.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const demoModels = (config.data?.models ?? []).filter(
    (m) =>
      !["retired", "failed"].includes(m.status) &&
      m.task !== "week2_operational",
  );
  return (
    <>
      <PageHeader
        title={`Demonstration · ${VIEWS.find(([path]) => path === route.path)?.[1] ?? "Overview"}`}
        description="The synthetic 60 × 60 demonstration grid of the first release. It exercises observations, verification, bulletins and jobs; nothing here is a forecast."
        badges={
          <>
            <Badge tone="serious" icon={<FlaskConical size={13} />}>
              DEMO DATA
            </Badge>
            <Badge>
              Synthetic datasets & demonstration models · not for operational
              forecasting
            </Badge>
          </>
        }
        actions={
          <>
            <Button onClick={() => setRefresh((x) => x + 1)}>
              <RefreshCw size={15} />
              Refresh
            </Button>
            <Button
              variant="primary"
              onClick={verify}
              busy={busy}
              disabled={loading || !!error}
            >
              <Play size={15} />
              Run verification
            </Button>
          </>
        }
      />
      <nav
        aria-label="Demonstration views"
        className="flex flex-wrap gap-1 rounded-lg bg-muted p-1 w-fit"
      >
        {VIEWS.map(([path, label]) => (
          <Link
            key={path}
            href={"/" + path}
            className={cx(
              "rounded-md px-3 py-1.5 font-medium",
              route.path === path
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </Link>
        ))}
      </nav>
      {notice && (
        <Notice tone="good">
          <span className="flex items-center justify-between gap-3">
            {notice}
            <button onClick={() => setNotice("")} aria-label="Dismiss notice">
              ×
            </button>
          </span>
        </Notice>
      )}
      {config.data && (
        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Select
              label="Forecast cycle"
              value={selection.cycle}
              options={config.data.forecasts.cycles}
              change={(v) => set("cycle", v)}
            />
            <Select
              label="Forecast provider"
              value={selection.provider}
              options={config.data.forecasts.sources}
              change={(v) => set("provider", v)}
            />
            <Select
              label="Forecast model"
              value={selection.model}
              options={demoModels.map((m) => ({
                value: m.model_id,
                label: m.model_name,
              }))}
              change={(v) => set("model", v)}
            />
            <Select
              label="Observation source"
              value={selection.observation}
              options={config.data.observations}
              change={(v) => set("observation", v)}
            />
            <Select
              label="Region"
              value={selection.country}
              options={["GHA", ...config.data.science.countries]}
              change={(v) => set("country", v)}
            />
          </CardContent>
        </Card>
      )}
      {error ? (
        <ErrorState message={error} retry={() => setRefresh((x) => x + 1)} />
      ) : !analysis ? (
        <Skeleton className="h-96" />
      ) : (
        <div
          className={cx("content grid gap-6", loading && "opacity-60")}
          aria-busy={loading}
        >
          {(view === "overview" || view === "monitoring") && (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Stat
                  label="Regional rainfall"
                  value={num(analysis.mean_rainfall_mm)}
                  unit="mm"
                  hint={selection.country + " · seven-day synthetic case"}
                />
                <Stat
                  label="RMSE"
                  value={num(analysis.metrics.rmse)}
                  unit="mm"
                  hint={"Against " + selection.observation}
                />
                <Stat
                  label="Spatial correlation"
                  value={num(analysis.metrics.correlation, 3)}
                  hint={analysis.metrics.sample_count + " paired grid cells"}
                />
                <Stat
                  label="Quality control"
                  value={
                    analysis.qc.every((q) => q.status === "PASS")
                      ? "PASS"
                      : "CHECK"
                  }
                  hint={analysis.qc.length + " datasets validated"}
                />
              </div>
              <div className="grid gap-6 xl:grid-cols-3">
                <Card className="xl:col-span-2">
                  <CardHeader
                    title={
                      view === "monitoring"
                        ? "Observed rainfall"
                        : "Synthetic rainfall outlook"
                    }
                    description={
                      analysis.period.replace("/", " → ") + " · Days 8–14"
                    }
                    action={<Badge tone="serious">SYNTHETIC</Badge>}
                  />
                  <CardContent className="grid gap-3">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(LAYERS).map(([layer, label]) => (
                        <button
                          key={layer}
                          onClick={() => set("layer", layer)}
                          className={cx(
                            "rounded-md border px-2.5 py-1 text-[0.86rem]",
                            selection.layer === layer
                              ? "border-primary bg-accent text-accent-foreground"
                              : "border-border hover:bg-muted",
                          )}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <div className="legacy">
                      <ClimateMap analysis={analysis} />
                    </div>
                    <a
                      className="small-link"
                      href={"/api/export/png?" + query(selection)}
                    >
                      Download map <ArrowDownToLine size={13} />
                    </a>
                  </CardContent>
                </Card>
                <div className="grid content-start gap-6">
                  <Card>
                    <CardHeader
                      title="Model comparison"
                      description={
                        selection.observation + " reference · same case"
                      }
                    />
                    <CardContent>
                      {comparison && (
                        <Chart
                          option={comparison}
                          height={200}
                          label="Demonstration RMSE by model"
                        />
                      )}
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader title="Observation comparison" />
                    <CardContent className="grid gap-2">
                      {analysis.observation_comparison.map((o) => (
                        <button
                          key={o.source}
                          onClick={() => set("observation", o.source)}
                          className={cx(
                            "flex items-center justify-between rounded-md border px-3 py-2 text-left",
                            o.source === selection.observation
                              ? "border-primary bg-accent"
                              : "border-border hover:bg-muted",
                          )}
                        >
                          <span className="font-medium">{o.source}</span>
                          <span className="tabular text-muted-foreground">
                            RMSE {num(o.rmse)} mm
                          </span>
                        </button>
                      ))}
                    </CardContent>
                  </Card>
                </div>
              </div>
              <Card>
                <CardHeader
                  title="Country summaries"
                  description="Area-weighted synthetic rainfall · seven-day total"
                  action={
                    <a
                      className="small-link"
                      href={"/api/export/csv?" + query(selection)}
                    >
                      Export CSV <ArrowDownToLine size={13} />
                    </a>
                  }
                />
                <CardContent>
                  <Table
                    head={["Country", "Rainfall", "RMSE", "Bias", "Cells"]}
                  >
                    {analysis.countries.map((c) => (
                      <tr key={c.country} className="tabular">
                        <td>
                          <button
                            className="font-medium hover:underline"
                            onClick={() => set("country", c.country)}
                          >
                            {c.country}
                          </button>
                        </td>
                        <td>{num(c.mean_rainfall_mm)} mm</td>
                        <td>{num(c.rmse)}</td>
                        <td>{num(c.bias)}</td>
                        <td>{c.cell_count || "No cells"}</td>
                      </tr>
                    ))}
                  </Table>
                </CardContent>
              </Card>
            </>
          )}
          {view === "observations" && (
            <div className="grid gap-6 lg:grid-cols-2">
              {analysis.qc.map((q) => (
                <Card key={q.dataset}>
                  <CardHeader
                    title={q.dataset}
                    description="Dataset quality control"
                    action={
                      <Badge tone={q.status === "PASS" ? "good" : "warning"}>
                        {q.status}
                      </Badge>
                    }
                  />
                  <CardContent className="pt-3">
                    <KeyValues
                      items={Object.entries(q.checks).map(([name, value]) => [
                        name.replaceAll("_", " "),
                        String(value),
                      ])}
                    />
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
          {view === "products" && (
            <Card>
              <CardHeader
                title="Demonstration product files"
                description="Synthetic labels and provenance"
              />
              <CardContent className="grid gap-3 sm:grid-cols-3">
                {[
                  ["png", "Regional map"],
                  ["csv", "Country verification"],
                  ["json", "Forecast & provenance"],
                ].map(([format, name]) => (
                  <a
                    key={format}
                    className="grid gap-1 rounded-lg border border-border p-4 hover:bg-muted"
                    href={"/api/export/" + format + "?" + query(selection)}
                  >
                    <span className="text-[0.78rem] font-semibold text-subtle">
                      {format.toUpperCase()}
                    </span>
                    <span className="font-medium">{name}</span>
                  </a>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
