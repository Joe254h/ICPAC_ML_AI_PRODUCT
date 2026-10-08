"use client";
/** Data › ECMWF: the forecast input contract and whether real runs can work. */
import { FileCode2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  KeyValues,
  Notice,
  PageHeader,
  Skeleton,
} from "@/components/ui";
import { useApp } from "@/components/shell";
import { StatusTable } from "@/features/operational/status";
import { useApi } from "@/services/hooks";
import type { Health } from "@/types/operational";

export default function DataEcmwf() {
  const health = useApi<Health>("/health");
  const { config } = useApp();
  const caps = config.data?.operational;
  const rows = Object.entries(health.data?.components ?? {}).filter(([name]) =>
    [
      "Operational inputs",
      "Forecast providers",
      "Operational forecasts",
    ].includes(name),
  );
  return (
    <>
      <PageHeader
        title="ECMWF S2S forecast input"
        description="Extended-range ensemble files read by the platform; nothing is downloaded by the web application"
      />
      {caps && !caps.pressure_steps_configured && (
        <Notice tone="warning">
          Missing scientific dependency: the seven Week-2 pressure-level steps
          used for the Atmos37 training features
          (ecmwf.pressure.week2_steps_hours in config/operational.yaml). Real
          Atmos37 runs stop at this setting until the HPC team supplies it.
        </Notice>
      )}
      <Card>
        <CardHeader
          title="Input status"
          description="From the API health check"
        />
        <CardContent>
          {health.loading && !health.data ? (
            <Skeleton className="h-24" />
          ) : health.error ? (
            <ErrorState message={health.error} retry={health.reload} />
          ) : (
            <StatusTable rows={rows} />
          )}
        </CardContent>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <FileCode2 size={17} /> Rainfall file
              </span>
            }
            description="FORECAST_INPUT_ROOT/ecmwf_s2s_tp_<YYYY-MM-DD>.nc (or .zarr)"
          />
          <CardContent className="pt-3">
            <KeyValues
              items={[
                ["Variable", "tp, accumulated from initialization"],
                ["Dimensions", "number, step, latitude, longitude"],
                [
                  "Members",
                  "ECMWF numbering; control (0) is excluded, perturbed 1..N used",
                ],
                [
                  "Steps",
                  "must include 168 h and 336 h (Week-2 = tp(336) − tp(168))",
                ],
                [
                  "Units",
                  "kg m**-2 or mm (1:1), or m (× 1000); anything else stops the run",
                ],
                [
                  "Grid",
                  "the 0.05° model grid (800 × 700); other grids need the regrid setting",
                ],
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <FileCode2 size={17} /> Pressure-level file (Atmos37)
              </span>
            }
            description="FORECAST_INPUT_ROOT/ecmwf_s2s_pl_<YYYY-MM-DD>.nc (or .zarr)"
          />
          <CardContent className="pt-3">
            <KeyValues
              items={[
                ["Variables", "q, u, v, t, gh"],
                ["Levels", "850, 700, 500 and 200 hPa (isobaricInhPa)"],
                ["Steps", "the seven Week-2 steps of the training definition"],
                ["Units", "kg kg**-1, m s**-1, K, gpm (declared in the file)"],
                [
                  "Processing",
                  "bilinear to the model grid, derived fields, seven-step mean per member, then ensemble mean and spread",
                ],
                [
                  "Synthetic runs",
                  caps?.synthetic_runs_allowed
                    ? "Allowed on this deployment (labelled synthetic)"
                    : "Disabled on this deployment",
                ],
              ]}
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
