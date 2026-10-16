import { NextRequest } from "next/server";

// Fluid compute supports 300 s on Hobby. Keep the upstream timeout below that limit;
// the Copilot shares a smaller budget across all model calls. Use /operations for long work.
export const maxDuration = 300;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, (await params).path);
}
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, (await params).path);
}
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, (await params).path);
}
async function proxy(request: NextRequest, segments: string[]) {
  const target = new URL(
    segments.map(encodeURIComponent).join("/") + request.nextUrl.search,
    (process.env.API_URL ?? "http://127.0.0.1:8000") + "/",
  );
  try {
    const authorization = request.headers.get("authorization");
    const upstream = await fetch(target, {
      method: request.method,
      headers: {
        "Content-Type": "application/json",
        ...(authorization ? { Authorization: authorization } : {}),
      },
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
      // Forecast runs and verification compute on the full 800 x 700 grid; other requests
      // allow for a serverless backend starting from zero (image, model registration).
      signal: AbortSignal.timeout(240000),
    });
    const headers = new Headers();
    for (const name of [
      "content-type",
      "content-disposition",
      "cache-control",
      "retry-after",
      "www-authenticate",
    ]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    // A 204 (a conversation deleted) has no body, and a Response must not be given one.
    const empty = [204, 205, 304].includes(upstream.status);
    return new Response(empty ? null : upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch {
    return Response.json(
      { detail: "Climate API unavailable. Check backend service and API_URL." },
      { status: 503 },
    );
  }
}
