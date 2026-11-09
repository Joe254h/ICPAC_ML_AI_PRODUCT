import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { request } from "../services/api";
import { useApi } from "../services/hooks";

vi.mock("../services/api", async (original) => ({
  ...(await original<typeof import("../services/api")>()),
  request: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("a late response from a previous forecast cannot replace the selected forecast", async () => {
  let finishOld!: (value: { label: string }) => void;
  const old = new Promise<{ label: string }>((resolve) => {
    finishOld = resolve;
  });
  vi.mocked(request)
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce({ label: "new" });
  const { result, rerender } = renderHook(
    ({ path }) => useApi<{ label: string }>(path),
    {
      initialProps: { path: "/forecasts/old" },
    },
  );
  rerender({ path: "/forecasts/new" });
  await waitFor(() => expect(result.current.data?.label).toBe("new"));
  await act(async () => {
    finishOld({ label: "old" });
    await old;
  });
  expect(result.current.data?.label).toBe("new");
});

test("changing observation sources clears the old source while the new scores load", async () => {
  let finish!: (value: { label: string }) => void;
  vi.mocked(request)
    .mockResolvedValueOnce({ label: "ARC 2.0" })
    .mockReturnValueOnce(
      new Promise<{ label: string }>((resolve) => {
        finish = resolve;
      }),
    );
  const { result, rerender } = renderHook(
    ({ path }) => useApi<{ label: string }>(path),
    {
      initialProps: { path: "/verification/summary?source=arc2" },
    },
  );
  await waitFor(() => expect(result.current.data?.label).toBe("ARC 2.0"));
  rerender({ path: "/verification/summary?source=chirps" });
  expect(result.current.loading).toBe(true);
  expect(result.current.data).toBeUndefined();
  await act(async () => {
    finish({ label: "CHIRPS" });
  });
  await waitFor(() => expect(result.current.data?.label).toBe("CHIRPS"));
});
