import { expect, test } from "@playwright/test";

test("workspace and country links retain a chosen forecast week", async ({
  page,
}) => {
  let runs: {
    latest?: boolean;
    of_record?: boolean;
    forecast_id: string;
  }[] = [];
  // A busy/cold API can return a temporary 503. Wait for a real fixture list
  // before navigating; do not treat an error object as forecast records.
  await expect(async () => {
    const response = await page.request.get("/api/forecasts");
    expect(response.ok()).toBe(true);
    const records = await response.json();
    expect(Array.isArray(records)).toBe(true);
    expect(records.length).toBeGreaterThan(0);
    runs = records;
  }).toPass({ timeout: 60_000, intervals: [1000, 2000, 5000] });
  const chosen =
    runs.find(
      (run: { latest?: boolean; of_record?: boolean }) =>
        !run.latest && run.of_record !== false,
    ) ?? runs[0];
  expect(chosen.forecast_id).toBeTruthy();
  const query = `?id=${chosen.forecast_id}`;
  await page.goto("/forecasts" + query);
  const workflow = page.getByRole("navigation", { name: "Forecast workflow" });
  await workflow.getByRole("link", { name: "All member states" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/countries\\?id=${chosen.forecast_id}$`),
  );
  const country = page.locator(".country-card").first();
  await expect(country).toHaveAttribute(
    "href",
    new RegExp(`id=${chosen.forecast_id}$`),
  );
  await country.click();
  await expect(page).toHaveURL(
    new RegExp(`/countries/[^?]+\\?id=${chosen.forecast_id}$`),
  );
  await workflow.getByRole("link", { name: "Rainfall maps" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/maps/rainfall\\?id=${chosen.forecast_id}$`),
  );
  await expect(
    page.getByRole("heading", { name: "Rainfall Maps", level: 1 }),
  ).toBeVisible();
  await workflow.getByRole("link", { name: "Weekly bulletin" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/bulletin\\?id=${chosen.forecast_id}$`),
  );
  await expect(
    page.getByRole("heading", { name: "Total Rainfall" }),
  ).toBeVisible();
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    ).toBeLessThanOrEqual(1);
  }
});

test("draft translation recovers after reload and a temporary API failure", async ({
  page,
}) => {
  const created = await page.request.post("/api/bulletins/generate", {
    data: { actor: "Browser QA" },
  });
  expect(created.ok()).toBeTruthy();
  const draft = await created.json();
  const stored = await page.request.get("/api/bulletins").then((r) => r.json());
  const translated = {
    ...draft,
    id: "qa-translated-version",
    version: (draft.version ?? 1) + 1,
    edited: { language: "Kiswahili", summary: "Browser recovery fixture" },
  };
  let submissions = 0;
  let recover = false;
  let completed = false;
  await page.route("**/api/bulletins", (route) =>
    route.fulfill({ json: completed ? [translated, ...stored] : stored }),
  );
  await page.route(`**/api/bulletins/${draft.id}/translations`, (route) => {
    submissions += 1;
    return route.fulfill({
      json: { id: "qa-translation", status: "running", done: 0, total: 4 },
    });
  });
  await page.route("**/api/bulletins/translations/qa-translation", (route) => {
    if (!recover)
      return route.fulfill({
        status: 503,
        json: { detail: "Temporary API failure" },
      });
    completed = true;
    return route.fulfill({
      json: {
        id: "qa-translation",
        status: "done",
        done: 4,
        total: 4,
        version_id: translated.id,
      },
    });
  });
  await page.route("**/api/bulletins/qa-translated-version", (route) =>
    route.fulfill({ json: translated }),
  );
  await page.goto(`/bulletins?id=${draft.id}`);
  await page.getByRole("button", { name: "Translate this draft" }).click();
  await expect(
    page.getByRole("button", { name: /Translating/ }),
  ).toBeDisabled();
  await expect(
    page.locator(".draft-translate").getByRole("alert"),
  ).toContainText("Temporary API failure");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Recovering translation…" }),
  ).toBeDisabled();
  await expect(
    page.locator(".draft-translate").getByRole("alert"),
  ).toContainText(
    "Connection interrupted; recovering the translation shortly.",
  );
  recover = true;
  await expect(page).toHaveURL(/id=qa-translated-version/, { timeout: 30_000 });
  await expect(
    page.getByText("Kiswahili version.", { exact: true }),
  ).toBeVisible();
  expect(submissions).toBe(1);
});
