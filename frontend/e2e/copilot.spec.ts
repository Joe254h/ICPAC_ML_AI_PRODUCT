import { test, expect } from "@playwright/test";
import path from "node:path";

test("continuous chat sends on Enter, restores history, collapses evidence and retries failures", async ({
  page,
}) => {
  const fid = "w2-2026-10-08-12345678";
  const context = {
    mode: "operational",
    forecast_id: fid,
    model_id: "candidate_model",
    model_status: "candidate",
    country: "Kenya",
    variant: "hybrid",
    synthetic: true,
  };
  const messages: Record<string, unknown>[] = [];
  const requests: Record<string, unknown>[] = [];
  let failNext = false;
  let failRestoreOnce = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.slice(4);
    let data: unknown = {};
    if (path === "/config")
      data = {
        science: { countries: ["Kenya", "Somalia"] },
        forecasts: {},
        models: [],
      };
    else if (path === "/models/current")
      data = {
        role: "candidate",
        model: { model_id: "candidate_model", status: "candidate" },
      };
    else if (path === "/forecasts/latest")
      data = {
        ...context,
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
      if (failRestoreOnce) {
        failRestoreOnce = false;
        return route.fulfill({
          status: 503,
          json: { detail: "Temporary restore failure" },
        });
      }
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
        text: `${context.country} rainfall for the same package. ${"Forecast explanation. ".repeat(45)}`,
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
  await expect(page.locator(".chat-evidence")).not.toHaveAttribute("open", "");
  await expect(page.locator(".tool-trace")).not.toHaveAttribute("open", "");
  await input.fill("And Somalia?");
  await input.press("Enter");
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  expect(requests[1].session_id).toBe("conversation-one");
  await expect(page.getByLabel("Conversation country")).toHaveValue("Somalia");
  if (process.env.BULLETIN_QA_MAP_ROOT)
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "continuous-chat-browser.png",
      ),
      fullPage: false,
    });
  await expect
    .poll(() =>
      page
        .locator(".chat-stream")
        .evaluate(
          (node) => node.scrollHeight - node.clientHeight - node.scrollTop,
        ),
    )
    .toBeLessThan(20);
  failRestoreOnce = true;
  await page.reload();
  await expect(input).toBeDisabled();
  await page
    .getByRole("button", { name: "Retry loading conversation" })
    .click();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(2);
  await expect(page.getByLabel("Conversation country")).toHaveValue("Somalia");
  failNext = true;
  await input.fill("Tell me more");
  await input.press("Enter");
  await expect(page.locator(".copilot-workspace [role=alert]")).toContainText(
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
    .getByRole("button", { name: "Conversations", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Saved conversations" })
    .getByRole("button")
    .first()
    .click();
  await expect(page.locator(".chat-message.assistant")).toHaveCount(3);
  await page.setViewportSize({ width: 390, height: 844 });
  if (process.env.BULLETIN_QA_MAP_ROOT)
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "continuous-chat-mobile-browser.png",
      ),
      fullPage: false,
    });
  const overflow = await page.evaluate(() =>
    Array.from(document.querySelectorAll("main *"))
      .map((node) => ({
        tag: node.tagName,
        class: node.className,
        right: Math.round(node.getBoundingClientRect().right),
      }))
      .filter((node) => node.right > window.innerWidth + 1)
      .slice(0, 12),
  );
  expect(overflow).toEqual([]);
});

test("weekly preview follows the supplied section order and links its own Word draft", async ({
  page,
}) => {
  const fid = "w2-2026-10-08-12345678";
  const headings = [
    "Headline",
    "Decision-Support Note",
    "Total Rainfall",
    "Rainfall Anomalies",
    "Exceptional Rainfall",
    "Mean Temperature",
    "Temperature Anomaly",
    "Somalia",
    "Somalia Temperature",
    "Heat Stress",
  ];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const api = url.pathname.slice(4);
    if (api.endsWith("/map")) {
      const root = process.env.BULLETIN_QA_MAP_ROOT;
      return route.fulfill(
        root
          ? {
              contentType: "image/png",
              path: path.join(
                root,
                url.searchParams.has("country")
                  ? "somalia.png"
                  : "regional.png",
              ),
            }
          : {
              contentType: "image/png",
              body: Buffer.from(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII=",
                "base64",
              ),
            },
      );
    }
    let data: unknown = {};
    if (api === "/config")
      data = {
        science: { countries: ["Kenya", "Somalia"] },
        forecasts: {},
        models: [],
      };
    else if (api === "/models/current")
      data = {
        role: "candidate",
        model: { model_id: "candidate_model", status: "candidate" },
      };
    else if (api.endsWith("/bulletin"))
      data = {
        forecast_id: fid,
        title: "Weekly Forecast for 15-21 October 2026",
        generator: {
          status: "ready",
          review: "DRAFT - human review required",
          layout_validation: "Verify the draft in Word",
        },
        export: `/forecasts/${fid}/bulletin/export`,
        sections: headings.map((title, index) => ({
          key: String(index),
          title,
          text: [
            index === 0
              ? "SYNTHETIC TEST INPUT - NOT A FORECAST OF REAL WEATHER."
              : index === 2
                ? "Current package country means: Kenya 64.3 mm; Somalia 47.6 mm."
                : "Current package evidence or an explicit missing-product statement.",
          ],
          ...(index === 2 || index === 7
            ? {
                map: `/forecasts/${fid}/map?layer=hybrid&style=weekly-v1${index === 7 ? "&country=Somalia" : ""}`,
              }
            : index > 2
              ? { missing_dependency: "Required validated field unavailable" }
              : {}),
        })),
      };
    else if (api === `/forecasts/${fid}`)
      data = {
        forecast_id: fid,
        model_id: "candidate_model",
        model_status: "candidate",
        model: { test_status: "untested" },
        synthetic: true,
        initialization: "2026-10-08",
        valid_start: "2026-10-15T00:00:00Z",
        valid_end: "2026-10-22T00:00:00Z",
        generation_time: "2026-10-08T00:00:00Z",
        verification_status: "unavailable",
        interpretation: {
          method: { label: "MBC + ATMOS37 CATBOOST" },
          model: { role: "candidate" },
          input: { label: "synthetic fixture" },
          anomaly: { missing_dependency: "climatology" },
          category: { missing_dependency: "thresholds" },
        },
      };
    await route.fulfill({ json: data });
  });
  await page.goto(`/bulletin?id=${fid}`);
  const paper = page.getByRole("article", {
    name: "Weekly forecast bulletin preview",
  });
  await expect(paper).toBeVisible();
  await expect(paper.getByRole("heading", { level: 1 })).toHaveText(
    "Weekly Forecast for 15-21 October 2026",
  );
  await expect(paper.getByRole("heading", { level: 2 })).toHaveText(headings);
  await expect(paper.getByRole("img")).toHaveCount(2);
  await expect(
    page.getByRole("link", { name: "Download Word draft" }).first(),
  ).toHaveAttribute("href", `/api/forecasts/${fid}/bulletin/export`);
  await expect(paper).toContainText("Heat Stress map unavailable");
  await expect
    .poll(() =>
      paper
        .getByRole("img")
        .first()
        .evaluate(
          (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
        ),
    )
    .toBe(true);
  if (process.env.BULLETIN_QA_MAP_ROOT) {
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "weekly-bulletin-browser.png",
      ),
      fullPage: true,
    });
    await paper.locator("section").nth(2).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "weekly-bulletin-regional-browser.png",
      ),
      fullPage: false,
    });
    await paper.locator("section").nth(7).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "weekly-bulletin-somalia-browser.png",
      ),
      fullPage: false,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  if (process.env.BULLETIN_QA_MAP_ROOT)
    await page.screenshot({
      path: path.join(
        process.env.BULLETIN_QA_MAP_ROOT,
        "weekly-bulletin-mobile-browser.png",
      ),
      fullPage: false,
    });
  const overflow = await page.evaluate(() =>
    Array.from(document.querySelectorAll("main *"))
      .map((node) => ({
        tag: node.tagName,
        class: node.className,
        right: Math.round(node.getBoundingClientRect().right),
      }))
      .filter((node) => node.right > window.innerWidth + 1)
      .slice(0, 12),
  );
  expect(overflow).toEqual([]);
});
