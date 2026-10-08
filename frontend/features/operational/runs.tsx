"use client";
/** Week-2 forecast history; on Data > Forecast runs also the run and import forms. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Play, Upload } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  ModelStatus,
  Notice,
  PageHeader,
  Skeleton,
  SyntheticBadge,
  Table,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import type { PageProps } from "@/features/view";
import { dateTime, day, validDays } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { ForecastRun } from "@/types/operational";

const field =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-foreground";

function RunForm({ done }: { done: (run: ForecastRun) => void }) {
  const { config } = useApp();
  const synthetic = !!config.data?.operational?.synthetic_runs_allowed;
  const stepsReady = !!config.data?.operational?.pressure_steps_configured;
  const [initialization, setInitialization] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [source, setSource] = useState<"ecmwf_files" | "synthetic_fixture">(
    "ecmwf_files",
  );
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Card>
      <CardHeader
        title="Run a forecast"
        description="Runs the model in use (production, else the newest candidate) for one initialization"
      />
      <CardContent className="grid gap-4">
        {!stepsReady && source === "ecmwf_files" && (
          <Notice tone="warning">
            Real Atmos37 runs stop at a missing scientific setting: the seven
            Week-2 pressure-level steps used in training
            (ecmwf.pressure.week2_steps_hours). The backend refuses to guess
            them.
          </Notice>
        )}
        <form
          className="grid gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              done(
                await mutate<ForecastRun>("/forecasts/run", {
                  initialization,
                  source,
                  actor,
                }),
              );
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="grid gap-1.5 text-muted-foreground">
            Initialization (00 UTC)
            <input
              className={field}
              type="date"
              required
              value={initialization}
              onChange={(e) => setInitialization(e.target.value)}
            />
          </label>
          <label className="grid gap-1.5 text-muted-foreground">
            Input
            <select
              className={field}
              aria-label="Forecast input"
              value={source}
              onChange={(e) =>
                setSource(e.target.value as "ecmwf_files" | "synthetic_fixture")
              }
            >
              <option value="ecmwf_files">ECMWF S2S files</option>
              {synthetic && (
                <option value="synthetic_fixture">
                  Synthetic demonstration input
                </option>
              )}
            </select>
          </label>
          <label className="grid gap-1.5 text-muted-foreground">
            Your name
            <input
              className={field}
              required
              minLength={2}
              maxLength={80}
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              aria-label="Your name"
            />
          </label>
          <Button variant="primary" type="submit" busy={busy}>
            <Play size={15} />
            {busy ? "Running…" : "Run forecast"}
          </Button>
        </form>
        {busy && (
          <p className="m-0 text-muted-foreground" role="status">
            Week-2 processing, MBC, Atmos37 features, CatBoost and maps: about
            15–60 seconds on the full 800 × 700 grid.
          </p>
        )}
        {source === "synthetic_fixture" && (
          <p className="m-0 text-[0.9rem] text-muted-foreground">
            Synthetic input exercises the real model and maps end to end; every
            output is labelled synthetic and is not a forecast of real weather.
          </p>
        )}
        {error && <ErrorState message={error} />}
      </CardContent>
    </Card>
  );
}

function ImportForm({ done }: { done: (run: ForecastRun) => void }) {
  const [forecastId, setForecastId] = useState("");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Card>
      <CardHeader
        title="Import an HPC product package"
        description="A package written by scripts/run_operational.py into RUN_ROOT/forecasts; checksums, model artifacts and the status label are checked first"
      />
      <CardContent className="grid gap-3">
        <form
          className="grid gap-4 md:grid-cols-[2fr_1fr_auto] md:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              done(
                await mutate<ForecastRun>("/forecasts/import", {
                  forecast_id: forecastId.trim(),
                  actor,
                }),
              );
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="grid gap-1.5 text-muted-foreground">
            Forecast ID
            <input
              className={field}
              required
              placeholder="w2-2026-10-05-1a2b3c4d"
              pattern="w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}"
              value={forecastId}
              onChange={(e) => setForecastId(e.target.value)}
            />
          </label>
          <label className="grid gap-1.5 text-muted-foreground">
            Your name
            <input
              className={field}
              required
              minLength={2}
              maxLength={80}
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          <Button type="submit" busy={busy}>
            <Upload size={15} />
            Import
          </Button>
        </form>
        {error && <ErrorState message={error} />}
      </CardContent>
    </Card>
  );
}

export function RunsTable({ runs }: { runs: ForecastRun[] }) {
  return (
    <Table
      head={[
        "Initialization",
        "Valid (Days 8–14)",
        "Model",
        "Input",
        "Verification",
        "Origin",
        "Generated",
        "",
      ]}
    >
      {runs.map((run) => (
        <tr key={run.forecast_id}>
          <td className="whitespace-nowrap font-medium">
            {day(run.initialization)}
          </td>
          <td className="whitespace-nowrap">
            {validDays(run.valid_start, run.valid_end)}
          </td>
          <td>
            <div className="grid gap-1">
              <span className="truncate">{run.model_id}</span>
              <ModelStatus status={run.model_status} />
            </div>
          </td>
          <td>
            {run.synthetic ? <SyntheticBadge /> : <Badge>ECMWF S2S</Badge>}
          </td>
          <td>
            <Badge
              tone={
                run.verification_status === "available" ? "good" : "neutral"
              }
            >
              {run.verification_status === "available"
                ? `Verified${run.season ? " · " + run.season : ""}`
                : "Not verified"}
            </Badge>
          </td>
          <td className="text-muted-foreground">
            {run.origin === "import" ? "HPC package" : "Platform run"}
          </td>
          <td className="whitespace-nowrap text-muted-foreground">
            {dateTime(run.generation_time)}
          </td>
          <td>
            <Link
              href={"/forecasts?id=" + run.forecast_id}
              className="font-medium text-primary hover:underline"
            >
              Open
            </Link>
          </td>
        </tr>
      ))}
    </Table>
  );
}

export default function Runs({ route }: PageProps) {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const router = useRouter();
  const { refresh } = useApp();
  const manage = route.page === "data-runs";
  const opened = (run: ForecastRun) => {
    refresh();
    router.push("/forecasts?id=" + run.forecast_id);
  };
  return (
    <>
      <PageHeader
        title={manage ? "Forecast runs" : "Week-2 forecasts"}
        description={
          manage
            ? "Run the operational model, import HPC packages and review every forecast produced"
            : "Every Week-2 forecast the platform holds, newest initialization first"
        }
      />
      {manage && (
        <div className="grid gap-6 xl:grid-cols-2">
          <RunForm done={opened} />
          <ImportForm done={opened} />
        </div>
      )}
      <Card>
        <CardHeader
          title="Forecast history"
          description="Synthetic runs stay labelled; the latest real forecast is preferred on the overview"
        />
        <CardContent>
          {runs.loading && !runs.data ? (
            <Skeleton className="h-40" />
          ) : runs.error ? (
            <ErrorState message={runs.error} retry={runs.reload} />
          ) : runs.data?.length ? (
            <RunsTable runs={runs.data} />
          ) : (
            <EmptyState title="No forecasts yet">
              {manage
                ? "Run a forecast above or import a package produced on the HPC."
                : "Forecasts are created under Data › Forecast runs."}
            </EmptyState>
          )}
        </CardContent>
      </Card>
    </>
  );
}
