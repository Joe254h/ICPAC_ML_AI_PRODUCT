import { test, expect } from "@playwright/test";
test("forecaster selects observations and runs verification", async ({
  page,
}) => {
  await page.goto("/demo");
  await expect(page.getByText("DEMO DATA", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Quality control", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Observation source", { exact: true })
    .selectOption("TAMSAT");
  await expect(page.locator(".content")).toHaveAttribute("aria-busy", "false");
  await page
    .getByRole("button", { name: "Run verification", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Verification run saved",
  );
  await page.getByRole("link", { name: "Verification", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Demonstration verification runs" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "TAMSAT", exact: true }).first(),
  ).toBeVisible();
});
