import { expect, test } from "@playwright/test";

test("the 20-capability workspace runs a connected workflow without publishing", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const before = await page.request
    .get("/api/bulletins")
    .then((response) => response.json());
  const published = before
    .filter((item: { status: string }) => item.status === "published")
    .map((item: { id: string }) => item.id)
    .sort();
  await page.goto("/automations");
  await expect(
    page.getByRole("heading", { name: "All 20 capabilities", exact: true }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(20);
  await expect(
    page
      .getByText("Awaiting an approved request profile", { exact: false })
      .first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Prepare forecast and bulletin", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Open prepared bulletin →" }),
  ).toBeVisible({ timeout: 150_000 });
  const after = await page.request
    .get("/api/bulletins")
    .then((response) => response.json());
  expect(
    after
      .filter((item: { status: string }) => item.status === "published")
      .map((item: { id: string }) => item.id)
      .sort(),
  ).toEqual(published);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
