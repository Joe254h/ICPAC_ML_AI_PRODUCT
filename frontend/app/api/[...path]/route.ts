import { NextRequest } from "next/server";
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
async function proxy(request: NextRequest, segments: string[]) {
  const target = new URL(
    segments.map(encodeURIComponent).join("/") + request.nextUrl.search,
    (process.env.API_URL ?? "http://127.0.0.1:8000") + "/",
  );
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
      // Forecast runs and verification compute on the full 800 x 700 grid; other requests
      // allow for a serverless backend starting from zero (image, model registration).
      signal: AbortSignal.timeout(
        request.method === "POST" && segments[0] === "forecasts"
          ? 300000
          : 90000,
      ),
    });
    const headers = new Headers();
    for (const name of [
      "content-type",
      "content-disposition",
      "cache-control",
    ]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return Response.json(
      { detail: "Climate API unavailable. Check backend service and API_URL." },
      { status: 503 },
    );
  }
}
