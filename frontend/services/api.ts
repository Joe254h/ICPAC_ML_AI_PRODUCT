/** An API failure with its HTTP status, so "nothing yet" (404) can be told apart. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(bulletinOperatorKey && path !== "/bulletins/email-action"
        ? { Authorization: `Bearer ${bulletinOperatorKey}` }
        : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "API unavailable" }));
    throw new ApiError(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
      response.status,
    );
  }
  // 204 (a conversation deleted): nothing to read.
  if (response.status === 204) return undefined as T;
  return response.json();
}

// Kept only in this tab's memory, never in browser storage or public environment variables.
let bulletinOperatorKey = "";
export function setBulletinOperatorKey(key: string) {
  bulletinOperatorKey = key;
}
export function getBulletinOperatorKey() {
  return bulletinOperatorKey;
}

export function mutate<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
