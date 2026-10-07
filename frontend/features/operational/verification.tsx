"use client";
/** Verification: seasonal skill of the model in use, verifying forecasts, demo runs. */
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Skeleton,
  Table,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import type { PageProps } from "@/features/view";
import { MetricsTable } from "@/features/operational/shared";
import { RunsTable } from "@/features/operational/runs";
import { dateTime, day, num, signed } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { ForecastRun, Seasonal } from "@/types/operational";

const field =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-foreground";

type DemoVerification = {
  id: string;
  created_at: string;
  selection: {
    country: string;
    observation: string;
    model: string;
    cycle: string;
  };
  metrics: {
    rmse: number;
    mae: number;
    bias: number;
    correlation: number | null;
  };
};

function VerifyForm({
  runs,
  preselect,
  done,
}: {
  runs: ForecastRun[];
  preselect?: string;
  done: () => void;
}) {
  const open = runs.filter((r) => r.verification_status !== "available");
  const [forecastId, setForecastId] = useState(
    preselect && open.some((r) => r.forecast_id === preselect)
      ? preselect
      : (open[0]?.forecast_id ?? ""),
  );
  const [observation, setObservation] = useState("");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  return (
    <Card>
      <CardHeader
        title="Verify a forecast"
        description="Observed CHIRPS Week-2 total (mm) on the 800 × 700 grid for exactly the forecast's valid window, as a NetCDF file inside DATA_ROOT"
      />
      <CardContent className="grid gap-3">
        {!open.length ? (
          <p className="m-0 text-muted-foreground">
            Every forecast is already verified, or none exists yet.
          </p>
        ) : (
          <form
            className="grid gap-4 md:grid-cols-[2fr_2fr_1fr_auto] md:items-end"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              setMessage("");
              try {
                await mutate(`/forecasts/${forecastId}/verification`, {
                  observation: observation.trim(),
                  actor,
                });
                setMessage("Verification recorded in the forecast package.");
                done();
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="grid gap-1.5 text-muted-foreground">
              Forecast
              <select
                className={field}
                value={forecastId}
                onChange={(e) => setForecastId(e.target.value)}
              >
                {open.map((run) => (
                  <option key={run.forecast_id} value={run.forecast_id}>
                    {day(run.initialization)} · {run.model_id}
                    {run.synthetic ? " · synthetic" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-muted-foreground">
              Observation file (inside DATA_ROOT)
              <input
                className={field}
                required
                placeholder="chirps_week2_2026-10-12.nc"
                pattern="[A-Za-z0-9_./-]+\.nc"
                value={observation}
                onChange={(e) => setObservation(e.target.value)}
              />
            </label>
            <label className="grid gap-1.5 text-muted-foreground">
              Your name
              <input
                className={field}
                required
                minLength={2}
                value={actor}
                onChange={(e) => setActor(e.target.value)}
              />
            </label>
            <Button variant="primary" type="submit" busy={busy}>
              <ShieldCheck size={15} />
              Verify
            </Button>
          </form>
        )}
        {message && <Notice tone="good">{message}</Notice>}
        {error && <ErrorState message={error} />}
      </CardContent>
    </Card>
  );
}

function SeasonalCard() {
  const [protectedPeriod, setProtectedPeriod] = useState(false);
  const seasonal = useApi<Seasonal>(
    "/verification/seasonal?include_protected=" + protectedPeriod,
  );
  const seasons = Object.entries(seasonal.data?.seasons ?? {});
  return (
    <Card>
      <CardHeader
        title="Seasonal skill of the model in use"
        description={
          seasonal.data
            ? `${seasonal.data.model_id} · ${seasonal.data.scope} · ${seasonal.data.use}`
            : "Pooled over every verified forecast of each season"
        }
        action={
          <label className="inline-flex items-center gap-2 text-muted-foreground">
            <input
              type="checkbox"
              className="accent-primary"
              checked={protectedPeriod}
              onChange={(e) => setProtectedPeriod(e.target.checked)}
            />
            Include 2022–2024 (display only)
          </label>
        }
      />
      <CardContent className="grid gap-5">
        {seasonal.loading && !seasonal.data ? (
          <Skeleton className="h-32" />
        ) : seasonal.status === 404 ? (
          <p className="m-0 text-muted-foreground">
            No operational model registered.
          </p>
        ) : seasonal.error ? (
          <ErrorState message={seasonal.error} retry={seasonal.reload} />
        ) : !seasons.length ? (
          <EmptyState
            icon={<ShieldCheck size={28} />}
            title="No verified forecasts yet"
          >
            Seasonal MAE, RMSE, bias and correlation appear once forecasts are
            verified against CHIRPS.
            {seasonal.data?.excluded_protected_period
              ? ` ${seasonal.data.excluded_protected_period} verified forecasts fall in the protected test period.`
              : ""}
          </EmptyState>
        ) : (
          seasons.map(([season, metrics]) => (
            <div key={season} className="grid gap-2">
              <h3 className="m-0 font-semibold">{season}</h3>
              <MetricsTable metrics={metrics} />
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

export default function Verification({ id }: PageProps) {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const demo = useApi<DemoVerification[]>("/verification");
  const { current } = useApp();
  const verified = (runs.data ?? []).filter(
    (r) => r.verification_status === "available",
  );
  return (
    <>
      <PageHeader
        title="Verification"
        description="MAE, RMSE, bias and Pearson correlation against CHIRPS, per forecast, per country and pooled by season. The 2022–2024 test period never feeds model selection."
        badges={
          current.data && (
            <Badge tone="info">
              Model in use: {current.data.model.model_id}
            </Badge>
          )
        }
      />
      <SeasonalCard />
      {runs.data && (
        <VerifyForm
          runs={runs.data}
          preselect={id}
          done={() => {
            runs.reload();
          }}
        />
      )}
      <Card>
        <CardHeader title="Verified forecasts" />
        <CardContent>
          {runs.error ? (
            <ErrorState message={runs.error} retry={runs.reload} />
          ) : verified.length ? (
            <RunsTable runs={verified} />
          ) : (
            <p className="m-0 text-muted-foreground">None yet.</p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader
          title="Demonstration verification runs"
          description="Synthetic demonstration grid (Workspace › Demonstration); not operational skill"
        />
        <CardContent>
          {demo.error ? (
            <ErrorState message={demo.error} retry={demo.reload} />
          ) : demo.data?.length ? (
            <Table
              head={[
                "Saved",
                "Country",
                "Observation",
                "Model",
                "RMSE",
                "MAE",
                "Bias",
                "r",
              ]}
            >
              {demo.data.map((row) => (
                <tr key={row.id} className="tabular">
                  <td className="whitespace-nowrap">
                    {dateTime(row.created_at)}
                  </td>
                  <td>{row.selection.country}</td>
                  <td>{row.selection.observation}</td>
                  <td>{row.selection.model}</td>
                  <td>{num(row.metrics.rmse, 2)}</td>
                  <td>{num(row.metrics.mae, 2)}</td>
                  <td>{signed(row.metrics.bias, 2)}</td>
                  <td>{num(row.metrics.correlation, 3)}</td>
                </tr>
              ))}
            </Table>
          ) : (
            <p className="m-0 text-muted-foreground">
              No demonstration runs saved.
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
