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
  // The hero is the live map with the forecast period as its title.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    /^\d{1,2}(–| [A-Z][a-z]+ – )\d{1,2} [A-Z][a-z]+ \d{4}$/,
  );
  const layers = page.getByRole("group", { name: "Forecast layer" });
  await expect(layers.getByRole("button", { name: /^MBC$/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // The hybrid is not produced yet, so its layer is offered as in progress.
  await expect(
    layers.getByRole("button", { name: /MBC \+ AI\/ML/ }),
  ).toBeDisabled();
  await expect(page.locator(".country-card")).toHaveCount(11);
  await expect(
    page.getByRole("heading", { name: "Observed rainfall" }),
  ).toBeVisible();
  await expect(page.getByText("Wettest country").first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "From the ensemble to the bulletin" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalScroll(page);
});

test("rainfall monitoring shows the newest CHIRPS dekad", async ({ page }) => {
  await page.goto("/monitoring");
  await expect(
    page.getByRole("heading", { level: 1, name: "Rainfall Monitoring" }),
  ).toBeVisible();
  await expect(
    page.locator("tbody tr").filter({ hasText: "Kenya" }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Percent of normal/ }),
  ).toBeDisabled();
  await expect(
    page.getByRole("heading", { name: "Percent of normal" }),
  ).toBeVisible();
});

test("no page shows code, identifiers or checksums", async ({ page }) => {
  const code =
    /w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}|[a-z0-9]+_[a-z0-9_]+_v\d|\.ya?ml\b|python -m|sha-?256|\b[0-9a-f]{20,}\b|\{"|week2_steps|max\(|\bHybrid7\b|-candidate\.\d|\bby startup\b|\.(nc|tif|json|py)\b|\b[A-Z][A-Z0-9]*_[A-Z0-9_]{2,}\b/;
  for (const path of [
    "/",
    "/forecasts",
    "/forecasts/hybrid",
    "/forecasts/archive",
    "/countries",
    "/countries/kenya",
    "/maps/rainfall",
    "/monitoring",
    "/verification",
    "/bulletin",
    "/bulletins",
    "/models",
    "/data",
    "/data/ecmwf",
    "/data/chirps",
    "/data/runs",
    "/system",
    "/copilot",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    expect(text.match(code)?.[0] ?? "", path).toBe("");
  }
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
    page.getByText(/upper-air \(pressure-level\) fields/).first(),
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
  await expect(page.locator("tbody tr").first()).toContainText("Local copy");
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
  await expect(row("CHIRPS monitoring")).toContainText("Healthy");
});
