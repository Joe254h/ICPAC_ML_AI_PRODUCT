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
  const visitor = visitorId();
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(visitor ? { "X-Visitor-Id": visitor } : {}),
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

// Anonymous conversation ownership, created automatically without a login.
// Clearing browser data starts a new history. Staff credentials stay in memory.
let browserVisitorId = "";
function visitorId(): string {
  if (typeof window === "undefined") return "";
  if (browserVisitorId) return browserVisitorId;
  try {
    const saved = window.localStorage.getItem("icpac-visitor-id");
    if (saved && /^[0-9a-f]{32}$/.test(saved))
      return (browserVisitorId = saved);
  } catch {
    // Restricted browser storage: retain this tab's history for its lifetime.
  }
  browserVisitorId = window.crypto.randomUUID().replaceAll("-", "");
  try {
    window.localStorage.setItem("icpac-visitor-id", browserVisitorId);
  } catch {
    // The in-memory identifier still works when storage is unavailable.
  }
  return browserVisitorId;
}

// Kept only in this tab's memory, never in browser storage or public environment variables.
let bulletinOperatorKey = "";
export function setBulletinOperatorKey(key: string) {
  bulletinOperatorKey = key;
}
export function getBulletinOperatorKey() {
  return bulletinOperatorKey;
}

/** The person signed in with the staff key in this tab, if any. */
export type StaffUser = { name: string; roles: string[] };
let staffUser: StaffUser | null = null;
export function setStaffUser(user: StaffUser | null) {
  staffUser = user;
}
export function getStaffUser() {
  return staffUser;
}

/** A file sent as it is (not JSON), for example a NetCDF forecast. */
export function upload<T>(path: string, file: File) {
  return request<T>(path, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/x-netcdf" },
  });
}

/** A file of any format, sent as it is. */
export function uploadFile<T>(path: string, file: File) {
  return request<T>(path, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

export function mutate<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Requests through the website's proxy carry at most about 4.5 MB: a larger file goes in
 * numbered parts. Returns the upload's id, for the endpoint that finishes it. */
export async function uploadInParts(
  file: File,
  purpose: "model" | "attachment",
  progress?: (sent: number) => void,
): Promise<string> {
  const started = await mutate<{ id: string; part_bytes: number }>("/uploads", {
    purpose,
    name: file.name,
    size: file.size,
  });
  for (
    let index = 0, offset = 0;
    offset < file.size;
    index += 1, offset += started.part_bytes
  ) {
    await request(`/uploads/${started.id}/parts/${index}`, {
      method: "POST",
      body: file.slice(offset, offset + started.part_bytes),
      headers: { "Content-Type": "application/octet-stream" },
    });
    progress?.(Math.min(file.size, offset + started.part_bytes));
  }
  return started.id;
}
