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
  await expect(page.getByText("Wettest country").first()).toBeVisible();
  // Why it can be trusted: the independent test's figure, from the verification data.
  const trust = page.locator("section.trust");
  await expect(
    trust.getByRole("heading", {
      name: "Corrected, checked and reviewed every week",
    }),
  ).toBeVisible();
  await expect(trust).toContainText(/\d+% lower error than raw ECMWF/);
  // The final refit is in use: its 2022–2024 cases are said to be unseen, not independent.
  await expect(trust).toContainText("551 forecast cases from 2022 to 2024");
  await expect(
    page.getByRole("heading", { name: "How each week's forecast is made" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalScroll(page);
});

test("a header menu opens on click and its pages are links", async ({
  page,
}) => {
  await page.goto("/");
  // Forecast data appear after hydration; background basemap requests need not finish.
  await expect(page.locator(".country-card")).toHaveCount(11);
  const nav = page.getByRole("navigation", { name: "Main" });
  const forecasts = nav.getByRole("button", { name: "Forecasts" });
  await forecasts.click();
  await expect(forecasts).toHaveAttribute("aria-expanded", "true");
  // Moving the pointer away keeps a clicked menu open.
  await page.mouse.move(5, 600);
  const archive = nav.getByRole("link", { name: "Forecast archive" });
  await expect(archive).toBeVisible();
  await archive.click();
  await expect(page).toHaveURL(/\/forecasts\/archive$/);
  // A second click closes it; Escape does too.
  const tools = nav.getByRole("button", { name: "Operations" });
  await tools.click();
  await expect(nav.getByRole("link", { name: "Data sources" })).toBeVisible();
  await tools.click();
  await expect(nav.getByRole("link", { name: "Data sources" })).toBeHidden();
  await tools.click();
  await page.keyboard.press("Escape");
  await expect(tools).toHaveAttribute("aria-expanded", "false");
  // Every page is in the menus: the member states under their own heading.
  await nav.getByRole("button", { name: "Countries" }).click();
  await expect(nav.getByText("Member states", { exact: true })).toBeVisible();
  await nav.getByRole("link", { name: "South Sudan" }).click();
  await expect(page).toHaveURL(/\/countries\/south-sudan$/);
  await nav.getByRole("button", { name: "Countries" }).click();
  await nav.getByRole("link", { name: "All member states" }).click();
  await expect(page).toHaveURL(/\/countries$/);
});

test("rainfall monitoring shows the newest dekad of all five estimates", async ({
  page,
}) => {
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
  // TAMSAT, ARC 2.0, RFE 2.0 and GPM IMERG are one switch away, compared with CHIRPS.
  const estimate = page.getByRole("group", { name: "Rainfall estimate" });
  await estimate.getByRole("button", { name: "TAMSAT" }).click();
  await expect(page).toHaveURL(/source=tamsat/);
  await expect(page.getByText(/TAMSAT v3\.1/).first()).toBeVisible();
  await expect(
    page.locator("tbody tr").filter({ hasText: "Kenya" }).first(),
  ).toBeVisible();
  const compare = page.locator(".card").filter({
    has: page.getByRole("heading", { name: "The estimates compared" }),
  });
  await expect(compare.locator("tbody tr")).toHaveCount(5);
  // The daily estimates are summed into the same dekad.
  for (const name of ["ARC 2.0", "RFE 2.0", "GPM IMERG"])
    await expect(
      compare.locator("tbody tr").filter({ hasText: name }),
    ).toContainText("%");
  await estimate.getByRole("button", { name: "GPM IMERG" }).click();
  await expect(page).toHaveURL(/source=imerg/);
  await expect(
    page.getByText(/IMERG Late Run daily totals/).first(),
  ).toBeVisible();
  await expect(
    page.locator("tbody tr").filter({ hasText: "Kenya" }).first(),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await noHorizontalScroll(page);
});

test("past weeks are forecast and verified, and the correlation map appears", async ({
  page,
}) => {
  test.setTimeout(300_000);
  await page.goto("/maps/correlation");
  await expect(
    page.getByText(
      /needs at least 3 verified forecasts of the model in use; 0 are verified/,
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Forecast and verify past weeks" })
    .click();
  // The local mirror holds the four previous weekly runs and the CHIRPS days of their
  // weeks; once they are verified the map replaces the note.
  await expect(
    page.getByRole("img", { name: /over verified forecasts/ }),
  ).toBeVisible({ timeout: 280_000 });
  // The map says how noisy a correlation over so few weeks is.
  await expect(
    page.getByText(/only r above 0\.\d\d differs from chance/),
  ).toBeVisible();
  await page.goto("/verification");
  await expect(
    page.getByRole("heading", { name: "How to read the scores" }),
  ).toBeVisible();
  const stat = page.locator(".stat").filter({ hasText: "Verified forecasts" });
  await expect(stat.locator(".value")).toHaveText("4");
  await expect(page.getByRole("cell", { name: /SON/ }).first()).toBeVisible();
  // The latest verified week is also scored against ARC 2.0, RFE 2.0 and GPM IMERG.
  const others = page.locator("tbody tr");
  await expect(others.filter({ hasText: "CHIRPS (reference)" })).toBeVisible();
  for (const name of ["ARC 2.0", "RFE 2.0", "GPM IMERG"])
    await expect(others.filter({ hasText: name }).first()).toContainText(" mm");
  // This week's forecast is still the current one.
  await page.goto("/forecasts");
  await expect(page.getByText("Not verified yet.")).toBeVisible();
  // The archive lists the weekly forecasts (Sunday runs) with the latest marked, and a
  // verified week shows its forecast beside what CHIRPS and the other estimates observed.
  await page.goto("/forecasts/archive");
  const weeks = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: /Weekly forecasts/ }) });
  await expect(weeks.locator("tbody tr").first()).toContainText("Latest");
  await expect(weeks.locator("tbody tr").first()).toContainText("03:00 EAT");
  await weeks
    .locator("tbody tr")
    .filter({ hasText: "Verified · CHIRPS" })
    .first()
    .getByRole("link", { name: "Open →" })
    .click();
  const observed = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: "What fell that week" }) });
  await expect(
    observed.getByRole("img", { name: /Rainfall observed by CHIRPS/ }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(observed.getByText(/RMSE [\d.]+ mm · MAE [\d.]+ mm/)).toBeVisible();
  await observed.getByRole("button", { name: "ARC 2.0" }).click();
  await expect(
    observed.getByRole("img", { name: /Rainfall observed by ARC 2\.0/ }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(
    observed.locator("tbody tr").filter({ hasText: "GPM IMERG" }),
  ).toContainText(/\d/);
});

test("the About page says what the service is for", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("contentinfo")
    .getByRole("link", { name: "About this service" })
    .click();
  await expect(
    page.getByRole("heading", { name: "About this service", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText(/7 to 14 days/)).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/internship/i);
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
    "/maps/correlation",
    "/maps/bias",
    "/monitoring",
    "/monitoring?source=tamsat",
    "/monitoring?source=arc2",
    "/verification",
    "/verification/experimental",
    "/bulletin",
    "/bulletins",
    "/models",
    "/data",
    "/data/ecmwf",
    "/data/chirps",
    "/data/tamsat",
    "/data/arc2",
    "/data/rfe2",
    "/data/imerg",
    "/data/runs",
    "/system",
    "/copilot",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Verification pages calculate maps from several full grids before rendering.
    await expect(page.locator(".skeleton"), path).toHaveCount(0, {
      timeout: 60_000,
    });
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
    page.getByText(/upper-air \(pressure-level\)/).first(),
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

test("data sources: every source is fetched and has its page", async ({
  page,
}) => {
  await page.goto("/data/ecmwf");
  await expect(
    page.getByRole("heading", { name: "Downloaded runs" }),
  ).toBeVisible();
  const downloaded = page
    .locator("section.card")
    .filter({ has: page.getByRole("heading", { name: "Downloaded runs" }) })
    .locator("tbody tr")
    .first();
  await expect(downloaded).toContainText("03:00 EAT");
  await expect(downloaded).toContainText("Local copy");
  await page.goto("/data/tamsat");
  await expect(
    page.getByRole("heading", { name: "Downloaded dekads" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  for (const [path, title] of [
    ["/data/arc2", "ARC 2.0"],
    ["/data/rfe2", "RFE 2.0"],
    ["/data/imerg", "GPM IMERG Late Run"],
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { level: 1, name: title }),
    ).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(1);
  }
  await page.goto("/data");
  await expect(page.getByText("Coming later")).toHaveCount(0);
});

test("system status reports the downloaded input and the issued forecast", async ({
  page,
}) => {
  await page.goto("/system");
  const row = (name: string) =>
    page
      .locator(".health-row")
      .filter({ has: page.getByText(name, { exact: true }) });
  await expect(row("ECMWF input")).toContainText("Healthy");
  await expect(row("Operational forecasts")).toContainText("Healthy");
  await expect(row("MBC + AI/ML forecast")).toContainText("In progress");
  await expect(row("CHIRPS monitoring")).toContainText("Healthy");
  await expect(row("TAMSAT monitoring")).toContainText("Healthy");
  await expect(row("ARC 2.0 monitoring")).toContainText("Healthy");
  await expect(row("RFE 2.0 monitoring")).toContainText("Healthy");
  await expect(row("GPM IMERG monitoring")).toContainText("Healthy");
  await expect(row("Bulletin email")).toContainText("Healthy");
});

test("a reference the Copilot cites opens as a readable page", async ({
  page,
}) => {
  await page.goto("/references?id=verification-guide");
  await expect(
    page.getByRole("heading", { name: "Verification guide", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText(/RMSE and MAE summarize/)).toBeVisible();
});
