/* eslint-disable @typescript-eslint/no-require-imports */
/* global process, console, require */
const { chromium } = require("@playwright/test");
const fs = require("node:fs/promises");
const path = require("node:path");
(async () => {
  const output = path.resolve(process.argv[2] || "../docs/screenshots");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    channel: process.env.LOCAL_BROWSER || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
    timezoneId: "Africa/Nairobi",
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.error(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") console.error(message.text());
  });
  for (const view of [
    "overview",
    "verification",
    "models",
    "copilot",
    "bulletins",
  ]) {
    await page.goto(
      "http://127.0.0.1:3000/" + (view === "overview" ? "" : view),
    );
    await page.locator(".filters select").first().waitFor();
    if (view === "overview" || view === "verification") {
      await page.locator(".stats").waitFor();
      await page
        .locator(".map[data-rendered-cells]:not([data-rendered-cells='0'])")
        .waitFor({ timeout: 60000 });
    }
    if (view === "copilot") {
      await page
        .getByLabel("Ask Forecaster Copilot")
        .fill("Compare CHIRPS and TAMSAT for Somalia.");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await page.locator(".chat-message.assistant").waitFor();
    }
    if (view === "models")
      await page.locator(".product-card").first().waitFor();
    if (view === "bulletins") await page.locator(".preview-heading").waitFor();
    await page.screenshot({
      path: path.join(output, view + ".png"),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("http://127.0.0.1:3000/");
  await page
    .locator(".map[data-rendered-cells]:not([data-rendered-cells='0'])")
    .waitFor({ timeout: 60000 });
  await page.screenshot({
    path: path.join(output, "tablet.png"),
    fullPage: true,
  });
  await browser.close();
  console.log("Saved screenshots to " + output);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
