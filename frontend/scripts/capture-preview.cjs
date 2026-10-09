/* eslint-disable @typescript-eslint/no-require-imports */
/* global process, console, require, fetch, document, setTimeout */
// Screenshots of the running service for docs/screenshots.
// Usage (API on :8000, frontend on :3000):
//   node scripts/capture-preview.cjs [output-directory]
// Without a forecast yet, the weekly cycle is run first: the API downloads the newest
// ECMWF ensemble (or reads the mirror in ECMWF_OPENDATA_MIRRORS) and issues the forecast.
// LOCAL_BROWSER=chrome uses an installed Chrome; CHROMIUM_PATH points at a binary.
const { chromium } = require("@playwright/test");
const fs = require("node:fs/promises");
const path = require("node:path");

const API = process.env.API_URL || "http://127.0.0.1:8000";
const WEB = "http://127.0.0.1:3000";

async function ensureForecast() {
  const latest = await fetch(API + "/forecasts/latest");
  if (latest.ok) return;
  const started = await fetch(API + "/operations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "cycle", actor: "Screenshot capture" }),
  });
  if (!started.ok)
    throw new Error(
      "Could not start the weekly cycle: " + (await started.text()),
    );
  const { id } = await started.json();
  for (let i = 0; i < 300; i++) {
    const operation = await (await fetch(`${API}/operations/${id}`)).json();
    if (operation.status === "complete") return;
    if (operation.status === "failed" || operation.status === "interrupted")
      throw new Error("The weekly cycle failed: " + operation.error);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("The weekly cycle did not finish in ten minutes");
}

async function imagesLoaded(page) {
  await page.waitForFunction(
    () => {
      const images = [...document.querySelectorAll("main img")];
      return images.every((i) => i.complete && i.naturalWidth > 0);
    },
    null,
    { timeout: 90000 },
  );
}

(async () => {
  const output = path.resolve(process.argv[2] || "../docs/screenshots");
  await fs.mkdir(output, { recursive: true });
  await ensureForecast();
  const browser = await chromium.launch({
    channel: process.env.LOCAL_BROWSER || undefined,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    timezoneId: "Africa/Nairobi",
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.error(error.message));
  const shots = [
    ["overview", "/", false],
    ["forecast", "/forecasts", true],
    ["maps", "/maps/rainfall", true],
    ["country", "/countries/kenya", true],
    ["bulletin", "/bulletin", true],
    ["verification", "/verification", true],
    ["models", "/models", true],
    ["data", "/data", true],
    ["operations", "/data/runs", true],
    ["system", "/system", true],
  ];
  for (const [name, url, fullPage] of shots) {
    await page.goto(WEB + url);
    await page.locator("h1").first().waitFor();
    await page.waitForLoadState("networkidle");
    await imagesLoaded(page);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(output, name + ".png"), fullPage });
  }
  await page.goto(WEB + "/copilot");
  await page
    .getByRole("button", {
      name: "Explain the forecast for Kenya.",
      exact: true,
    })
    .click();
  await page.locator(".chat-message.assistant").waitFor({ timeout: 60000 });
  await page.screenshot({
    path: path.join(output, "copilot.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(WEB + "/");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(output, "mobile.png") });
  await browser.close();
  console.log("Saved screenshots to " + output);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
