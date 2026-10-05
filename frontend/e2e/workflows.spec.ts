import { test, expect } from "@playwright/test";
test("Copilot calls tools and displays retrieved sources", async ({ page }) => {
  await page.goto("/copilot");
  await page
    .getByLabel("Ask Forecaster Copilot")
    .fill("Compare CHIRPS and TAMSAT for Somalia.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText(
    "Somalia",
    { timeout: 60000 },
  );
  await expect(page.locator(".chat-message.assistant")).toContainText("RMSE");
  await expect(
    page.getByText("Inspect tool evidence", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".reference-list").last()).toContainText(
    "Prototype verification guide",
  );
});
test("Bulletin requires a named review before approval", async ({ page }) => {
  await page.goto("/bulletins");
  await page
    .getByRole("button", { name: "Generate draft", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Submit for review", exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await page
    .getByRole("button", { name: "Submit for review", exact: true })
    .click();
  await page
    .getByLabel("Reviewer name", { exact: true })
    .fill("Browser test forecaster");
  await page
    .getByLabel("Review justification", { exact: true })
    .fill("Checked synthetic sources, units and valid dates");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Confirm action", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve bulletin", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Approve bulletin", exact: true })
    .click();
  await page
    .getByLabel("Reviewer name", { exact: true })
    .fill("Browser test forecaster");
  await page
    .getByLabel("Review justification", { exact: true })
    .fill("Narrative matches frozen tool evidence");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Confirm action", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Record demo publication", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Export HTML", exact: true }),
  ).toBeVisible();
});
test("Local executor completes and exposes logs", async ({ page }) => {
  await page.goto("/jobs");
  await page.getByLabel("Job executor", { exact: true }).selectOption("local");
  await page.getByRole("button", { name: "Run pipeline", exact: true }).click();
  await expect(
    page
      .locator("tbody tr")
      .filter({ hasText: "products" })
      .filter({ hasText: "local" })
      .first(),
  ).toContainText("success", { timeout: 60000 });
});
test("Model promotion requires explicit confirmation and can roll back", async ({
  page,
}) => {
  await page.goto("/models");
  const raw = page.locator(".product-card").filter({
    has: page.getByRole("heading", { name: "Raw ECMWF", exact: true }),
  });
  await raw.getByRole("button", { name: "Promote", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Confirm action", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Reviewer name", { exact: true })
    .fill("Browser reviewer");
  await page
    .getByLabel("Review justification", { exact: true })
    .fill("Prototype comparison reviewed for UI validation");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Confirm action", exact: true })
    .click();
  const mock = page.locator(".product-card").filter({
    has: page.getByRole("heading", { name: "Mock correction", exact: true }),
  });
  await expect(
    mock.getByRole("button", { name: "Rollback", exact: true }),
  ).toBeVisible();
  await mock.getByRole("button", { name: "Rollback", exact: true }).click();
  await page
    .getByLabel("Reviewer name", { exact: true })
    .fill("Browser reviewer");
  await page
    .getByLabel("Review justification", { exact: true })
    .fill("Restore the original demonstration production version");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Confirm action", exact: true })
    .click();
  await expect(raw.getByText("retired", { exact: true })).toBeVisible();
});
