/* eslint-disable @typescript-eslint/no-require-imports */
/* global process, console, require, fetch, document */
// Screenshots of the running workspace for docs/screenshots.
// Usage (API on :8000 with ALLOW_SYNTHETIC_FORECASTS=true, frontend on :3000):
//   node scripts/capture-preview.cjs [output-directory]
// LOCAL_BROWSER=chrome uses an installed Chrome; CHROMIUM_PATH points at a binary.
const { chromium } = require("@playwright/test");
const fs = require("node:fs/promises");
const path = require("node:path");

const API = process.env.API_URL || "http://127.0.0.1:8000";
const WEB = "http://127.0.0.1:3000";

async function ensureForecast() {
  const latest = await fetch(API + "/forecasts/latest");
  if (latest.ok) return;
  const run = await fetch(API + "/forecasts/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      initialization: new Date().toISOString().slice(0, 10),
      source: "synthetic_fixture",
      actor: "Screenshot capture",
    }),
  });
  if (!run.ok)
    throw new Error("Could not create a forecast: " + (await run.text()));
}

async function imagesLoaded(page) {
  await page.waitForFunction(
    () => {
      const images = [...document.querySelectorAll("main img")];
      return (
        images.length > 0 &&
        images.every((i) => i.complete && i.naturalWidth > 0)
      );
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
    ["overview", "/", true],
    ["forecast", "/forecasts", true],
    ["maps", "/maps/rainfall", true],
    ["country", "/countries/kenya", true],
    ["models", "/models", false],
    ["verification", "/verification", false],
  ];
  for (const [name, url, maps] of shots) {
    await page.goto(WEB + url);
    await page.locator("main h1").first().waitFor();
    if (maps) await imagesLoaded(page);
    else await page.waitForLoadState("networkidle");
    await page.screenshot({
      path: path.join(output, name + ".png"),
      fullPage: name !== "overview",
    });
  }
  await page.goto(WEB + "/copilot");
  await page
    .getByLabel("Ask Forecaster Copilot")
    .fill("Compare CHIRPS and TAMSAT for Somalia.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.locator(".chat-message.assistant").waitFor({ timeout: 60000 });
  await page.screenshot({
    path: path.join(output, "copilot.png"),
    fullPage: true,
  });
  await page.goto(WEB + "/bulletin");
  await page.locator("main h1").first().waitFor();
  await page.waitForLoadState("networkidle");
  await page.screenshot({
    path: path.join(output, "bulletins.png"),
    fullPage: true,
  });
  await page.goto(WEB + "/");
  await imagesLoaded(page);
  await page.getByLabel("Toggle theme").click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(output, "dark.png") });
  await page.getByLabel("Toggle theme").click();
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto(WEB + "/");
  await imagesLoaded(page);
  await page.screenshot({ path: path.join(output, "tablet.png") });
  await browser.close();
  console.log("Saved screenshots to " + output);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
