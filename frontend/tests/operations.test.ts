import { act, renderHook, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Operation } from "../types/operational";
import { operationActive, operationLabel } from "../services/operation-state";
import { useOperation } from "../services/operations";
import { request } from "../services/api";

vi.mock("../services/api", () => ({ request: vi.fn(), mutate: vi.fn() }));

const record: Operation = {
  id: "retry-job",
  action: "end_to_end",
  title: "Connected workflow",
  status: "failed",
  initialization: "2026-10-18",
  forecast_id: null,
  created_at: "2026-10-18T09:00:00Z",
  created_by: "Operator",
  messages: [],
  result: null,
  error: "503 Slow Down",
  retry_at: "2026-10-18T09:15:00Z",
  attempts: 1,
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

test("a persisted failed task with a scheduled retry is active work", () => {
  expect(operationActive(record)).toBe(true);
  expect(operationLabel(record)).toBe("Waiting for retry");
  expect(operationActive({ ...record, retry_at: null })).toBe(false);
});

test("polling follows recovery without a page refresh or a duplicate submission", async () => {
  vi.useFakeTimers();
  vi.mocked(request)
    .mockResolvedValueOnce(record)
    .mockResolvedValueOnce({
      ...record,
      status: "complete",
      retry_at: null,
      error: null,
    });
  const finished = vi.fn();
  const hook = renderHook(() => useOperation(finished));
  await act(async () => {
    hook.result.current.follow(record);
  });
  expect(hook.result.current.running).toBe(true);
  expect(finished).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(hook.result.current.operation?.status).toBe("complete");
  expect(hook.result.current.running).toBe(false);
  expect(finished).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledTimes(2);
});
