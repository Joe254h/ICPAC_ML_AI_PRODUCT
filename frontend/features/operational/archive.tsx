"use client";
/** Every issued Week-2 forecast, newest first. */
import Link from "next/link";
import {
  Card,
  ErrorState,
  LinkButton,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import { dateTime, day, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ForecastRun } from "@/types/operational";
import { NoForecast, methodName } from "@/features/operational/shared";

export default function Archive() {
  const runs = useApi<ForecastRun[]>("/forecasts");
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecast Archive"
          crumbs={[
            { label: "Forecasts", href: "/forecasts" },
            { label: "Archive" },
          ]}
          subtitle="Every Week-2 forecast issued by the service, with its product package, method and verification status."
          actions={
            <LinkButton href="/data/runs" variant="amber">
              Run a forecast
            </LinkButton>
          }
        />
        {runs.loading && <Skeleton height={360} />}
        {runs.error && <ErrorState message={runs.error} retry={runs.reload} />}
        {runs.data && !runs.data.length && <NoForecast />}
        {runs.data && runs.data.length > 0 && (
          <Card
            title={`${runs.data.length} forecast${runs.data.length === 1 ? "" : "s"}`}
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Valid period (days 8–14)</th>
                    <th>ECMWF run</th>
                    <th>Issued from</th>
                    <th>Input</th>
                    <th>Verification</th>
                    <th>Generated</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {runs.data.map((run, index) => (
                    <tr key={run.forecast_id}>
                      <td className="strong">
                        {validDays(run.valid_start, run.valid_end)}
                        {index === 0 && (
                          <span style={{ marginLeft: 10 }}>
                            <Status tone="info">Latest</Status>
                          </span>
                        )}
                      </td>
                      <td>{day(run.initialization)}, 00 UTC</td>
                      <td>{methodName(run)}</td>
                      <td>{run.input_label}</td>
                      <td>
                        {run.verification_status === "available" ? (
                          <Status tone="ok">Verified · CHIRPS</Status>
                        ) : (
                          <Status tone="progress">Awaiting CHIRPS</Status>
                        )}
                      </td>
                      <td style={{ color: "var(--muted)" }}>
                        {dateTime(run.generation_time)}
                      </td>
                      <td>
                        <Link
                          className="link-amber"
                          href={`/forecasts?id=${run.forecast_id}`}
                        >
                          Open →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
