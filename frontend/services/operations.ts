"use client";
/** Start background operations and follow them until they finish. */
import { useCallback, useEffect, useRef, useState } from "react";
import { mutate, request } from "@/services/api";
import type { Operation, OperationAction } from "@/types/operational";

const FINISHED = new Set(["complete", "failed", "interrupted"]);

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
        if (FINISHED.has(record.status)) done.current?.(record);
        else timer.current = setTimeout(() => poll(id), 2000);
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
      extra: { initialization?: string; forecast_id?: string } = {},
    ) => {
      setError(null);
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
      if (!FINISHED.has(record.status)) poll(record.id);
    },
    [poll],
  );

  const running = operation !== null && !FINISHED.has(operation.status);
  return { operation, error, running, start, follow };
}
