"use client";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Bell,
  Bot,
  CheckCircle2,
  ChevronRight,
  CloudRain,
  Database,
  FileText,
  FlaskConical,
  Globe2,
  Layers3,
  LayoutDashboard,
  LoaderCircle,
  Moon,
  Play,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sun,
  TerminalSquare,
  TrendingUp,
} from "lucide-react";
import Chart from "@/components/chart";
import Workflow from "@/features/workflow";
import { mutate, query, request } from "@/services/api";
import type { Analysis, Config, Selection } from "@/types";
const ClimateMap = dynamic(() => import("@/components/map"), {
  ssr: false,
  loading: () => <div className="map skeleton">Loading regional map…</div>,
});
const nav = [
  ["overview", "Overview", LayoutDashboard],
  ["forecasts", "Forecasts", CloudRain],
  ["monitoring", "Monitoring", Activity],
  ["verification", "Verification", ShieldCheck],
  ["observations", "Observations", Database],
  ["models", "Models", Layers3],
  ["products", "Products", ArrowDownToLine],
  ["bulletins", "Bulletins", FileText],
  ["copilot", "Forecaster Copilot", Bot],
  ["jobs", "Jobs", TerminalSquare],
  ["health", "System Health", Activity],
  ["settings", "Settings", Settings2],
] as const;
const defaults: Selection = {
  cycle: "2026-09-28",
  observation: "CHIRPS",
  model: "mock-v1",
  provider: "ECMWF S2S",
  country: "GHA",
  layer: "corrected",
};
export const number = (value: number | null | undefined, digits = 1) =>
  value == null ? "Unavailable" : value.toFixed(digits);
export function Panel({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export default function Platform({ view }: { view: string }) {
  const [config, setConfig] = useState<Config | null>(null),
    [analysis, setAnalysis] = useState<Analysis | null>(null),
    [selection, setSelection] = useState(defaults),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [refresh, setRefresh] = useState(0),
    [dark, setDark] = useState(false),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setDark(localStorage.getItem("icpac-theme") === "dark");
  }, []);
  useEffect(() => {
    request<Config>("/config")
      .then(setConfig)
      .catch((e) => setError(e.message));
  }, [refresh]);
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
  useEffect(() => {
    if (view === "monitoring")
      setSelection((old) => ({ ...old, layer: "observed" }));
  }, [view]);
  const workflowView = [
    "models",
    "bulletins",
    "copilot",
    "jobs",
    "health",
    "settings",
  ].includes(view);
  const title = nav.find((n) => n[0] === view)?.[1] ?? "Overview";
  const set = (key: keyof Selection, value: string) =>
    setSelection((old) => ({ ...old, [key]: value }));
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
  return (
    <div className={"app " + (dark ? "dark" : "")}>
      <aside className="sidebar">
        <Link href="/" className="brand">
          <div className="brand-mark">
            <Globe2 size={25} />
          </div>
          <div>
            <strong>
              IGAD <span>|</span> ICPAC
            </strong>
            <small>CLIMATE INTELLIGENCE</small>
          </div>
        </Link>
        <div className="workspace-tag">
          <span className="live-dot" /> FORECASTER WORKSPACE
        </div>
        <nav aria-label="Main navigation">
          {nav.map(([key, label, Icon]) => (
            <Link
              href={key === "overview" ? "/" : "/" + key}
              key={key}
              className={view === key ? "active" : ""}
              title={label}
            >
              <Icon size={18} />
              <span>{label}</span>
              {view === key && <ChevronRight size={14} />}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="prototype-tag">
            <FlaskConical size={15} /> PROTOTYPE v0.1
          </div>
          <p>
            Decision support for a<br />
            climate-resilient Eastern Africa.
          </p>
          <div className="profile">
            <div className="avatar">FC</div>
            <div>
              <strong>Forecaster</strong>
              <small>Local demonstration</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>Climate Intelligence Platform</span>
          <div className="topbar-right">
            <span className="environment">Prototype</span>
            <span className="health-dot">
              <span className={error ? "warn-dot" : "live-dot"} />
              {error
                ? "Connection issue"
                : analysis
                  ? "API connected"
                  : "Connecting"}
            </span>
            <button
              className="icon-button"
              aria-label="Toggle theme"
              onClick={() => {
                localStorage.setItem("icpac-theme", dark ? "light" : "dark");
                setDark(!dark);
              }}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              className="icon-button"
              aria-label="Show recent alerts"
              onClick={() =>
                setNotice(
                  "Synthetic providers active. Operational credentials and authoritative masks are not configured.",
                )
              }
            >
              <Bell size={18} />
            </button>
          </div>
        </header>
        <main>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} /> {title}
          </div>
          <div className="page-title">
            <div>
              <div className="eyebrow">EASTERN AFRICA · WEEK-2 OPERATIONS</div>
              <h1>{view === "overview" ? "Forecast operations" : title}</h1>
              <p>
                {view === "verification"
                  ? "Evaluate model output against independent observation sources."
                  : "From climate data to reviewed guidance, in one workspace."}
              </p>
            </div>
            <div className="title-actions">
              <button
                className="button secondary"
                onClick={() => setRefresh((x) => x + 1)}
              >
                <RefreshCw size={15} />
                Refresh
              </button>
              <button
                className="button primary"
                onClick={verify}
                disabled={busy || loading || !!error}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Play size={15} />
                )}
                Run verification
              </button>
            </div>
          </div>
          <div className="demo-banner">
            <FlaskConical size={15} />
            <strong>DEMO DATA</strong>
            <span>
              Synthetic datasets & demonstration models · Not for operational
              forecasting
            </span>
            <span className="banner-version">PIPELINE v1</span>
          </div>
          {notice && (
            <div role="status" className="notice">
              {notice}
              <button onClick={() => setNotice("")} aria-label="Dismiss notice">
                ×
              </button>
            </div>
          )}
          <div className="filters">
            {config && (
              <>
                <Select
                  label="Forecast cycle"
                  value={selection.cycle}
                  options={config.forecasts.cycles}
                  change={(v) => set("cycle", v)}
                />
                <Select
                  label="Forecast provider"
                  value={selection.provider}
                  options={config.forecasts.sources}
                  change={(v) => set("provider", v)}
                />
                <Select
                  label="Forecast model"
                  value={selection.model}
                  options={config.models
                    .filter(
                      (m) =>
                        !["retired", "failed"].includes(m.status) &&
                        m.task !== "week2_operational",
                    )
                    .map((m) => ({ value: m.model_id, label: m.model_name }))}
                  change={(v) => set("model", v)}
                />
                <Select
                  label="Observation source"
                  value={selection.observation}
                  options={config.observations}
                  change={(v) => set("observation", v)}
                />
                <Select
                  label="Region"
                  value={selection.country}
                  options={["GHA", ...config.science.countries]}
                  change={(v) => set("country", v)}
                />
              </>
            )}
            <div className="lead-pill">
              <small>LEAD WINDOW</small>
              <strong>Days 8–14</strong>
            </div>
          </div>
          {!workflowView &&
            (error ? (
              <div className="error" role="alert">
                <strong>Unable to load this selection</strong>
                <p>{error}</p>
                <button
                  className="button secondary"
                  onClick={() => setRefresh((x) => x + 1)}
                >
                  Retry
                </button>
              </div>
            ) : !analysis ? (
              <div className="loading">
                <LoaderCircle className="spin" />
                Loading validated climate products…
              </div>
            ) : (
              <div
                className={loading ? "content refreshing" : "content"}
                aria-busy={loading}
              >
                {[
                  "overview",
                  "forecasts",
                  "verification",
                  "monitoring",
                ].includes(view) && (
                  <>
                    <div className="stats">
                      <Stat
                        icon={<CloudRain size={19} />}
                        label={
                          view === "verification"
                            ? "Mean absolute error"
                            : "Regional rainfall"
                        }
                        value={number(
                          view === "verification"
                            ? analysis.metrics.mae
                            : analysis.mean_rainfall_mm,
                        )}
                        unit="mm"
                        caption={
                          selection.country + " · accumulated seven-day case"
                        }
                      />
                      <Stat
                        icon={<TrendingUp size={19} />}
                        label="RMSE"
                        value={number(analysis.metrics.rmse)}
                        unit="mm"
                        caption={
                          "Against " +
                          selection.observation +
                          " · spatial cells"
                        }
                      />
                      <Stat
                        icon={<Activity size={19} />}
                        label="Spatial correlation"
                        value={number(analysis.metrics.correlation, 3)}
                        unit=""
                        caption={
                          analysis.metrics.sample_count + " paired grid cells"
                        }
                      />
                      <Stat
                        icon={<ShieldCheck size={19} />}
                        label="Quality control"
                        value={
                          analysis.qc.every((q) => q.status === "PASS")
                            ? "PASS"
                            : "CHECK"
                        }
                        unit=""
                        caption={analysis.qc.length + " datasets validated"}
                        success
                      />
                    </div>
                    <div className="two-columns">
                      <Panel
                        title={
                          view === "monitoring"
                            ? "Observed rainfall"
                            : "Regional rainfall outlook"
                        }
                        subtitle={
                          analysis.period.replace("/", " → ") + " · Days 8–14"
                        }
                        action={<span className="badge green">SYNTHETIC</span>}
                      >
                        <div className="map-tools">
                          {[
                            "corrected",
                            "raw",
                            "observed",
                            "anomaly",
                            "bias",
                            "rmse",
                            "improvement",
                          ].map((layer) => (
                            <button
                              key={layer}
                              onClick={() => set("layer", layer)}
                              className={
                                selection.layer === layer ? "selected" : ""
                              }
                            >
                              {
                                (
                                  {
                                    corrected: "Corrected",
                                    raw: "Raw",
                                    observed: "Observed",
                                    anomaly: "Anomaly",
                                    bias: "Bias",
                                    rmse: "Error",
                                    improvement: "Improvement",
                                  } as Record<string, string>
                                )[layer]
                              }
                            </button>
                          ))}
                        </div>
                        <ClimateMap analysis={analysis} />
                        <div className="map-bottom">
                          <span>
                            Approximate masks · {analysis.map.features.length}{" "}
                            cells
                          </span>
                          <a href={"/api/export/png?" + query(selection)}>
                            Download map <ArrowDownToLine size={13} />
                          </a>
                        </div>
                      </Panel>
                      <div className="right-stack">
                        <Panel
                          title="Model comparison"
                          subtitle={
                            selection.observation + " reference · same case"
                          }
                          action={<span className="unit-label">RMSE · mm</span>}
                        >
                          <Chart
                            height={195}
                            option={{
                              grid: {
                                left: 45,
                                right: 20,
                                top: 25,
                                bottom: 35,
                              },
                              tooltip: { trigger: "axis" },
                              xAxis: {
                                type: "category",
                                data: analysis.model_comparison.map(
                                  (x) => x.model,
                                ),
                                axisLine: { show: false },
                                axisTick: { show: false },
                              },
                              yAxis: {
                                type: "value",
                                splitLine: { lineStyle: { color: "#e5eae5" } },
                              },
                              series: [
                                {
                                  type: "bar",
                                  barWidth: 46,
                                  data: analysis.model_comparison.map(
                                    (x, i) => ({
                                      value: Number(x.rmse.toFixed(2)),
                                      itemStyle: {
                                        color: i === 0 ? "#b8c4ba" : "#2d7562",
                                        borderRadius: [5, 5, 0, 0],
                                      },
                                    }),
                                  ),
                                  label: { show: true, position: "top" },
                                },
                              ],
                            }}
                          />
                          <div className="chart-note">
                            <ShieldCheck size={14} />
                            Computed by the verification engine
                          </div>
                        </Panel>
                        <Panel
                          title="Operational readiness"
                          subtitle="Local prototype environment"
                        >
                          <div className="readiness">
                            {[
                              ["Forecast ingestion", "Ready"],
                              ["Observation adapters", "3 sources"],
                              ["Model inference", "Mock active"],
                              ["HPC connection", "Simulated"],
                            ].map(([label, status]) => (
                              <div key={label}>
                                <span>
                                  <CheckCircle2 size={15} />
                                  {label}
                                </span>
                                <span
                                  className={
                                    "badge " +
                                    (status === "Simulated" ? "amber" : "green")
                                  }
                                >
                                  {status}
                                </span>
                              </div>
                            ))}
                          </div>
                          <Link href="/jobs" className="panel-link">
                            Inspect pipeline jobs <ArrowRight size={14} />
                          </Link>
                        </Panel>
                      </div>
                    </div>
                    <div className="two-columns lower">
                      <Panel
                        title="Country summaries"
                        subtitle="Area-weighted synthetic rainfall · seven-day total"
                        action={
                          <a
                            className="small-link"
                            href={"/api/export/csv?" + query(selection)}
                          >
                            Export CSV <ArrowDownToLine size={13} />
                          </a>
                        }
                      >
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>COUNTRY</th>
                                <th>RAINFALL</th>
                                <th>RMSE</th>
                                <th>BIAS</th>
                                <th>CELLS</th>
                              </tr>
                            </thead>
                            <tbody>
                              {analysis.countries.map((c) => (
                                <tr key={c.country}>
                                  <td>
                                    <button
                                      className="country-link"
                                      onClick={() => set("country", c.country)}
                                    >
                                      {c.country}
                                    </button>
                                  </td>
                                  <td>
                                    {number(c.mean_rainfall_mm)}{" "}
                                    <small>mm</small>
                                  </td>
                                  <td>{number(c.rmse)}</td>
                                  <td>{number(c.bias)}</td>
                                  <td>{c.cell_count || "No cells"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </Panel>
                      <div className="right-stack">
                        <Panel
                          title="Observation comparison"
                          subtitle="Reference source changes verification"
                        >
                          <div className="observation-list">
                            {analysis.observation_comparison.map((o) => (
                              <button
                                key={o.source}
                                onClick={() => set("observation", o.source)}
                                className={
                                  o.source === selection.observation
                                    ? "chosen"
                                    : ""
                                }
                              >
                                <div className="source-icon">
                                  <Database size={17} />
                                </div>
                                <div>
                                  <strong>{o.source}</strong>
                                  <small>Synthetic observation</small>
                                </div>
                                <div className="source-score">
                                  <strong>
                                    {number(o.rmse)} <small>mm</small>
                                  </strong>
                                  <small>RMSE</small>
                                </div>
                              </button>
                            ))}
                          </div>
                        </Panel>
                        <div className="copilot-card">
                          <div className="copilot-orb">
                            <Bot size={24} />
                          </div>
                          <div>
                            <h3>Your Forecaster Copilot</h3>
                            <p>
                              Explore verified data, compare sources, and
                              prepare a reviewed narrative.
                            </p>
                            <Link href="/copilot">
                              Open Copilot <ArrowRight size={14} />
                            </Link>
                          </div>
                        </div>
                      </div>
                    </div>
                    {view === "verification" && (
                      <Panel
                        title="Daily rainfall comparison"
                        subtitle="Underlying daily increments · mm/day"
                      >
                        <Chart
                          option={{
                            color: ["#b58c60", "#2d7562"],
                            tooltip: { trigger: "axis" },
                            legend: { data: ["Raw forecast", "Observation"] },
                            grid: { left: 45, right: 20, bottom: 35 },
                            xAxis: {
                              type: "category",
                              data: analysis.timeseries.map((x) => x.date),
                            },
                            yAxis: { type: "value" },
                            series: [
                              {
                                name: "Raw forecast",
                                type: "line",
                                data: analysis.timeseries.map((x) => x.raw),
                              },
                              {
                                name: "Observation",
                                type: "line",
                                data: analysis.timeseries.map(
                                  (x) => x.observed,
                                ),
                              },
                            ],
                          }}
                        />
                      </Panel>
                    )}
                    {view === "forecasts" && (
                      <Panel
                        title="Product provenance"
                        subtitle="Source, model, configuration and period"
                      >
                        <pre>
                          {JSON.stringify(analysis.provenance, null, 2)}
                        </pre>
                        <p className="prose">
                          Probability products require calibration and validated
                          hindcasts; unavailable in this prototype.
                        </p>
                      </Panel>
                    )}
                  </>
                )}
                {view === "observations" && (
                  <div className="source-grid">
                    {analysis.qc.map((q) => (
                      <Panel
                        key={q.dataset}
                        title={q.dataset}
                        subtitle="Canonical dataset quality control"
                        action={<span className="badge green">{q.status}</span>}
                      >
                        <div className="checks">
                          {Object.entries(q.checks).map(([name, value]) => (
                            <div key={name}>
                              <span>{name.replaceAll("_", " ")}</span>
                              <strong>{String(value)}</strong>
                            </div>
                          ))}
                        </div>
                      </Panel>
                    ))}
                    <Panel
                      title="Additional providers"
                      subtitle="Interfaces prepared for integration"
                    >
                      <p className="prose">
                        IMERG, ARC2 and stations remain unavailable. CHIRPS,
                        TAMSAT and RFE2 use reproducible synthetic data.
                      </p>
                    </Panel>
                  </div>
                )}
                {view === "products" && (
                  <Panel
                    title="Forecast product package"
                    subtitle="Synthetic labels and provenance"
                  >
                    <div className="product-grid">
                      {[
                        ["png", "Regional map"],
                        ["csv", "Country verification"],
                        ["json", "Forecast & provenance"],
                      ].map(([fmt, name]) => (
                        <a
                          key={fmt}
                          className="product-card"
                          href={"/api/export/" + fmt + "?" + query(selection)}
                        >
                          <div className="file-format">{fmt.toUpperCase()}</div>
                          <h3>{name}</h3>
                          <span>
                            Download <ArrowDownToLine size={14} />
                          </span>
                        </a>
                      ))}
                    </div>
                  </Panel>
                )}
              </div>
            ))}
          {workflowView && (
            <Workflow
              view={view}
              selection={selection}
              config={config}
              refresh={() => setRefresh((x) => x + 1)}
            />
          )}
          <footer>
            <span>IGAD | ICPAC · Climate Intelligence & Automation</span>
            <span>Deterministic science. Traceable outputs. Human review.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function Stat({
  icon,
  label,
  value,
  unit,
  caption,
  success = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit: string;
  caption: string;
  success?: boolean;
}) {
  return (
    <div className={"stat " + (success ? "stat-success" : "")}>
      <div className="stat-top">
        <span>{label}</span>
        {icon}
      </div>
      <div className="stat-value">
        {value}
        <span>{unit}</span>
      </div>
      <div className="stat-caption">
        {success && <span className="live-dot" />}
        {caption}
      </div>
    </div>
  );
}
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
    <label className="select">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => change(e.target.value)}
      >
        {options.map((o) => (
          <option
            key={typeof o === "string" ? o : o.value}
            value={typeof o === "string" ? o : o.value}
          >
            {typeof o === "string" ? o : o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
