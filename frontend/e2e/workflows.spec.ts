import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUTBOX = path.join(
  process.env.E2E_STATE ?? path.join(os.tmpdir(), "icpac-e2e"),
  "service",
  "outbox",
);

/** The link in the newest email to ``address`` (quoted-printable decoded). */
function emailedLink(address: string): string {
  const files = fs
    .readdirSync(OUTBOX)
    .filter((name) => name.includes(address.replace("@", "_at_")))
    .sort();
  const raw = fs.readFileSync(
    path.join(OUTBOX, files[files.length - 1]),
    "utf8",
  );
  const text = raw.replace(/=\r?\n/g, "").replace(/=3D/g, "=");
  const match =
    /http:\/\/127\.0\.0\.1:3000(\/bulletins\/action\?token=[\w.-]+)/.exec(text);
  if (!match) throw new Error(`No action link in the email to ${address}`);
  return match[1];
}

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

test("a bulletin is approved and published from the emailed links", async ({
  page,
}) => {
  await page.goto("/bulletin");
  await page.getByRole("button", { name: "Create draft for review" }).click();
  await page.waitForURL(/\/bulletins\?id=/, { timeout: 60_000 });
  await expect(
    page.getByText(/Submitting emails 1 reviewer a link/),
  ).toBeVisible();
  await review(page, "Submit for review", "Ready for the reviewer");
  await expect(
    page.getByText(/Emailed to the reviewers \(reviewer@icpac\.test\)/),
  ).toBeVisible();

  // The reviewer opens the link from the email: the bulletin and the two decisions.
  await page.goto(emailedLink("reviewer@icpac.test"));
  await expect(
    page.getByRole("heading", { name: "Review the bulletin" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(
    page.getByText("Give a reason for the rejection."),
  ).toBeVisible();
  await page.getByLabel("Your name").fill("Email reviewer");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Approved\. The approved text/)).toBeVisible();
  await expect(
    page.getByText("The publishers have been emailed"),
  ).toBeVisible();

  // The publisher publishes from their own email.
  await page.goto(emailedLink("publisher@icpac.test"));
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText(/^Published\./)).toBeVisible();
  // A link works once.
  await page.reload();
  await expect(page.getByText(/already been used/)).toBeVisible();
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
