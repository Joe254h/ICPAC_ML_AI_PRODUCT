import { expect, test } from "@playwright/test";

test("staff connect restores private history and disconnect clears the page", async ({
  page,
  context,
}) => {
  await context.setExtraHTTPHeaders({});
  await page.goto("/copilot");
  // Signed out, the Copilot asks for a sign-in: no error, nothing to retry.
  await expect(
    page.getByRole("heading", { name: "Sign in to use the Copilot" }),
  ).toBeVisible();
  await expect(page.getByText("Retry loading the conversation")).toHaveCount(0);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByLabel("Staff access key")
    .fill("test-bulletin-operator-key-00000000");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const chip = page.getByRole("button", { name: "Signed in as Joe254h" });
  await expect(chip).toBeVisible();
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Explain the forecast for Kenya.",
      exact: true,
    })
    .click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "Kenya",
    { timeout: 60_000 },
  );
  await chip.click();
  await expect(page.getByRole("dialog")).toContainText("Signed in as Joe254h");
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(page.locator(".chat-message")).toHaveCount(0);
  await page.getByText("Staff access", { exact: true }).click();
  await page
    .getByLabel("Staff access key")
    .fill("test-bulletin-operator-key-00000000");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "Kenya",
    { timeout: 60_000 },
  );
});
