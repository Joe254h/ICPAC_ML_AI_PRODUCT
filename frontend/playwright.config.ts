import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Browser tests run the real service: a local mirror (ECMWF Open Data GRIB2 files and
// indexes for yesterday's 00 UTC run, and the newest CHIRPS dekad laid out as on the CHC
// server), the API on a fresh database, and the web app.
const state = process.env.E2E_STATE ?? path.join(os.tmpdir(), "icpac-e2e");
const mirror = "http://127.0.0.1:8998";

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3000",
    channel: process.env.LOCAL_BROWSER ?? undefined,
    // A browser already on the machine instead of Playwright's download.
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : undefined,
  },
  projects: [
    // Issues this week's forecast through the Operations page; every other test reads it.
    { name: "cycle", testMatch: /cycle\.setup\.ts/ },
    { name: "app", dependencies: ["cycle"], testIgnore: /cycle\.setup\.ts/ },
  ],
  webServer: [
    {
      command: `python -m backend.tests.ecmwf_mirror --root ${path.join(state, "mirror")} --port 8998`,
      cwd: "..",
      url: mirror + "/",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `rm -rf ${path.join(state, "service")} && mkdir -p ${path.join(state, "service")} && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`,
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        DATABASE_URL: `sqlite:///${path.join(state, "service", "icpac.db")}`,
        RUN_ROOT: path.join(state, "service", "runs"),
        FORECAST_INPUT_ROOT: path.join(state, "service", "inputs"),
        DATA_ROOT: path.join(state, "service", "data"),
        ECMWF_OPENDATA_MIRRORS: mirror,
        CHIRPS_BASE_URL: mirror + "/chc",
        LLM_PROVIDER: "mock",
      },
    },
    {
      command: "pnpm dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !process.env.CI,
    },
  ],
  timeout: 90_000,
});
