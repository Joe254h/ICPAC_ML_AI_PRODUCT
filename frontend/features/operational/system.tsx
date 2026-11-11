"use client";
/** System status: every part of the service from the API health check. */
import Link from "next/link";
import { RotateCw } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import type { Tone } from "@/components/ui";
import { useApi } from "@/services/hooks";
import type { Health } from "@/types/operational";

type Level = "Healthy" | "Warning" | "Unavailable" | "In progress";

const TONE: Record<Level, Tone> = {
  Healthy: "ok",
  Warning: "progress",
  Unavailable: "bad",
  "In progress": "info",
};

/** A component line reads "Level · detail". */
function parse(value: string): { level: Level; detail: string } {
  const [head, ...rest] = value.split(" · ");
  if (head in TONE) return { level: head as Level, detail: rest.join(" · ") };
  return { level: "Healthy", detail: value };
}

const GROUPS: {
  title: string;
  text: string;
  names: string[];
  link?: [string, string];
}[] = [
  {
    title: "Data inputs",
    text: "The ensemble the forecast is made from, the observations it is verified against and the rainfall monitoring.",
    names: ["ECMWF input", "CHIRPS verification", "CHIRPS monitoring"],
    link: ["/data", "Data sources"],
  },
  {
    title: "Forecasts and models",
    text: "The weekly runs and the registered model that corrects them.",
    names: [
      "Operational forecasts",
      "Operational model",
      "Model registration",
      "MBC + AI/ML forecast",
    ],
    link: ["/models", "Model registry"],
  },
  {
    title: "Platform",
    text: "The service itself, its records and its storage.",
    names: ["API", "Database", "Storage", "Copilot language model"],
  },
];

function Row({ name, value }: { name: string; value: string }) {
  const { level, detail } = parse(value);
  return (
    <div className="health-row">
      <div>
        <strong>{name}</strong>
        {detail && <span>{detail}</span>}
      </div>
      <Status tone={TONE[level]}>{level}</Status>
    </div>
  );
}

type Feedback = {
  current: string;
  versions: Record<string, { helpful: number; unhelpful: number }>;
  unhelpful: {
    question: string;
    note: string;
    at: string;
    provider?: string;
    agent_version: string;
  }[];
};

/** How people rated the Copilot's answers, by agent version (its instructions and tools),
 * with the latest unhelpful questions to review. Shown to administrators only. */
function CopilotFeedback() {
  const feedback = useApi<Feedback>("/chat/feedback");
  if (!feedback.data) return null;
  const versions = Object.entries(feedback.data.versions);
  return (
    <Card
      title="Copilot answers"
      subtitle="Marks people gave the answers, for the Copilot's current instructions and tools and earlier ones. Review the unhelpful ones to improve the prompts and tools."
    >
      {versions.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No answer has been marked yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Instructions and tools</th>
              <th>Helpful</th>
              <th>Not helpful</th>
            </tr>
          </thead>
          <tbody>
            {versions.map(([version, row]) => (
              <tr key={version}>
                <td>
                  {version === feedback.data?.current
                    ? "Current"
                    : "An earlier version"}
                </td>
                <td>{row.helpful}</td>
                <td>{row.unhelpful}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {feedback.data.unhelpful.length > 0 && (
        <details className="card-details">
          <summary>
            Latest unhelpful answers ({feedback.data.unhelpful.length})
          </summary>
          <ul>
            {feedback.data.unhelpful.map((row) => (
              <li key={`${row.at}-${row.question}`}>
                “{row.question}”{row.note && <> · {row.note}</>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

export default function System() {
  const health = useApi<Health>("/health");
  const components = health.data?.components ?? {};
  const grouped = new Set(GROUPS.flatMap((g) => g.names));
  const other = Object.keys(components).filter((name) => !grouped.has(name));
  const levels = Object.values(components).map((v) => parse(v).level);
  const count = (level: Level) => levels.filter((l) => l === level).length;
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="System Status"
          crumbs={[
            { label: "Operations", href: "/data/runs" },
            { label: "System status" },
          ]}
          subtitle="Live checks of inputs, runs, models and platform."
          actions={
            <Button variant="outline" onClick={health.reload}>
              <RotateCw size={16} /> Check again
            </Button>
          }
        />
        {health.loading && !health.data && <Skeleton height={420} />}
        {health.error && (
          <ErrorState message={health.error} retry={health.reload} />
        )}
        {health.data && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Overall</div>
                <div className="value" style={{ fontSize: 26 }}>
                  {health.data.status === "Healthy"
                    ? "All systems working"
                    : "Needs attention"}
                </div>
              </div>
              <div className="stat">
                <div className="label">Healthy</div>
                <div className="value">{count("Healthy")}</div>
              </div>
              <div className="stat amber">
                <div className="label">Warnings</div>
                <div className="value">
                  {count("Warning") + count("Unavailable")}
                </div>
              </div>
              <div className="stat">
                <div className="label">In progress</div>
                <div className="value">{count("In progress")}</div>
              </div>
            </div>
            {count("Unavailable") > 0 && (
              <Notice tone="red" title="Unavailable components.">
                Forecasts that depend on them cannot be issued until they are
                fixed; see the details below.
              </Notice>
            )}
            {GROUPS.map((group) => {
              const names = group.names.filter((name) => name in components);
              if (!names.length) return null;
              return (
                <Card
                  key={group.title}
                  title={group.title}
                  subtitle={group.text}
                  action={
                    group.link && (
                      <Link className="link-amber" href={group.link[0]}>
                        {group.link[1]} →
                      </Link>
                    )
                  }
                >
                  <div className="health-list">
                    {names.map((name) => (
                      <Row key={name} name={name} value={components[name]} />
                    ))}
                  </div>
                </Card>
              );
            })}
            {other.length > 0 && (
              <Card title="Other checks">
                <div className="health-list">
                  {other.map((name) => (
                    <Row key={name} name={name} value={components[name]} />
                  ))}
                </div>
              </Card>
            )}
            <CopilotFeedback />
            <p style={{ color: "var(--muted)", fontSize: 14 }}>
              Tasks that download data or run forecasts are listed in{" "}
              <Link href="/data/runs">Operations</Link>.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
