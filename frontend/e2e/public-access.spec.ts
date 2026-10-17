import { expect, test } from "@playwright/test";

test("public visitors can chat immediately, reload, and keep separate histories", async ({
  page,
  context,
  browser,
}) => {
  test.skip(
    process.env.E2E_ACCESS_MODE !== "public",
    "Requires the public evaluation backend",
  );
  await context.setExtraHTTPHeaders({});
  await page.goto("/copilot");
  const health = await page.request.get("/api/health");
  expect((await health.json()).access_mode).toBe("public");
  await expect(page.getByText("Staff access", { exact: true })).toHaveCount(0);
  await page
    .getByLabel("Ask Forecaster Copilot", { exact: true })
    .fill("Hello");
  const answer = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/chat") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const response = await answer;
  expect(response.status()).toBe(200);
  expect(response.request().headers().authorization).toBeUndefined();
  const session = (await response.json()).session_id;
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1);
  const otherContext = await browser.newContext();
  try {
    const other = await otherContext.newPage();
    await other.goto(new URL("/copilot", page.url()).href);
    await expect(
      other.getByLabel("Ask Forecaster Copilot", { exact: true }),
    ).toBeVisible();
    const result = await other.evaluate(async (id) => {
      const visitor = localStorage.getItem("icpac-visitor-id")!;
      const headers = { "X-Visitor-Id": visitor };
      const list = await fetch("/api/chat/sessions", { headers }).then((r) =>
        r.json(),
      );
      const denied = await fetch(`/api/chat/sessions/${id}`, { headers });
      return { list, status: denied.status };
    }, session);
    expect(result.list).toEqual([]);
    expect(result.status).toBe(404);
  } finally {
    await otherContext.close();
  }
});
