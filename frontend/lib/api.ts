// The one way the dashboard talks to the Django REST API (/api/v1, same origin).
//
// * Session cookie + CSRF token (section 3.8): unsafe requests send X-CSRFToken.
// * Automatic requests (polling, refreshes) send X-Poll: 1, so an unattended
//   dashboard does not count as user activity (plan decision D8).
// * A change refused with code "reauthenticate" asks for the password, then is
//   retried once.

const BASE = "/api/v1/";
const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);
const UNREACHABLE = "Cannot reach the server. Check that the system is running.";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public fields?: Record<string, string[]>,
    /** The parsed JSON body of the error response, if it had one (for example a topology import report). */
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  poll?: boolean;
  signal?: AbortSignal;
}

let memoryToken: string | null = null;
let reauthHandler: (() => Promise<boolean>) | null = null;
let reauthCancel: (() => void) | null = null;
let unauthenticatedHandler: (() => void) | null = null;

/**
 * The ReauthDialog registers itself here so that any request can ask for the password.
 * `cancel` closes the dialog when the session ends while it is open.
 */
export function setReauthHandler(handler: (() => Promise<boolean>) | null, cancel: (() => void) | null = null) {
  reauthHandler = handler;
  reauthCancel = cancel;
}

/** Called when the session has ended (logged out elsewhere, expired, or the server restarted). */
export function setUnauthenticatedHandler(handler: (() => void) | null) {
  unauthenticatedHandler = handler;
}

export function rememberCsrfToken(token: string | undefined) {
  if (token) memoryToken = token;
}

function cookieToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function csrfToken(): Promise<string> {
  const token = cookieToken() ?? memoryToken;
  if (token) return token;
  let response: Response;
  try {
    response = await fetch(BASE + "auth/csrf", { credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (!response.ok) throw await toError(response);
  const data = await readJson<{ csrfToken: string }>(response);
  memoryToken = data.csrfToken;
  return cookieToken() ?? data.csrfToken;
}

/** The JSON body of a successful response. A cancelled request stays a cancellation. */
async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(response.status, "The server sent a reply that could not be read. Please try again.");
  }
}

function firstMessages(data: Record<string, unknown>): { message: string; fields: Record<string, string[]> } {
  const fields: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(data)) {
    if (key === "code") continue;
    if (Array.isArray(value)) fields[key] = value.map(String);
    else if (typeof value === "string") fields[key] = [value];
  }
  const parts = Object.entries(fields).map(([key, messages]) =>
    ["detail", "non_field_errors", "parameters"].includes(key) ? messages.join(" ") : `${key.replace(/_/g, " ")}: ${messages.join(" ")}`,
  );
  return { message: parts.join(" ") || "The request was not accepted.", fields };
}

async function toError(response: Response): Promise<ApiError> {
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    // not JSON (for example a proxy error page)
  }
  if (response.status === 429) {
    // DRF's own text ("Request was throttled. Expected available in 3412 seconds.") is not plain language
    const minutes = Math.max(1, Math.ceil((Number(response.headers.get("Retry-After")) || 60) / 60));
    const wait = minutes === 1 ? "1 minute" : `${minutes} minutes`;
    return new ApiError(429, `Too many attempts. Please try again in ${wait}.`, "throttled", undefined, data);
  }
  if (response.status === 404) {
    // DRF's own text ("No SimulationScenario matches the given query.") names a database table, not the item
    const code = data && typeof data === "object" && "code" in data && typeof data.code === "string" ? data.code : undefined;
    return new ApiError(404, "This item no longer exists.", code, undefined, data);
  }
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const record = data as Record<string, unknown>;
    const { message, fields } = firstMessages(record);
    return new ApiError(response.status, message, typeof record.code === "string" ? record.code : undefined, fields, data);
  }
  if (response.status >= 500) {
    return new ApiError(response.status, "The server had a problem. Please try again shortly.", undefined, undefined, data);
  }
  return new ApiError(response.status, `The request failed (HTTP ${response.status}).`, undefined, undefined, data);
}

export async function api<T>(path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.poll) headers["X-Poll"] = "1";
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (!SAFE.has(method)) headers["X-CSRFToken"] = await csrfToken();

  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, UNREACHABLE);
  }

  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return readJson<T>(response);
  }
  const html = (response.headers.get("content-type") ?? "").includes("text/html");
  const error = await toError(response);
  const unsafe = !SAFE.has(method);
  // A stale CSRF token (for example after logging in on another tab): fetch a fresh one and retry once.
  if (unsafe && !retried && response.status === 403 && (html || error.message.startsWith("CSRF Failed"))) {
    memoryToken = null;
    return api<T>(path, options, true);
  }
  if (unsafe && !retried && error.code === "reauthenticate" && reauthHandler) {
    if (await reauthHandler()) return api<T>(path, options, true);
  }
  if (error.code === "not_authenticated") {
    reauthCancel?.(); // the password cannot help once the session has ended
    unauthenticatedHandler?.();
  }
  return Promise.reject(error);
}

export const get = <T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}) =>
  api<T>(path, { ...options, method: "GET" });

export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });

export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });

export const del = (path: string) => api<void>(path, { method: "DELETE" });

/** Build a query string, leaving out empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
