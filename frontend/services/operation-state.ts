import type { Operation } from "@/types/operational";

/** Older backends persist a retry as failed plus retry_at; it is still active work. */
export function operationActive(operation: Operation): boolean {
  return (
    operation.status === "queued" ||
    operation.status === "running" ||
    (operation.status === "failed" && !!operation.retry_at)
  );
}

export function operationLabel(operation: Operation): string {
  return operation.status === "failed" && operation.retry_at
    ? "Waiting for retry"
    : operation.status;
}
