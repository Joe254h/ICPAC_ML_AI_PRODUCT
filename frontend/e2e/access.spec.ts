import { expect, test } from "@playwright/test";

test("staff connect restores private history and disconnect clears the page", async ({
  page,
  context,
}) => {
  await context.setExtraHTTPHeaders({});
  await page.goto("/copilot");
  await page.getByText("Staff access", { exact: true }).click();
  await page
    .getByLabel("Staff access key")
    .fill("test-bulletin-operator-key-00000000");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Connected as Joe254h" }),
  ).toBeVisible();
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
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(page.locator(".chat-message")).toHaveCount(0);
  await page
    .getByLabel("Staff access key")
    .fill("test-bulletin-operator-key-00000000");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "Kenya",
    { timeout: 60_000 },
  );
});
