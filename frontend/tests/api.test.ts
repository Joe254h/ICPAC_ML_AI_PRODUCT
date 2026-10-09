import { afterEach, expect, test, vi } from "vitest";
import { ApiError, mutate, request } from "../services/api";
afterEach(() => vi.unstubAllGlobals());
test("surfaces API failures instead of inventing data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "QC failed" }),
    }),
  );
  await expect(request("/forecasts/latest")).rejects.toThrow("QC failed");
});
test("keeps the HTTP status so 'nothing yet' can be told apart", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "No forecast yet" }),
    }),
  );
  const error = (await request("/forecasts/latest").catch(
    (e) => e,
  )) as ApiError;
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(404);
});
test("successful typed response is used", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mode: "operational" }),
    }),
  );
  await expect(request("/health")).resolves.toEqual({ mode: "operational" });
});
test("posts JSON bodies", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ id: "op" }) });
  vi.stubGlobal("fetch", fetch);
  await mutate("/operations", { action: "cycle", actor: "Forecaster" });
  expect(fetch).toHaveBeenCalledWith(
    "/api/operations",
    expect.objectContaining({
      method: "POST",
      body: '{"action":"cycle","actor":"Forecaster"}',
    }),
  );
});
