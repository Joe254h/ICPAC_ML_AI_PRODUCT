import { expect, test } from "@playwright/test";

test("working pages fit phones, tablets and desktop with readable Arabic and dark mode", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [1440, 768, 375, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of [
      "/verification",
      "/automations",
      "/maps/rainfall",
      "/countries",
      "/bulletin",
      "/copilot",
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      if (path === "/verification")
        await expect(
          page.getByRole("heading", { name: "Scores of every verified week" }),
        ).toBeVisible();
      if (path === "/automations")
        await expect(
          page.getByRole("heading", {
            name: "All 20 capabilities",
            exact: true,
          }),
        ).toBeVisible();
      if (path === "/countries")
        await expect(page.locator(".country-card")).toHaveCount(11);
      if (path === "/bulletin")
        await expect(
          page.getByRole("heading", { name: "Total Rainfall", exact: true }),
        ).toBeVisible();
      if (path === "/copilot")
        await expect(
          page.getByRole("combobox", { name: "Answer language" }),
        ).toBeVisible();
      if (path === "/maps/rainfall") {
        const map = page.getByRole("img", {
          name: /^Raw ECMWF Week-2 rainfall/,
        });
        await expect(map).toBeVisible({ timeout: 60_000 });
        await expect
          .poll(() =>
            map.evaluate((image: HTMLImageElement) => image.naturalWidth),
          )
          .toBeGreaterThan(500);
      }
      await expect(page.locator(".skeleton")).toHaveCount(0, {
        timeout: 60_000,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - innerWidth,
        ),
        `${path} at ${width}`,
      ).toBeLessThanOrEqual(1);
      await page.screenshot({
        path: test
          .info()
          .outputPath(`${path.replaceAll("/", "-")}-${width}.png`),
      });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/verification");
  await page.locator(".utility .language-picker select").selectOption("ar");
  await expect(page.locator(".workspace-rail")).toHaveAttribute("dir", "rtl");
  const dark = page.getByRole("button", { name: "Switch to dark mode" });
  if (await dark.isVisible()) await dark.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 60_000 });
  await page.screenshot({
    path: test.info().outputPath("verification-arabic-dark.png"),
  });
  await page.goto("/copilot");
  await expect(
    page.getByRole("combobox", { name: "Answer language" }),
  ).toHaveValue("ar");
  await expect(
    page.getByLabel("Ask Forecaster Copilot", { exact: true }),
  ).toHaveAttribute("dir", "auto");
  expect(errors).toEqual([]);
});
