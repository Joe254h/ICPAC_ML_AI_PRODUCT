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
    headers: { "Content-Type": "application/json", ...options?.headers },
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
  const protectedBulletin =
    path.startsWith("/bulletins/") && path !== "/bulletins/email-action";
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers:
      protectedBulletin && bulletinOperatorKey
        ? { Authorization: `Bearer ${bulletinOperatorKey}` }
        : undefined,
  });
}
