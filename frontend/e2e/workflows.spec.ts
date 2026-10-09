import { expect, test, type Page } from "@playwright/test";

async function review(page: Page, action: string, comment: string) {
  await page.getByRole("button", { name: action, exact: true }).click();
  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: action, exact: true });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Reviewer name").fill("Browser reviewer");
  await dialog.getByLabel("Justification").fill(comment);
  await dialog.getByRole("checkbox").check();
  await confirm.click();
  await expect(dialog).toBeHidden();
}

test("a bulletin goes from draft to review, approval and publication", async ({
  page,
}) => {
  await page.goto("/bulletin");
  await expect(
    page.getByRole("heading", { name: "Total Rainfall" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Products in progress" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create draft for review" }).click();
  await page.waitForURL(/\/bulletins\?id=/, { timeout: 60_000 });
  await expect(page.getByText("Draft", { exact: true }).first()).toBeVisible();
  await review(
    page,
    "Submit for review",
    "Checked the maps, wording and valid dates",
  );
  await review(page, "Approve", "The narrative matches the forecast");
  await review(page, "Publish", "Released through the ICPAC channels");
  await expect(
    page.getByText("Published", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Word" })).toHaveAttribute(
    "href",
    /\/api\/bulletins\/.+\/export\?format=docx/,
  );
});

test("the model registry shows the candidate and guards promotion", async ({
  page,
}) => {
  await page.goto("/models");
  await expect(
    page.getByRole("heading", { name: "MBC + Atmos37 CatBoost" }),
  ).toBeVisible();
  await expect(page.getByText("AI/ML layer in progress.")).toBeVisible();
  await page.getByRole("button", { name: "Promote to production" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});

test("operations lists the weekly cycle with who ran it", async ({ page }) => {
  await page.goto("/data/runs");
  const row = page
    .locator("tbody tr")
    .filter({ hasText: "Weekly cycle" })
    .first();
  await expect(row).toContainText("complete");
  await expect(row).toContainText("Browser forecaster");
  await row.getByRole("button", { name: "Details" }).click();
  await expect(
    page.getByRole("link", { name: "Open forecast →" }).first(),
  ).toBeVisible();
});
