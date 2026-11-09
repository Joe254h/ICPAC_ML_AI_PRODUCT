import { act, renderHook, cleanup } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { Operation } from "../types/operational";
import { operationActive, operationLabel } from "../services/operation-state";
import { useOperation } from "../services/operations";
import { ApiError, mutate, request } from "../services/api";

vi.mock("../services/api", async (original) => ({
  ...(await original<typeof import("../services/api")>()),
  request: vi.fn(),
  mutate: vi.fn(),
}));

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
  sessionStorage.clear();
  vi.useRealTimers();
  vi.resetAllMocks();
});

test("reload follows the saved job to its completed result without posting", async () => {
  sessionStorage.setItem(
    "icpac-operation-reload",
    JSON.stringify({ operation: record }),
  );
  vi.mocked(request).mockResolvedValue({
    ...record,
    status: "complete",
    retry_at: null,
  });
  const done = vi.fn();
  const hook = renderHook(() => useOperation(done, "reload"));
  await act(async () => {});
  expect(hook.result.current.running).toBe(false);
  expect(hook.result.current.operation?.status).toBe("complete");
  expect(mutate).not.toHaveBeenCalled();
  expect(done).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem("icpac-operation-reload")).toBeNull();
});

test("a lost POST response and reload reuse the saved submission identity", async () => {
  vi.useFakeTimers();
  vi.mocked(request).mockResolvedValueOnce({ idempotent_submission: true });
  vi.mocked(mutate).mockRejectedValueOnce(new TypeError("response lost"));
  const first = renderHook(() => useOperation(undefined, "lost-post"));
  await act(async () => {
    await first.result.current.start("past_weeks", "Joe254h");
  });
  const firstBody = vi.mocked(mutate).mock.calls[0][1];
  expect(first.result.current.running).toBe(true);
  first.unmount();
  vi.mocked(mutate).mockResolvedValueOnce({
    ...record,
    status: "complete",
    retry_at: null,
  });
  vi.mocked(request)
    .mockResolvedValueOnce({ idempotent_submission: true })
    .mockResolvedValueOnce({
      ...record,
      status: "complete",
      retry_at: null,
    });
  const second = renderHook(() => useOperation(undefined, "lost-post"));
  await act(async () => {});
  expect(mutate).toHaveBeenCalledTimes(2);
  expect(vi.mocked(mutate).mock.calls[1][1]).toEqual(firstBody);
  expect(second.result.current.running).toBe(false);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(mutate).toHaveBeenCalledTimes(2);
});

test.each([{}, new ApiError("Unknown operation", 404)])(
  "a frontend released before its backend cannot submit unsafe retries (%s)",
  async (response) => {
    if (response instanceof Error)
      vi.mocked(request).mockRejectedValueOnce(response);
    else vi.mocked(request).mockResolvedValueOnce(response);
    const hook = renderHook(() => useOperation(undefined, "old-backend"));
    await act(async () => {
      await hook.result.current.start("past_weeks", "Joe254h");
    });
    expect(mutate).not.toHaveBeenCalled();
    expect(hook.result.current.running).toBe(false);
    expect(hook.result.current.error).toContain("service is being updated");
    expect(sessionStorage.getItem("icpac-operation-old-backend")).toBeNull();
  },
);

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

test("a transient API failure reconnects to the same task and clears its warning", async () => {
  vi.useFakeTimers();
  vi.mocked(request)
    .mockRejectedValueOnce(new TypeError("connection reset"))
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
  expect(hook.result.current.error).toContain("checking again");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(hook.result.current.operation?.status).toBe("complete");
  expect(hook.result.current.error).toBeNull();
  expect(finished).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenNthCalledWith(2, "/operations/retry-job");
});

test("a late response cannot switch tracking back to an earlier task", async () => {
  let finishOld!: (value: Operation) => void;
  vi.mocked(request)
    .mockReturnValueOnce(
      new Promise<Operation>((resolve) => {
        finishOld = resolve;
      }),
    )
    .mockResolvedValueOnce({
      ...record,
      id: "new",
      status: "complete",
      retry_at: null,
    });
  const finished = vi.fn();
  const hook = renderHook(() => useOperation(finished));
  await act(async () => {
    hook.result.current.follow(record);
  });
  await act(async () => {
    hook.result.current.follow({ ...record, id: "new" });
  });
  await act(async () => {
    finishOld(record);
  });
  expect(hook.result.current.operation?.id).toBe("new");
  expect(hook.result.current.running).toBe(false);
  expect(finished).toHaveBeenCalledTimes(1);
});
