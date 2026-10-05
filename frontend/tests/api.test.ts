import { afterEach, expect, test, vi } from "vitest";
import { request, query } from "../services/api";
afterEach(() => vi.unstubAllGlobals());
test("surfaces API failures instead of inventing data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "QC failed" }),
    }),
  );
  await expect(request("/analysis")).rejects.toThrow("QC failed");
});
test("successful typed response is used", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mode: "synthetic" }),
    }),
  );
  await expect(request("/health")).resolves.toEqual({ mode: "synthetic" });
});
test("encodes source and country selection", () =>
  expect(
    query({
      cycle: "2026-09-28",
      provider: "ECMWF S2S",
      model: "mock-v1",
      observation: "TAMSAT",
      country: "South Sudan",
      layer: "raw",
    }),
  ).toContain("country=South+Sudan"));
