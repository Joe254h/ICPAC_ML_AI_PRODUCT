"use client";
/** Start background operations and follow them until they finish. */
import { useCallback, useEffect, useRef, useState } from "react";
import { mutate, request } from "@/services/api";
import type { Operation, OperationAction } from "@/types/operational";
import { operationActive } from "@/services/operation-state";

export function useOperation(onFinished?: (operation: Operation) => void) {
  const [operation, setOperation] = useState<Operation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const done = useRef(onFinished);
  done.current = onFinished;

  const poll = useCallback((id: string) => {
    request<Operation>("/operations/" + id)
      .then((record) => {
        setOperation(record);
        if (!operationActive(record)) done.current?.(record);
        else
          timer.current = setTimeout(
            () => poll(id),
            record.retry_at ? 15000 : 2000,
          );
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const start = useCallback(
    async (
      action: OperationAction,
      actor: string,
      extra: {
        initialization?: string;
        forecast_id?: string;
        weeks?: number;
      } = {},
    ) => {
      setError(null);
      if (timer.current) clearTimeout(timer.current);
      try {
        const record = await mutate<Operation>("/operations", {
          action,
          actor,
          ...extra,
        });
        setOperation(record);
        poll(record.id);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [poll],
  );

  const follow = useCallback(
    (record: Operation) => {
      setOperation(record);
      if (timer.current) clearTimeout(timer.current);
      if (operationActive(record)) poll(record.id);
    },
    [poll],
  );

  const running = operation !== null && operationActive(operation);
  return { operation, error, running, start, follow };
}
