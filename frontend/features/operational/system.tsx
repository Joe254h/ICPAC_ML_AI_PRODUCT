"use client";
/** System › data, model and processing status from the API health check. */
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  LinkButton,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { RunsTable } from "@/features/operational/runs";
import {
  StatusBadge,
  StatusTable,
  parseStatus,
} from "@/features/operational/status";
import { useApi } from "@/services/hooks";
import type { ForecastRun, Health } from "@/types/operational";

const GROUPS: Record<string, (name: string) => boolean> = {
  data: (n) =>
    n.startsWith("Observations") ||
    [
      "Database",
      "Storage",
      "Forecast providers",
      "Operational inputs",
    ].includes(n),
  models: (n) =>
    [
      "Model registry",
      "Operational model",
      "Model registration",
      "Production artifact",
      "LLM",
    ].includes(n),
  processing: (n) =>
    [
      "API",
      "Local executor",
      "SLURM",
      "Latest successful product run",
      "Operational forecasts",
    ].includes(n),
  all: () => true,
};

export default function System({ route }: PageProps) {
  const health = useApi<Health>("/health");
  const runs = useApi<ForecastRun[]>(
    route.param === "processing" ? "/forecasts" : null,
  );
  const select = GROUPS[route.param ?? "all"] ?? GROUPS.all;
  const rows = Object.entries(health.data?.components ?? {}).filter(([name]) =>
    select(name),
  );
  const worst = rows.some(([, v]) => parseStatus(v).level === "Unavailable")
    ? "Unavailable"
    : rows.some(([, v]) => parseStatus(v).level === "Warning")
      ? "Warning"
      : "Healthy";
  return (
    <>
      <PageHeader
        title={route.title}
        description="Live checks reported by the API; a warning names what is not configured"
        badges={health.data ? <StatusBadge level={worst} /> : undefined}
      />
      <Card>
        <CardHeader title="Components" />
        <CardContent>
          {health.loading && !health.data ? (
            <Skeleton className="h-40" />
          ) : health.error ? (
            <ErrorState message={health.error} retry={health.reload} />
          ) : (
            <StatusTable rows={rows} />
          )}
        </CardContent>
      </Card>
      {route.param === "processing" && (
        <Card>
          <CardHeader
            title="Recent forecast runs"
            action={<LinkButton href="/jobs">Pipeline jobs</LinkButton>}
          />
          <CardContent>
            {runs.data?.length ? (
              <RunsTable runs={runs.data.slice(0, 8)} />
            ) : (
              <p className="m-0 text-muted-foreground">No forecast runs yet.</p>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}
