import { expect, test } from "@playwright/test";

test("a restored source retry is followed to completion without another submission", async ({
  page,
}) => {
  const workspace = await page.request
    .get("/api/automations")
    .then((response) => response.json());
  const waiting = {
    id: "recovery-check",
    action: "end_to_end",
    title: "Source recovery check",
    status: "failed",
    initialization: "2026-10-18",
    created_at: "2026-10-18T09:00:00Z",
    created_by: "QA",
    messages: [],
    result: null,
    error: "Temporary provider throttling",
    attempts: 1,
    retry_at: "2099-01-01T00:00:00Z",
  };
  await page.route("**/api/automations", (route) =>
    route.fulfill({ json: { ...workspace, last_cycle: waiting } }),
  );
  let polls = 0;
  await page.route("**/api/operations/recovery-check", (route) => {
    polls += 1;
    return route.fulfill({
      json:
        polls === 1
          ? waiting
          : {
              ...waiting,
              status: "complete",
              retry_at: null,
              error: null,
              result: { bulletin_id: "prepared-test-bulletin" },
            },
    });
  });
  let submissions = 0;
  await page.route("**/api/operations", (route) => {
    submissions += 1;
    return route.abort();
  });
  await page.goto("/automations");
  await expect(page.getByText(/Waiting for retry · 1 attempt/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Workflow running…" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("link", { name: "Open prepared bulletin →" }),
  ).toBeVisible({ timeout: 30000 });
  expect(submissions).toBe(0);
});

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
