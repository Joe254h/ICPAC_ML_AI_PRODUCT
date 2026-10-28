import type { Operation } from "@/types/operational";

/** Older backends persist a retry as failed plus retry_at; it is still active work. */
export function operationActive(operation: Operation): boolean {
  return (
    operation.status === "queued" ||
    operation.status === "running" ||
    (operation.status === "failed" && !!operation.retry_at)
  );
}

const LABELS: Record<Operation["status"], string> = {
  queued: "Queued",
  running: "Running",
  complete: "Complete",
  failed: "Failed",
  interrupted: "Interrupted",
  cancelled: "Stopped",
};

export function operationLabel(operation: Operation): string {
  if (operation.status === "failed" && operation.retry_at)
    return "Waiting for retry";
  if (operation.stop_requested && operationActive(operation)) return "Stopping";
  return LABELS[operation.status] ?? operation.status;
}
