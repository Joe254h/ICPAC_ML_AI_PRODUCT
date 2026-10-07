import { test, expect } from "@playwright/test";

// End to end: synthetic ECMWF S2S input -> Week-2 processing -> MBC -> Atmos37
// features -> the registered CatBoost candidate -> package and maps -> API -> display.
test("a synthetic forecast run is displayed with its labels, maps and countries", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.goto("/data/runs");
  await page.getByLabel("Forecast input").selectOption("synthetic_fixture");
  await page.getByLabel("Your name").first().fill("Browser forecaster");
  await page.getByRole("button", { name: "Run forecast", exact: true }).click();
  await page.waitForURL(/\/forecasts\?id=w2-/, { timeout: 200_000 });

  await expect(
    page.getByText("Synthetic input · not a real forecast").first(),
  ).toBeVisible();
  await expect(
    page.getByText("Candidate · not production").first(),
  ).toBeVisible();
  for (const name of ["Raw ECMWF", "MBC", "MBC + AI"]) {
    const map = page.getByRole("img", {
      name: `${name} Week-2 rainfall`,
      exact: true,
    });
    await expect(map).toBeVisible();
    await expect
      .poll(() => map.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(1000);
  }
  const rows = page.locator("tbody tr").filter({ hasText: "Kenya" });
  await expect(rows.first()).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("MBC + AI · domain mean")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Validation skill of the model" }),
  ).toBeVisible();
  await page.goto("/countries/kenya");
  await expect(page.getByText("MBC + AI · mean")).toBeVisible();
  await expect(page.getByText("Anomaly: unavailable")).toBeVisible();
});
