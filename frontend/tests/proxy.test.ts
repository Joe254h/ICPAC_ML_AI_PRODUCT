import { afterEach, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "../app/api/[...path]/route";

afterEach(() => vi.unstubAllGlobals());

test("the proxy preserves anonymous conversation ownership without adding staff access", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const visitor = "a".repeat(32);
  const response = await GET(
    new NextRequest("http://localhost/api/chat/sessions", {
      headers: { "X-Visitor-Id": visitor },
    }),
    { params: Promise.resolve({ path: ["chat", "sessions"] }) },
  );
  expect(response.status).toBe(200);
  expect(fetch.mock.calls[0][1].headers["X-Visitor-Id"]).toBe(visitor);
  expect(fetch.mock.calls[0][1].headers.Authorization).toBeUndefined();
  expect(fetch.mock.calls[0][1].cache).toBe("no-store");
});

test("a connection failure gives visitors a useful message without deployment settings", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("upstream unreachable")),
  );
  const response = await GET(new NextRequest("http://localhost/api/health"), {
    params: Promise.resolve({ path: ["health"] }),
  });
  expect(response.status).toBe(503);
  const body = await response.json();
  expect(body.detail).toContain("temporarily unavailable");
  expect(body.detail).not.toContain("API_URL");
});
