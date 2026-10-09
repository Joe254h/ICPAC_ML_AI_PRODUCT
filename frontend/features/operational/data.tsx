"use client";
/** Data sources: those in use and those coming later. */
import Link from "next/link";
import { ExternalLink } from "lucide-react";
import {
  Card,
  ErrorState,
  LinkButton,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { dateTime, day } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ChirpsWindow, DataSource, EcmwfInput } from "@/types/operational";

function latestText(source: DataSource): string {
  if (!source.latest) return "Nothing fetched yet";
  if (source.id === "ecmwf") {
    const latest = source.latest as EcmwfInput;
    return `Latest: run of ${day(latest.initialization)} · fetched ${dateTime(latest.fetched_at)}`;
  }
  const latest = source.latest as ChirpsWindow;
  return `Latest: week from ${day(latest.valid_start)} · fetched ${dateTime(latest.fetched_at)}`;
}

function SourceCard({ source }: { source: DataSource }) {
  const active = source.status === "active";
  return (
    <article
      className="card"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          alignItems: "start",
        }}
      >
        <div>
          <p className="eyebrow" style={{ marginBottom: 4 }}>
            {source.role}
          </p>
          <h3 style={{ fontSize: 22 }}>{source.name}</h3>
        </div>
        {active ? (
          <Status tone="ok">In use</Status>
        ) : (
          <Status tone="planned">Coming later</Status>
        )}
      </div>
      <p style={{ margin: 0 }}>{source.description}</p>
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 14 }}>
        {source.provider} ·{" "}
        <a href={source.url} target="_blank" rel="noreferrer">
          website <ExternalLink size={12} style={{ verticalAlign: -1 }} />
        </a>
      </p>
      {active && (
        <p style={{ margin: 0, fontSize: 14, color: "var(--green-800)" }}>
          {latestText(source)} · {source.fetched ?? 0} on record
        </p>
      )}
      <div style={{ marginTop: "auto", paddingTop: 8 }}>
        <Link className="link-amber" href={`/data/${source.id}`}>
          {active ? "Open data page →" : "Details →"}
        </Link>
      </div>
    </article>
  );
}

export default function Data() {
  const sources = useApi<DataSource[]>("/data/sources");
  const active = sources.data?.filter((s) => s.status === "active") ?? [];
  const planned = sources.data?.filter((s) => s.status !== "active") ?? [];
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Data Sources"
          crumbs={[{ label: "Data & Tools" }, { label: "Data sources" }]}
          subtitle="The forecast is made from the ECMWF ensemble and verified against CHIRPS, both downloaded by this service. Further observation datasets will be added."
          actions={
            <LinkButton href="/data/runs" variant="amber">
              Operations
            </LinkButton>
          }
        />
        {sources.loading && <Skeleton height={260} />}
        {sources.error && (
          <ErrorState message={sources.error} retry={sources.reload} />
        )}
        {active.length > 0 && (
          <Card
            title="In use"
            subtitle="Downloaded, checked and processed automatically."
          >
            <div className="grid-2">
              {active.map((source) => (
                <SourceCard key={source.id} source={source} />
              ))}
            </div>
          </Card>
        )}
        {planned.length > 0 && (
          <Card
            title="Coming later"
            subtitle="Listed so forecasters know what is planned; their readers have not been built yet, so nothing is computed from them."
          >
            <div className="grid-2">
              {planned.map((source) => (
                <SourceCard key={source.id} source={source} />
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
