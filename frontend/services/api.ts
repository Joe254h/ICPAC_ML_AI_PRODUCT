import type { Selection } from "@/types";
export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "API unavailable" }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
export function query(selection: Selection) {
  return new URLSearchParams(selection).toString();
}
export function mutate<T>(path: string, body: unknown) {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}
