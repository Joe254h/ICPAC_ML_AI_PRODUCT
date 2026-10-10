import { expect, test } from "@playwright/test";

test("the Copilot answers from the issued forecast", async ({ page }) => {
  await page.goto("/copilot");
  await expect(
    page.getByRole("heading", { name: "Conversations" }),
  ).toBeVisible();
  const saved = page
    .getByRole("navigation", { name: "Saved conversations" })
    .getByRole("button");
  await page
    .getByRole("button", {
      name: "Explain the forecast for Kenya.",
      exact: true,
    })
    .click();
  const answer = page.locator(".chat-message.assistant").last();
  await expect(answer).toContainText("Kenya", { timeout: 60_000 });
  await expect(answer).toContainText("mm");
  await expect(page.getByLabel("Conversation country")).toHaveValue("Kenya");
  // The new conversation is saved and listed first, as the current one.
  await expect(saved.first()).toHaveAttribute("aria-current", "true");
  await expect(saved.first()).toContainText("Explain the forecast for Kenya.");
});

test("continuous chat sends on Enter, restores history and retries failures", async ({
  page,
}) => {
  const fid = "w2-2026-10-07-12345678";
  const context = {
    mode: "operational",
    forecast_id: fid,
    model_id: "candidate_model",
    model_status: "candidate",
    country: "Kenya",
    variant: "mbc",
    valid_start: "2026-10-14T00:00:00Z",
    valid_end: "2026-10-21T00:00:00Z",
  };
  const messages: Record<string, unknown>[] = [];
  const requests: Record<string, unknown>[] = [];
  let failNext = false;
  // Restores fail until the test clicks Retry: in development React runs the restoring
  // effect twice and discards the first response, so a single failure would be missed.
  let failRestore = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.slice(4);
    let data: unknown = {};
    if (path === "/config")
      data = {
        operational: {
          hybrid: { status: "in_progress", reason: "inputs missing" },
          countries: ["Kenya", "Somalia"],
          input_sources: ["ecmwf_opendata"],
          map_layers: ["raw", "mbc"],
          verification_maps: {},
          pressure_steps_configured: false,
        },
        models: [],
        data_sources: [],
      };
    else if (path === "/health")
      data = { status: "Healthy", mode: "operational", components: {} };
    else if (path === "/models/current")
      data = {
        role: "candidate",
        model: { model_id: "candidate_model", status: "candidate" },
      };
    else if (path === "/forecasts/latest")
      data = {
        ...context,
        initialization: "2026-10-07",
        layers: ["raw", "mbc"],
        primary_layer: "mbc",
        countries: [{ country: "Kenya" }, { country: "Somalia" }],
      };
    else if (path === "/chat/sessions")
      data = messages.length
        ? [
            {
              id: "conversation-one",
              title: "Kenya rainfall",
              created_at: "2026-10-08",
              updated_at: "2026-10-08",
              message_count: messages.length,
              context,
            },
          ]
        : [];
    else if (path === "/chat/sessions/conversation-one") {
      if (failRestore)
        return route.fulfill({
          status: 503,
          json: { detail: "Temporary restore failure" },
        });
      data = { id: "conversation-one", messages, context };
    } else if (path === "/chat") {
      const body = route.request().postDataJSON();
      requests.push(body);
      if (failNext) {
        failNext = false;
        return route.fulfill({
          status: 503,
          json: { detail: "Temporary endpoint failure" },
        });
      }
      if (body.message.includes("Somalia")) context.country = "Somalia";
      const answer = {
        role: "assistant",
        session_id: "conversation-one",
        context: { ...context },
        text: `${context.country} rainfall for the same forecast. ${"Forecast explanation. ".repeat(45)}`,
        provider: "openai_compatible",
        sources: [
          {
            id: "science",
            title: "Verification guide",
            category: "scientific_reference",
            checksum: "abc",
            synthetic: false,
            excerpt: "Evidence source.",
            url: "/api/references/science",
          },
        ],
        tool_trace: [
          {
            tool: "get_country_forecast",
            arguments: { forecast_id: fid },
            result: { mean_rainfall_mm: 64.3 },
          },
        ],
      };
      messages.push({ role: "user", text: body.message }, answer);
      data = answer;
    }
    await route.fulfill({ json: data });
  });
  await page.goto("/copilot");
  const input = page.getByLabel("Ask Forecaster Copilot");
  await expect(input).toBeEnabled();
  await input.fill("Kenya rainfall");
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("Kenya rainfall\n");
  expect(requests).toHaveLength(0);
  await input.press("Enter");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1);
  await expect(page.locator(".chat-message.assistant")).toContainText(
    "Kenya rainfall",
  );
  expect(requests[0].context_mode).toBe("operational");
  // Empty: the forecast's main layer, chosen by the service.
  expect(requests[0].variant).toBeNull();
  for (const details of await page.locator(".chat-details").all())
    await expect(details).not.toHaveAttribute("open", "");
  await input.fill("And Somalia?");
  await input.press("Enter");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  expect(requests[1].session_id).toBe("conversation-one");
  await expect(page.getByLabel("Conversation country")).toHaveValue("Somalia");
  await expect
    .poll(() =>
      page
        .locator(".chat-stream")
        .evaluate(
          (node) => node.scrollHeight - node.clientHeight - node.scrollTop,
        ),
    )
    .toBeLessThan(20);
  failRestore = true;
  await page.reload();
  const retry = page.getByRole("button", {
    name: "Retry loading the conversation",
  });
  await expect(retry).toBeVisible();
  await expect(input).toBeDisabled();
  failRestore = false;
  await retry.click();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  await expect(page.getByLabel("Conversation country")).toHaveValue("Somalia");
  failNext = true;
  await input.fill("Tell me more");
  await input.press("Enter");
  await expect(page.locator(".chat-card [role=alert]")).toContainText(
    "Temporary endpoint failure",
  );
  await expect(input).toHaveValue("Tell me more");
  await expect(page.locator(".chat-message.user")).toHaveCount(2);
  await input.press("Enter");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(3);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await expect(page.locator(".chat-message")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Saved conversations" })
    .getByRole("button")
    .first()
    .click();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
