"use client";
/** Data › CHIRPS: observations for verification and the demonstration datasets. */
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  ErrorState,
  KeyValues,
  PageHeader,
  Skeleton,
  Table,
} from "@/components/ui";
import { useApi } from "@/services/hooks";

type Dataset = {
  id: string;
  name?: string;
  mode?: string;
  status?: string;
  checksum?: string;
  [key: string]: unknown;
};

export default function DataChirps() {
  const datasets = useApi<Dataset[]>("/observations");
  return (
    <>
      <PageHeader
        title="CHIRPS observations"
        description="Observed Week-2 totals verify forecasts; they are never used to fit or select a model in the application"
      />
      <Card>
        <CardHeader
          title="Verification input"
          description="One file per forecast window, placed inside DATA_ROOT and named in Verification"
        />
        <CardContent className="pt-3">
          <KeyValues
            items={[
              ["Format", "NetCDF, variable precipitation_week2 in mm"],
              [
                "Grid",
                "the 800 × 700 model grid (same latitude and longitude as forecast.nc)",
              ],
              [
                "Window",
                "attributes valid_start and valid_end equal to the forecast's valid window",
              ],
              [
                "Storage",
                "the observed field is kept in the forecast package as observation.nc",
              ],
              [
                "Test period",
                "windows in 2022–2024 are verified for display only",
              ],
            ]}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader
          title="Demonstration observation datasets"
          description="Synthetic sources of the demonstration grid (Workspace › Demonstration)"
        />
        <CardContent>
          {datasets.loading && !datasets.data ? (
            <Skeleton className="h-24" />
          ) : datasets.error ? (
            <ErrorState message={datasets.error} retry={datasets.reload} />
          ) : (
            <Table head={["Source", "Mode", "Checksum"]}>
              {(datasets.data ?? []).map((row) => (
                <tr key={row.id}>
                  <td className="font-medium">{row.id}</td>
                  <td>
                    <Badge tone={row.mode === "local" ? "good" : "neutral"}>
                      {String(row.mode ?? "synthetic")}
                    </Badge>
                  </td>
                  <td>
                    <code className="text-[0.85rem] text-muted-foreground">
                      {String(row.checksum ?? "—").slice(0, 16)}
                    </code>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
