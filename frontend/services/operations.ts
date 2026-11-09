"use client";
/** Start background operations and follow them until they finish. */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, mutate, request } from "@/services/api";
import type { Operation, OperationAction } from "@/types/operational";
import { operationActive } from "@/services/operation-state";

type Submission = {
  action: OperationAction;
  actor: string;
  request_id: string;
  initialization?: string;
  forecast_id?: string;
  weeks?: number;
  model_id?: string;
};

function save(key: string | undefined, value: unknown) {
  if (!key) return;
  try {
    if (value === null) sessionStorage.removeItem("icpac-operation-" + key);
    else
      sessionStorage.setItem("icpac-operation-" + key, JSON.stringify(value));
  } catch {
    // Operation tracking still works when browser storage is restricted.
  }
}

export function useOperation(
  onFinished?: (operation: Operation) => void,
  recoveryKey?: string,
) {
  const [operation, setOperation] = useState<Operation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingNow = useRef(false);
  const alive = useRef(true);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const done = useRef(onFinished);
  done.current = onFinished;

  const poll = useCallback(
    (id: string, token: number = generation.current) => {
      request<Operation>("/operations/" + id)
        .then((record) => {
          if (!alive.current || token !== generation.current) return;
          setError(null);
          setOperation(record);
          save(
            recoveryKey,
            operationActive(record) ? { operation: record } : null,
          );
          if (!operationActive(record)) done.current?.(record);
          else
            timer.current = setTimeout(
              () => poll(id, token),
              record.retry_at ? 15000 : 2000,
            );
        })
        .catch((e: Error) => {
          if (!alive.current || token !== generation.current) return;
          if (e instanceof ApiError && [401, 403, 404].includes(e.status)) {
            setError(e.message);
            setOperation(null);
            save(recoveryKey, null);
            return;
          }
          // A lost connection says nothing about the server task's state. Keep its
          // identifier and reconnect, without posting another operation.
          setError(
            `Connection interrupted; checking again shortly. ${e.message}`,
          );
          timer.current = setTimeout(() => poll(id, token), 5000);
        });
    },
    [recoveryKey],
  );

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      generation.current += 1;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const submit = useCallback(
    async (body: Submission, token: number) => {
      try {
        const updating =
          "The forecast service is being updated. Please try this task again once the update finishes.";
        let compatible = false;
        try {
          const capability = await request<{ idempotent_submission?: boolean }>(
            "/operations/capabilities",
          );
          compatible = capability.idempotent_submission === true;
        } catch (e) {
          if (e instanceof ApiError && e.status === 404)
            throw new ApiError(updating, 409);
          throw e;
        }
        if (!compatible) throw new ApiError(updating, 409);
        if (!alive.current || token !== generation.current) return;
        const record = await mutate<Operation>("/operations", body);
        if (!alive.current || token !== generation.current) return;
        submittingNow.current = false;
        setSubmitting(false);
        setOperation(record);
        save(recoveryKey, { operation: record });
        poll(record.id, token);
      } catch (e) {
        if (!alive.current || token !== generation.current) return;
        if (e instanceof ApiError && e.status < 500 && e.status !== 429) {
          submittingNow.current = false;
          setSubmitting(false);
          save(recoveryKey, null);
          setError(e.message);
          return;
        }
        // The server may already have accepted this POST. Reuse its identity.
        setError(
          "Connection interrupted; recovering the same submission shortly.",
        );
        timer.current = setTimeout(() => submit(body, token), 5000);
      }
    },
    [poll, recoveryKey],
  );

  useEffect(() => {
    if (!recoveryKey) return;
    try {
      const saved = JSON.parse(
        sessionStorage.getItem("icpac-operation-" + recoveryKey) ?? "null",
      );
      const token = ++generation.current;
      if (saved?.operation?.id && operationActive(saved.operation)) {
        setOperation(saved.operation);
        poll(saved.operation.id, token);
      } else if (saved?.request?.request_id) {
        submittingNow.current = true;
        setSubmitting(true);
        void submit(saved.request, token);
      }
    } catch {
      save(recoveryKey, null);
    }
  }, [recoveryKey, poll, submit]);

  const start = useCallback(
    async (
      action: OperationAction,
      actor: string,
      extra: Omit<Submission, "action" | "actor" | "request_id"> = {},
    ) => {
      if (submittingNow.current || (operation && operationActive(operation)))
        return;
      submittingNow.current = true;
      setSubmitting(true);
      const token = ++generation.current;
      setError(null);
      if (timer.current) clearTimeout(timer.current);
      const body = {
        action,
        actor,
        ...extra,
        request_id: crypto.randomUUID().replaceAll("-", ""),
      };
      save(recoveryKey, { request: body });
      await submit(body, token);
    },
    [submit, recoveryKey, operation],
  );

  const follow = useCallback(
    (record: Operation) => {
      const token = ++generation.current;
      submittingNow.current = false;
      setSubmitting(false);
      setError(null);
      setOperation(record);
      save(recoveryKey, operationActive(record) ? { operation: record } : null);
      if (timer.current) clearTimeout(timer.current);
      if (operationActive(record)) poll(record.id, token);
    },
    [poll, recoveryKey],
  );

  /** Ask the followed task to stop: a queued one stops at once, a running one at its
   * next step. */
  const stop = useCallback(
    async (actor: string) => {
      if (!operation) return;
      const token = ++generation.current;
      if (timer.current) clearTimeout(timer.current);
      setError(null);
      try {
        const record = await mutate<Operation>(
          `/operations/${operation.id}/stop`,
          { actor },
        );
        if (!alive.current || token !== generation.current) return;
        setOperation(record);
        save(
          recoveryKey,
          operationActive(record) ? { operation: record } : null,
        );
        if (operationActive(record)) poll(record.id, token);
        else done.current?.(record);
      } catch (e) {
        if (!alive.current || token !== generation.current) return;
        setError((e as Error).message);
        poll(operation.id, token);
      }
    },
    [operation, poll, recoveryKey],
  );

  const running =
    submitting || (operation !== null && operationActive(operation));
  return { operation, error, running, start, follow, stop };
}
