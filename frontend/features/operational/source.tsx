"use client";
/** One data source: ECMWF ensemble, CHIRPS, or a source that is coming later. */
import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, Download, ExternalLink } from "lucide-react";
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
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { useActor } from "@/lib/actor";
import { dateTime, day, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import { useOperation } from "@/services/operations";
import type {
  ChirpsWindow,
  DataSource,
  EcmwfInput,
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
  return "Local copy";
}

function Ecmwf({ source }: { source?: DataSource }) {
  const inputs = useApi<EcmwfInput[]>("/data/ecmwf");
  const [actor] = useActor();
  const [date, setDate] = useState("");
  const { operation, error, running, start } = useOperation(() =>
    inputs.reload(),
  );
  return (
    <>
      <PageBanner
        title="ECMWF Ensemble (ENS)"
        crumbs={[
          { label: "Data & Tools", href: "/data" },
          { label: "ECMWF ensemble" },
        ]}
        subtitle="The forecast input: the real-time ECMWF ensemble from ECMWF Open Data, 00 UTC run, 0.25°, 15-day range. Only the Week-2 rainfall is downloaded."
        facts={["50 ensemble members", "Days 8–14", "Open licence (CC BY 4.0)"]}
      />
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
              Only the total rainfall of the 50 ensemble members at days 7 and
              14 is downloaded, as the model was trained; nothing else is
              fetched.
            </li>
            <li>
              Each field is checked: the right variable, date, run, member,
              forecast hour and units.
            </li>
            <li>
              The global field is cut to Eastern Africa and kept as the forecast
              input.
            </li>
            <li>
              The forecast averages it to the 1.5° grid the model was trained
              on, then interpolates it to the 0.05° ICPAC grid (see{" "}
              <Link href="/forecasts/raw">Raw ECMWF</Link>).
            </li>
          </ol>
        </Card>
      </div>
      <Card
        title="Downloaded runs"
        subtitle={
          source
            ? `${source.provider}: ECMWF's own server first, then its archive on Amazon Web Services`
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
        {id !== "ecmwf" && id !== "chirps" && (
          <Planned source={source} title={route.title} />
        )}
      </div>
    </div>
  );
}
