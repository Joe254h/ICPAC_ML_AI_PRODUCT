import { expect, test, type Page } from "@playwright/test";

// Every page reads the forecast the cycle setup issued from the ECMWF mirror.

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

async function mapLoaded(page: Page, name: string | RegExp) {
  const map = page.getByRole("img", { name }).first();
  await expect(map).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(() => map.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(500);
}

test("the home page leads with this week's outlook", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "Week-2 Rainfall Forecasts for Eastern Africa",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Our Week-2 Rainfall Outlook" }),
  ).toBeVisible();
  // The hybrid is not produced yet, so its layer is offered as in progress.
  await expect(page.getByText("MBC + AI/ML (in progress)")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Latest Updates" }),
  ).toBeVisible();
  const sources = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Our Data Sources" }),
  });
  await expect(sources.getByText("In use", { exact: true })).toHaveCount(2);
  await expect(sources.getByText("Coming later", { exact: true })).toHaveCount(
    4,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalScroll(page);
});

test("the latest forecast shows its layers, maps and countries", async ({
  page,
}) => {
  await page.goto("/forecasts");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Weekly Forecast for",
  );
  await expect(page.getByText("ECMWF ensemble + MBC").first()).toBeVisible();
  const products = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Forecast products" }),
  });
  await expect(products.getByText("Available", { exact: true })).toHaveCount(2);
  await expect(products.getByText("In progress", { exact: true })).toHaveCount(
    1,
  );
  await mapLoaded(page, "MBC Week-2 rainfall map");
  await expect(
    page.locator("tbody tr").filter({ hasText: "Kenya" }).first(),
  ).toBeVisible();
  await expect(page.getByText("Not verified yet.")).toBeVisible();
});

test("the hybrid layer says what it still needs", async ({ page }) => {
  await page.goto("/forecasts/hybrid");
  await expect(page.getByText("In progress").first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "What is needed to complete it" }),
  ).toBeVisible();
  await expect(
    page.getByText("ecmwf.pressure.week2_steps_hours").first(),
  ).toBeVisible();
});

test("a country page has its own map and figures", async ({ page }) => {
  await page.goto("/countries/kenya");
  await expect(
    page.getByRole("heading", { level: 1, name: "Kenya" }),
  ).toBeVisible();
  await expect(page.getByText("Area mean", { exact: true })).toBeVisible();
  await mapLoaded(page, /Kenya/);
});

test("data sources: ECMWF and CHIRPS are fetched, the others come later", async ({
  page,
}) => {
  await page.goto("/data/ecmwf");
  await expect(
    page.getByRole("heading", { name: "Downloaded runs" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("00 UTC");
  await expect(page.locator("tbody tr").first()).toContainText(
    "127.0.0.1:8998",
  );
  await page.goto("/data/tamsat");
  await expect(
    page.getByRole("heading", { name: "TAMSAT reader" }),
  ).toBeVisible();
  await expect(page.getByText("In progress", { exact: true })).toBeVisible();
});

test("system status reports the downloaded input and the issued forecast", async ({
  page,
}) => {
  await page.goto("/system");
  const row = (name: string) =>
    page.locator(".health-row").filter({ hasText: name });
  await expect(row("ECMWF input")).toContainText("Healthy");
  await expect(row("Operational forecasts")).toContainText("Healthy");
  await expect(row("MBC + AI/ML forecast")).toContainText("In progress");
});
