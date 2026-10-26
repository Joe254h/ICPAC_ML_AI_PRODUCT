"use client";
/** One data source: ECMWF ensemble, CHIRPS, TAMSAT, or a source that is coming later. */
import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, Download, ExternalLink, RefreshCw } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  InProgress,
  KeyValues,
  LinkButton,
  Notice,
  PageBanner,
  Skeleton,
  Status,
  type Tone,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { useActor } from "@/lib/actor";
import {
  dateTime,
  day,
  num,
  period,
  sentence,
  validDays,
  versionLabel,
} from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type {
  ChirpsWindow,
  DataSource,
  Dekad,
  EcmwfInput,
  EcmwfReadiness,
  Operation,
} from "@/types/operational";

function OperationNotice({
  operation,
  error,
}: {
  operation: Operation | null;
  error: string | null;
}) {
  if (error) return <ErrorState message={error} />;
  if (!operation) return null;
  const failed = operation.status === "failed";
  const done = operation.status === "complete";
  return (
    <Notice
      tone={failed ? "red" : done ? "green" : "amber"}
      title={`${operation.title}:`}
    >
      {failed ? operation.error : (operation.messages.at(-1)?.text ?? "Queued")}{" "}
      <Link href="/data/runs">See the operations log</Link>
    </Notice>
  );
}

function mirrorName(mirror: string): string {
  if (mirror === "ecmwf" || mirror.includes("data.ecmwf.int")) return "ECMWF";
  if (mirror === "aws" || mirror.includes("amazonaws"))
    return "ECMWF archive (AWS)";
  if (mirror === "google" || mirror.includes("googleapis"))
    return "ECMWF archive (Google Cloud)";
  return "Local copy";
}

const POLICY: Record<string, string> = {
  catboost_full: "full CatBoost correction",
  global_alpha075: "75% CatBoost correction",
  mam_protected: "MAM-protected correction",
  mbc_only: "MBC only (fallback)",
};

const COMPATIBILITY: Record<
  EcmwfReadiness["compatibility"]["status"],
  [Tone, string]
> = {
  compatible: ["ok", "Compatible"],
  waiting: ["progress", "Waiting for an input"],
  unchecked: ["info", "Not checked yet"],
  incompatible: ["bad", "Incompatible input"],
  awaiting_review: ["progress", "Checks passed, review needed"],
  unknown: ["bad", "Model not loaded"],
};

function Yes({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <Status tone={ok ? "ok" : "bad"}>{children}</Status>;
}

function hours(values?: number[] | null): string {
  return values?.length ? values.map((h) => `${h} h`).join(", ") : "—";
}

function Readiness({
  ready,
  changed,
}: {
  ready: EcmwfReadiness;
  changed: () => void;
}) {
  const [actor] = useActor();
  const { operation, error, running, start } = useOperation(changed);
  const model = ready.model;
  const availability = ready.availability;
  const rain = ready.rainfall;
  const upper = ready.upper_air;
  const [tone, label] = COMPATIBILITY[ready.compatibility.status];
  const checks = ready.last_run?.input_checks ?? [];
  const failed = checks.filter((c) => c.status === "failed").length;
  return (
    <>
      <div className="grid-2">
        <Card
          title="Forecast generation"
          subtitle="Decided from the inputs held and their checks, for the model in use."
        >
          <KeyValues
            items={[
              [
                "Raw ECMWF and MBC",
                <span key="raw">
                  <Yes ok={ready.generation.raw_mbc.allowed}>
                    {ready.generation.raw_mbc.allowed ? "Allowed" : "Not yet"}
                  </Yes>{" "}
                  {ready.generation.raw_mbc.reason}
                </span>,
              ],
              [
                "MBC + AI/ML",
                <span key="ml">
                  <Yes ok={ready.generation.ml.allowed}>
                    {ready.generation.ml.allowed ? "Allowed" : "Not yet"}
                  </Yes>{" "}
                  {ready.generation.ml.reason}
                </span>,
              ],
              [
                "Compatibility",
                <span key="compat">
                  <Status tone={tone}>{label}</Status>{" "}
                  {ready.compatibility.detail}
                </span>,
              ],
              [
                "Real-time review",
                ready.realtime_review
                  ? `Confirmed by ${ready.realtime_review.actor}, ${dateTime(ready.realtime_review.timestamp)}`
                  : model?.realtime_gate_from
                    ? "Not confirmed: runs from 2025 produce the AI/ML layer only after a reviewer confirms the real-time input"
                    : "Not required for this model",
              ],
            ]}
          />
        </Card>
        <Card
          title="Model in use"
          subtitle="Inputs are checked against what this model was trained on."
          action={
            <LinkButton href="/models" variant="outline" size="sm">
              Models
            </LinkButton>
          }
        >
          {model ? (
            <KeyValues
              items={[
                [
                  "Model",
                  `${model.model_name ?? "—"} · version ${versionLabel(model.version ?? "")}`,
                ],
                [
                  "Policy",
                  model.policy ? (POLICY[model.policy] ?? model.policy) : "—",
                ],
                [
                  "Ensemble",
                  model.training_members
                    ? `${model.training_members} perturbed members (control excluded)`
                    : "Perturbed members 1–10",
                ],
                [
                  "Upper-air leads",
                  model.needs_upper_air
                    ? hours(model.pressure_steps_hours)
                    : "Not needed",
                ],
              ]}
            />
          ) : (
            <p style={{ margin: 0 }}>No operational model is registered.</p>
          )}
        </Card>
      </div>
      <Card
        title="Readiness"
        subtitle={`Recorded states, as of ${dateTime(ready.checked_at)}. Nothing here is assumed from a server answering: each item was checked or downloaded.`}
        action={
          <Button
            variant="outline"
            size="sm"
            disabled={running}
            onClick={() => start("check_ecmwf", actor || "Forecaster")}
          >
            <RefreshCw size={16} className={running ? "spin" : undefined} />
            {running ? "Checking…" : "Check ECMWF now"}
          </Button>
        }
      >
        <OperationNotice operation={operation} error={error} />
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Item</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="strong">Latest published run</td>
                <td>
                  {availability ? (
                    <Yes ok={availability.status === "published"}>
                      {availability.initialization
                        ? `${day(availability.initialization)}, 00 UTC`
                        : "None found"}
                    </Yes>
                  ) : (
                    <Status tone="planned">Not checked yet</Status>
                  )}
                </td>
                <td>
                  {availability
                    ? `${availability.summary}. Indexes read ${dateTime(availability.checked_at)}${availability.mirrors.length ? ` from ${availability.mirrors.map(mirrorName).join(", ")}` : ""}.`
                    : "Use “Check ECMWF now” to read the ECMWF Open Data indexes."}
                </td>
              </tr>
              <tr>
                <td className="strong">Total precipitation</td>
                <td>
                  <Yes ok={rain.status === "available"}>
                    {rain.status === "available"
                      ? "Downloaded"
                      : rain.status === "incomplete"
                        ? "Incomplete"
                        : "Not downloaded"}
                  </Yes>
                </td>
                <td>
                  {rain.initialization
                    ? `Run of ${day(rain.initialization)} · ${rain.members ?? "?"} members · steps ${hours(rain.steps_hours)} · ${rain.type ?? ""}`
                    : "No run downloaded yet."}
                </td>
              </tr>
              <tr>
                <td className="strong">Days 8–14 (Week 2)</td>
                <td>
                  <Yes ok={Boolean(rain.week2_complete)}>
                    {rain.week2_complete ? "Complete" : "Not complete"}
                  </Yes>
                </td>
                <td>
                  Week-2 rainfall is the accumulation between 168 h and 336 h,
                  per member.
                </td>
              </tr>
              <tr>
                <td className="strong">Upper-air predictors</td>
                <td>
                  {upper.status === "not_needed" ||
                  upper.status === "not_configured" ? (
                    <Status tone="planned">
                      {upper.status === "not_needed"
                        ? "Not needed"
                        : "Not configured"}
                    </Status>
                  ) : (
                    <Yes ok={upper.status === "available"}>
                      {upper.status === "available"
                        ? "Downloaded"
                        : upper.status === "incompatible"
                          ? "Wrong forecast hours"
                          : "Not downloaded"}
                    </Yes>
                  )}
                </td>
                <td>
                  {upper.status === "available"
                    ? `q, u, v, t and gh at ${hours(upper.steps_hours)}${upper.members ? ` · ${upper.members} members` : ""}${upper.fetched_at ? ` · ${dateTime(upper.fetched_at)}` : ""}`
                    : upper.status === "not_needed"
                      ? "The model in use reads rainfall only."
                      : upper.status === "not_configured"
                        ? "The forecast hours at which this model's training read the upper-air fields are not supplied, so they are not downloaded."
                        : availability?.upper_air_listed === false
                          ? "Not listed in the ECMWF index for this run."
                          : "Downloaded with the next background forecast run."}
                </td>
              </tr>
              <tr>
                <td className="strong">Acquisition</td>
                <td>
                  {rain.fetched_at ? (
                    <Status tone="ok">Recorded</Status>
                  ) : (
                    <Status tone="planned">None</Status>
                  )}
                </td>
                <td>
                  {rain.fetched_at
                    ? `${dateTime(rain.fetched_at)} · ${rain.fetched_by ?? ""} · ${rain.mirror ? mirrorName(rain.mirror) : ""}${rain.bytes ? ` · ${(rain.bytes / 1e6).toFixed(1)} MB` : ""}`
                    : "—"}
                </td>
              </tr>
              <tr>
                <td className="strong">Input checks (last run)</td>
                <td>
                  {checks.length ? (
                    <Yes ok={!failed}>
                      {failed ? `${failed} failed` : `${checks.length} passed`}
                    </Yes>
                  ) : (
                    <Status tone="planned">Not run yet</Status>
                  )}
                </td>
                <td>
                  {ready.last_run
                    ? `Forecast from the run of ${day(ready.last_run.initialization)}`
                    : "Run the forecast to check every input."}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
      {checks.length > 0 && (
        <Card
          title="Input checks of the last run"
          subtitle="Each input compared with the frozen model's training data. A failed check stops the AI/ML layer; nothing is filled in."
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Result</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c, i) => (
                  <tr key={`${c.check}-${i}`}>
                    <td className="strong">{sentence(c.check)}</td>
                    <td>
                      <Status
                        tone={
                          c.status === "passed"
                            ? "ok"
                            : c.status === "note"
                              ? "info"
                              : "bad"
                        }
                      >
                        {c.status === "note" ? "Noted" : sentence(c.status)}
                      </Status>
                    </td>
                    <td>{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {ready.failures.length > 0 && (
        <Card
          title="Recent failures"
          subtitle="Download and processing tasks that did not finish."
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>What happened</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {ready.failures.map((f, i) => (
                  <tr key={i}>
                    <td className="strong">{f.title}</td>
                    <td>
                      {f.error ?? "Stopped"}
                      {f.retry_at
                        ? ` · retried automatically ${dateTime(f.retry_at)}`
                        : ""}
                    </td>
                    <td style={{ color: "var(--muted)" }}>
                      {f.finished_at ? dateTime(f.finished_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

function Ecmwf({ source }: { source?: DataSource }) {
  const inputs = useApi<EcmwfInput[]>("/data/ecmwf");
  const ready = useApi<EcmwfReadiness>("/data/ecmwf/readiness");
  const [actor] = useActor();
  const [date, setDate] = useState("");
  const { operation, error, running, start } = useOperation(() => {
    inputs.reload();
    ready.reload();
  });
  return (
    <>
      <PageBanner
        title="ECMWF Ensemble (ENS)"
        crumbs={[
          { label: "Data & Tools", href: "/data" },
          { label: "ECMWF ensemble" },
        ]}
        subtitle="The forecast input: the real-time ECMWF ensemble from ECMWF Open Data, 00 UTC run, 0.25°, 15-day range. Only the fields the model reads are downloaded."
        facts={[
          "10 perturbed members, as in training",
          "Days 8–14",
          "Open licence (CC BY 4.0)",
        ]}
      />
      {ready.loading && <Skeleton height={220} />}
      {ready.error && <ErrorState message={ready.error} retry={ready.reload} />}
      {ready.data && <Readiness ready={ready.data} changed={ready.reload} />}
      <div className="grid-2">
        <Card
          title="Download a run"
          subtitle="Leave the date empty for the newest published 00 UTC run (published about 8–9 hours after 00 UTC)."
        >
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              alignItems: "end",
            }}
          >
            <label className="field">
              Initialization date
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            <Button
              variant="green"
              disabled={running}
              onClick={() =>
                start(
                  "fetch_ecmwf",
                  actor || "Forecaster",
                  date ? { initialization: date } : {},
                )
              }
            >
              <Download size={18} /> {running ? "Downloading…" : "Download"}
            </Button>
          </div>
          <div style={{ marginTop: 16 }}>
            <OperationNotice operation={operation} error={error} />
          </div>
        </Card>
        <Card title="How it is processed">
          <ol style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 8 }}>
            <li>
              Total rainfall of perturbed members 1–10 (the ensemble size the
              model was trained on) at 168 h and 336 h; for the AI/ML layer,
              humidity, winds, temperature and geopotential at the model&apos;s
              seven upper-air leads.
            </li>
            <li>
              Each field is checked: the right variable, date, run, member,
              forecast hour and units.
            </li>
            <li>
              The global field is cut to Eastern Africa, averaged to the 1.5°
              grid the model was trained on and interpolated to the 0.05° ICPAC
              grid (see <Link href="/forecasts/raw">Raw ECMWF</Link>).
            </li>
            <li>
              Before the AI/ML layer, every input is compared with the training
              data; a failed check stops it and the forecast is issued from MBC.
            </li>
          </ol>
        </Card>
      </div>
      <Card
        title="Downloaded runs"
        subtitle={
          source
            ? `${source.provider}: ECMWF's own server first, then its archives`
            : undefined
        }
      >
        {inputs.loading && <Skeleton height={160} />}
        {inputs.data && !inputs.data.length && (
          <p style={{ margin: 0 }}>No run downloaded yet.</p>
        )}
        {inputs.data && inputs.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>ECMWF run</th>
                  <th className="num">Members</th>
                  <th>Downloaded from</th>
                  <th className="num">Size</th>
                  <th>Fetched</th>
                </tr>
              </thead>
              <tbody>
                {inputs.data.map((row) => (
                  <tr key={row.id}>
                    <td className="strong">
                      {day(row.initialization)}, 00 UTC
                    </td>
                    <td className="num">{row.members}</td>
                    <td>{mirrorName(row.mirror)}</td>
                    <td className="num">
                      {(row.grib_bytes / 1e6).toFixed(1)} MB
                    </td>
                    <td style={{ color: "var(--muted)" }}>
                      {dateTime(row.fetched_at)} · {row.fetched_by}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Chirps() {
  const windows = useApi<ChirpsWindow[]>("/data/chirps");
  const [actor] = useActor();
  const { operation, error, running, start } = useOperation(() =>
    windows.reload(),
  );
  return (
    <>
      <PageBanner
        title="CHIRPS v2.0"
        crumbs={[{ label: "Data & Tools", href: "/data" }, { label: "CHIRPS" }]}
        subtitle="The verification reference: daily satellite-and-gauge rainfall at 0.05°, on the same grid as the forecast. The final product is used when published, else the preliminary product."
        facts={["0.05° daily", "Africa", "Climate Hazards Center, UCSB"]}
        actions={
          <Button
            variant="amber"
            disabled={running}
            onClick={() => start("verify_due", actor || "Forecaster")}
          >
            <CheckCircle2 size={18} />{" "}
            {running ? "Verifying…" : "Verify finished forecasts"}
          </Button>
        }
      />
      <OperationNotice operation={operation} error={error} />
      <Card
        title="Observed weeks"
        subtitle="Seven daily totals summed over each forecast's Week-2 window."
      >
        {windows.loading && <Skeleton height={160} />}
        {windows.data && !windows.data.length && (
          <p style={{ margin: 0 }}>
            No week observed yet: a forecast&apos;s week is fetched about two
            days after it ends.
          </p>
        )}
        {windows.data && windows.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Products</th>
                  <th className="num">Days</th>
                  <th className="num">Cells without data</th>
                  <th>Fetched</th>
                </tr>
              </thead>
              <tbody>
                {windows.data.map((row) => (
                  <tr key={row.id}>
                    <td className="strong">
                      {validDays(
                        row.valid_start + "T00:00:00Z",
                        row.valid_end + "T00:00:00Z",
                      )}
                    </td>
                    <td>
                      {row.products.map((product) => (
                        <span key={product} style={{ marginRight: 6 }}>
                          <Status
                            tone={product === "final" ? "ok" : "progress"}
                          >
                            {product}
                          </Status>
                        </span>
                      ))}
                    </td>
                    <td className="num">{row.days.length}</td>
                    <td className="num">
                      {Math.max(
                        ...row.days.map((d) => d.missing_domain_cells),
                        0,
                      ).toLocaleString("en-GB")}
                    </td>
                    <td style={{ color: "var(--muted)" }}>
                      {dateTime(row.fetched_at)} · {row.fetched_by}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Product status">
        <KeyValues
          items={[
            [
              "Final",
              "Published about three weeks after the end of each month; replaces the preliminary values.",
            ],
            [
              "Preliminary",
              "Available a few days after each pentad; used for timely verification and labelled as such.",
            ],
            [
              "Missing cells",
              "CHIRPS marks some coastal cells as no data; they are left out of the scores, never filled.",
            ],
          ]}
        />
      </Card>
    </>
  );
}

function Tamsat() {
  const dekads = useApi<Dekad[]>("/monitoring/dekads?source=tamsat");
  const [actor] = useActor();
  const { operation, error, running, start } = useOperation(() =>
    dekads.reload(),
  );
  return (
    <>
      <PageBanner
        title="TAMSAT v3.1"
        crumbs={[{ label: "Data & Tools", href: "/data" }, { label: "TAMSAT" }]}
        subtitle="A second observed-rainfall estimate for the monitoring: dekadal rainfall over Africa from Meteosat thermal-infrared imagery, calibrated against rain gauges, at 0.0375°."
        actions={
          <Button
            variant="amber"
            disabled={running}
            onClick={() => start("update_chirps", actor || "Forecaster")}
          >
            <RefreshCw size={17} className={running ? "spin" : undefined} />
            {running ? "Checking…" : "Check for a new dekad"}
          </Button>
        }
      />
      <OperationNotice operation={operation} error={error} />
      <Card
        title="Downloaded dekads"
        subtitle="Each one is shown on the Monitoring page next to CHIRPS."
      >
        {dekads.loading && <Skeleton height={160} />}
        {dekads.error && (
          <ErrorState message={dekads.error} retry={dekads.reload} />
        )}
        {dekads.data && !dekads.data.length && (
          <p style={{ margin: 0 }}>
            No dekad downloaded yet. The weekly cycle and the daily task look
            for a new one, or use the button above.
          </p>
        )}
        {dekads.data && dekads.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Dekad</th>
                  <th className="num">Regional mean (mm)</th>
                  <th className="num">Below 1 mm</th>
                  <th>Fetched</th>
                </tr>
              </thead>
              <tbody>
                {dekads.data.map((row) => (
                  <tr key={row.dekad}>
                    <td className="strong">
                      <Link href="/monitoring?source=tamsat">
                        {period(row.start, row.end)}
                      </Link>
                    </td>
                    <td className="num">{num(row.region.mean_mm)}</td>
                    <td className="num">
                      {Math.round(row.region.dry_fraction * 100)}%
                    </td>
                    <td style={{ color: "var(--muted)" }}>
                      {dateTime(row.fetched_at)} · {row.fetched_by}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="grid-2">
        <Card title="How it is processed">
          <ol style={{ margin: 0, paddingLeft: 22, display: "grid", gap: 8 }}>
            <li>
              The month&apos;s folder on the TAMSAT server is listed and the
              newest dekad is downloaded once.
            </li>
            <li>
              The file is checked: a rainfall field, dated inside the dekad, on
              TAMSAT&apos;s 0.0375° grid. Gap-filled rainfall is used where
              TAMSAT provides it.
            </li>
            <li>
              It is cut to Eastern Africa, interpolated to the 0.05° ICPAC grid
              and summarised by member state.
            </li>
          </ol>
        </Card>
        <Card title="Use">
          <KeyValues
            items={[
              ["Monitoring", "Dekad totals, next to CHIRPS"],
              [
                "Percent of normal",
                "From CHIRPS; TAMSAT's own 1991–2020 normal is not held",
              ],
              ["Verification", "CHIRPS stays the reference"],
              ["Licence", "CC BY 4.0, University of Reading"],
            ]}
          />
        </Card>
      </div>
    </>
  );
}

function Planned({ source, title }: { source?: DataSource; title: string }) {
  return (
    <>
      <PageBanner
        title={source?.name ?? title}
        crumbs={[{ label: "Data & Tools", href: "/data" }, { label: title }]}
        subtitle={source?.description}
        facts={["Coming later"]}
      />
      <div className="grid-2">
        <InProgress title={`${source?.name ?? title} reader`}>
          This dataset is planned as a further verification reference. Its
          download and reader have not been built yet, so no forecast is
          compared with it. CHIRPS is used until then.
        </InProgress>
        <Card title="About the dataset">
          <KeyValues
            items={[
              ["Provider", source?.provider ?? "—"],
              ["Role", source?.role ?? "verification"],
              [
                "Website",
                source ? (
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.url.replace(/^https?:\/\//, "")}{" "}
                    <ExternalLink size={12} />
                  </a>
                ) : (
                  "—"
                ),
              ],
            ]}
          />
        </Card>
      </div>
      <p>
        <LinkButton href="/data/chirps" variant="outline">
          CHIRPS, the reference in use
        </LinkButton>
      </p>
    </>
  );
}

export default function Source({ route }: PageProps) {
  const id = route.param ?? "ecmwf";
  const sources = useApi<DataSource[]>("/data/sources");
  const source = sources.data?.find((s) => s.id === id);
  return (
    <div className="page">
      <div className="wrap">
        {id === "ecmwf" && <Ecmwf source={source} />}
        {id === "chirps" && <Chirps />}
        {id === "tamsat" && <Tamsat />}
        {id !== "ecmwf" && id !== "chirps" && id !== "tamsat" && (
          <Planned source={source} title={route.title} />
        )}
      </div>
    </div>
  );
}
