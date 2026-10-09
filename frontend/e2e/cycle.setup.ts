import { expect, test as setup } from "@playwright/test";

// The weekly cycle as a forecaster runs it: download the newest ECMWF ensemble (from the
// local mirror), issue the Week-2 forecast and verify what is due.
setup("the weekly cycle issues this week's forecast", async ({ page }) => {
  setup.setTimeout(300_000);
  await page.goto("/data/runs");
  await page.getByLabel("Your name").fill("Browser forecaster");
  await page
    .getByRole("button", { name: "Run the weekly cycle", exact: true })
    .click();
  const open = page.getByRole("link", { name: "Open forecast →" }).first();
  await expect(open).toBeVisible({ timeout: 280_000 });
  await expect(
    page.getByText("complete", { exact: true }).first(),
  ).toBeVisible();
  await open.click();
  await page.waitForURL(/\/forecasts\?id=w2-/);
});
