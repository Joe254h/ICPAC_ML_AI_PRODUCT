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
  // The conversation list hides and comes back, as in ChatGPT, and the choice is kept.
  const heading = page.getByRole("heading", { name: "Conversations" });
  await page.getByRole("button", { name: "Hide conversations" }).click();
  await expect(heading).toBeHidden();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Show conversations" }),
  ).toBeVisible();
  await expect(heading).toBeHidden();
  await page.getByRole("button", { name: "Show conversations" }).click();
  await expect(heading).toBeVisible();
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

test("conversations are archived, restored and deleted", async ({ page }) => {
  await page.goto("/copilot");
  const input = page.getByLabel("Ask Forecaster Copilot");
  await input.fill("What is RMSE?");
  await input.press("Enter");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1, {
    timeout: 60_000,
  });
  const saved = page.getByRole("navigation", { name: "Saved conversations" });
  const item = saved.locator(".history-item").first();
  await expect(item).toContainText("What is RMSE?");

  // Archive: out of the list, onto the archived shelf, and a new conversation starts.
  await item.getByRole("button", { name: "Options for What is RMSE?" }).click();
  await page.getByRole("menuitem", { name: "Archive" }).click();
  await expect(saved.getByText("What is RMSE?")).toHaveCount(0);
  await expect(page.locator(".chat-message")).toHaveCount(0);
  await page.getByRole("button", { name: "Archived conversations" }).click();
  const shelf = page.getByRole("navigation", {
    name: "Archived conversations",
  });
  await expect(shelf).toContainText("What is RMSE?");

  // Restore brings it back.
  await shelf
    .getByRole("button", { name: "Options for What is RMSE?" })
    .click();
  await page.getByRole("menuitem", { name: "Restore" }).click();
  await expect(page.getByText("No archived conversations.")).toBeVisible();
  await page.getByRole("button", { name: "Back to conversations" }).click();
  await expect(saved).toContainText("What is RMSE?");

  // Delete asks first; Cancel keeps it, Delete removes it for good.
  await saved
    .getByRole("button", { name: "Options for What is RMSE?" })
    .first()
    .click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog", {
    name: "Delete this conversation?",
  });
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(saved).toContainText("What is RMSE?");
  await saved
    .getByRole("button", { name: "Options for What is RMSE?" })
    .first()
    .click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(dialog).toBeHidden();
  await page.reload();
  await expect(page.getByText("What is RMSE?")).toHaveCount(0);
});

test("the bulletin is shown in the conversation", async ({ page }) => {
  await page.goto("/copilot");
  await page
    .getByRole("button", { name: "Show this week's bulletin.", exact: true })
    .click();
  const card = page.locator(".chat-message.assistant .chat-bulletin").last();
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText("Version 1");
  await expect(card).toContainText("Headline");
  await expect(
    page
      .locator(".chat-message.assistant")
      .last()
      .getByRole("link", {
        name: /Review this draft/,
      }),
  ).toBeVisible();
});

test("another model's forecast is uploaded in the chat and compared with ICPAC's", async ({
  page,
  request,
}) => {
  const latest = await (await request.get("/api/forecasts/latest")).json();
  await page.goto("/copilot");
  await page
    .getByTestId("forecast-file")
    .setInputFiles(`${process.cwd()}/e2e/fixtures/colleague_week2.nc`);
  const form = page.getByRole("group", {
    name: "Upload another model's forecast",
  });
  await expect(form).toContainText("colleague_week2.nc");
  await form.getByLabel("Model name").fill("Colleague CNN");
  // The file has no dates: the week is given.
  await form
    .getByLabel("Week starts")
    .fill(String(latest.valid_start).slice(0, 10));
  await form.getByRole("button", { name: "Upload and compare" }).click();
  const card = page.locator(".chat-message.assistant .chat-comparison").last();
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText("Colleague CNN");
  await expect(card).toContainText("Waiting for observations");
  await expect(card).toContainText("forecast of the same week");
  await card.getByText("Country by country").click();
  await expect(card.locator("tbody tr").first()).toBeVisible();
  await page.goto("/verification");
  const listed = page.locator(".card").filter({
    has: page.getByRole("heading", { name: "Other models' forecasts" }),
  });
  await expect(listed).toContainText("Colleague CNN");
  await expect(listed).toContainText("Awaiting CHIRPS");
});

test("a file of any format goes with a question, and a question can be edited", async ({
  page,
}) => {
  await page.goto("/copilot");
  await page.getByTestId("forecast-file").setInputFiles({
    name: "field-report.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Floods were reported in Garissa on 25 October."),
  });
  const pending = page.getByRole("list", {
    name: "Files for the next question",
  });
  await expect(pending).toContainText("field-report.txt");
  await page
    .getByLabel("Ask Forecaster Copilot")
    .fill("What does my report say?");
  await page.keyboard.press("Enter");
  const asked = page.locator(".chat-message.user").last();
  await expect(asked).toContainText("field-report.txt");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1, {
    timeout: 60_000,
  });
  // Editing the question replaces it and its answer.
  await asked.getByRole("button", { name: "Edit this question" }).click();
  await page
    .getByLabel("Edited question")
    .fill("Summarise this week's forecast.");
  await page.getByRole("button", { name: "Ask again" }).click();
  await expect(page.locator(".chat-message.user")).toHaveCount(1);
  await expect(page.locator(".chat-message.user").last()).toContainText(
    "Summarise this week's forecast.",
  );
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1, {
    timeout: 60_000,
  });
  // The forecast weeks are offered in the conversation's menu.
  await expect(
    page.getByLabel("Forecast week").locator("option").first(),
  ).toContainText("newest");
});
