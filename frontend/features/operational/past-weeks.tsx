"use client";
/**
 * Forecast and verify past weeks: forecasts are made from the ECMWF runs of recent weeks
 * (kept in ECMWF's open archive) and scored against CHIRPS, which has already observed
 * those weeks, so verification scores and maps exist without waiting for new weeks to end.
 */
import Link from "next/link";
import { History } from "lucide-react";
import { Button, Notice } from "@/components/ui";
import { useActor } from "@/lib/actor";
import { useOperation } from "@/services/operations";

export const PAST_WEEKS = 4;

export default function PastWeeks({ onDone }: { onDone?: () => void }) {
  const [actor] = useActor();
  const { operation, running, error, start } = useOperation(() => onDone?.());
  const failed =
    operation?.status === "failed" || operation?.status === "interrupted";
  const result = operation?.result as {
    verified?: string[];
    waiting?: string[];
    failed?: string[];
  } | null;
  const count = (list?: string[]) => list?.length ?? 0;
  const summary =
    operation?.status === "complete" && result
      ? [
          `${count(result.verified)} past weeks verified`,
          count(result.waiting) &&
            `${count(result.waiting)} waiting for CHIRPS`,
          count(result.failed) &&
            `${count(result.failed)} could not be forecast or verified`,
        ]
          .filter(Boolean)
          .join(", ")
      : operation?.messages.at(-1)?.text;
  return (
    <div className="card past-weeks">
      <div className="past-weeks-text">
        <h3>Verify the last {PAST_WEEKS} weeks now</h3>
        <p>
          Forecasts for the last {PAST_WEEKS} weeks that CHIRPS has observed are
          made from the ECMWF runs of that time, with the same model, and scored
          against CHIRPS. This takes a few minutes; this week&apos;s forecast
          stays the current one.
        </p>
      </div>
      <Button
        variant="amber"
        disabled={running}
        onClick={() =>
          start("past_weeks", actor || "Forecaster", { weeks: PAST_WEEKS })
        }
      >
        <History size={18} aria-hidden />{" "}
        {running
          ? "Forecasting and verifying…"
          : "Forecast and verify past weeks"}
      </Button>
      {operation && (
        <Notice tone={failed ? "red" : "green"}>
          {summary} · <Link href="/data/runs">Operations log</Link>
        </Notice>
      )}
      {error && <Notice tone="red">{error}</Notice>}
    </div>
  );
}
