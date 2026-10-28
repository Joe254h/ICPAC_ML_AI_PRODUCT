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
    page.getByText("Complete", { exact: true }).first(),
  ).toBeVisible();
  // The rainfall monitoring follows as its own task; other tests read its dekads.
  await page.getByText("Task history", { exact: true }).click();
  const monitoring = page
    .locator("tbody tr")
    .filter({ hasText: "Update the rainfall monitoring" })
    .first();
  await expect(async () => {
    await page.getByRole("button", { name: "Refresh" }).click();
    await expect(monitoring).toContainText("Complete", { timeout: 3000 });
  }).toPass({ timeout: 240_000 });
  await open.click();
  await page.waitForURL(/\/forecasts\?id=w2-/);
});
