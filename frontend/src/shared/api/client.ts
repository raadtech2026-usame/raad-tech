import { env } from "../../config/env";
import { ApiError, type ApiErrorDetail } from "./types";

/** Set once by `authStore` (avoids a circular import: this module never imports the store).
 * Returns the current access token, or `null` if signed out. */
type TokenGetter = () => string | null;
let getAccessToken: TokenGetter = () => null;
export function configureAuthTokenGetter(getter: TokenGetter): void {
  getAccessToken = getter;
}

/** Set once by `authStore` — attempts a token refresh, returns whether it succeeded. Wired
 * this way (not called directly) for the same reason as the getter above. */
type UnauthorizedHandler = () => Promise<boolean>;
let handleUnauthorized: UnauthorizedHandler | null = null;
export function configureUnauthorizedHandler(handler: UnauthorizedHandler): void {
  handleUnauthorized = handler;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Skip attaching `Authorization` (login/refresh themselves must not send a stale/absent
   * token) and skip the 401-triggers-refresh retry (refreshing itself can 401). */
  anonymous?: boolean;
}

function toCamelCaseDetail(raw: {
  code: string;
  message: string;
  correlation_id: string | null;
  details?: unknown;
  reason?: string | null;
  required_action?: string | null;
}): ApiErrorDetail {
  return {
    code: raw.code,
    message: raw.message,
    correlationId: raw.correlation_id,
    details: raw.details,
    reason: raw.reason,
    requiredAction: raw.required_action,
  };
}

async function parseErrorEnvelope(response: Response): Promise<ApiErrorDetail> {
  try {
    const body = (await response.json()) as { error?: Parameters<typeof toCamelCaseDetail>[0] };
    if (body.error) {
      return toCamelCaseDetail(body.error);
    }
  } catch {
    // Response body wasn't the documented envelope (e.g. a proxy/gateway error) - fall through.
  }
  return {
    code: "UNKNOWN_ERROR",
    message: `Request failed with status ${response.status}.`,
    correlationId: null,
  };
}

async function rawRequest<T>(path: string, options: RequestOptions): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!options.anonymous) {
    const token = getAccessToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    const detail = await parseErrorEnvelope(response);
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

/** Typed request with one automatic retry-after-refresh on a 401 (`.claude/rules/api.md` #3:
 * bearer auth on every authenticated request) — never retried more than once, and never for
 * an already-`anonymous` call (login/refresh themselves), so a genuinely expired refresh
 * token fails once and lets the caller (ultimately `authStore`) sign the user out. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, options);
  } catch (error) {
    const isUnauthorized = error instanceof ApiError && error.status === 401;
    if (isUnauthorized && !options.anonymous && handleUnauthorized) {
      const refreshed = await handleUnauthorized();
      if (refreshed) {
        return await rawRequest<T>(path, options);
      }
    }
    throw error;
  }
}
