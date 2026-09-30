import { ApiError } from "../../shared/api/types";

/** What went wrong, from the sign-in form's point of view. Each kind drives a different visual
 * state (`useLoginPhase`) and message, so an account lockout never looks like a typo and a dead
 * network never looks like a wrong password. */
export type LoginFailureKind =
  | "invalid_credentials"
  | "locked"
  | "rate_limited"
  | "network"
  | "unknown";

export interface LoginFailure {
  kind: LoginFailureKind;
  message: string;
}

function formatClockTime(iso: string): string | null {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return null;
  }
  return when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function lockedUntil(details: unknown): string | null {
  if (details && typeof details === "object" && "locked_until" in details) {
    const value = (details as { locked_until: unknown }).locked_until;
    return typeof value === "string" ? formatClockTime(value) : null;
  }
  return null;
}

/** Classifies the error `authStore.login` rethrows. The store itself only keeps a message
 * string, so this is done here, at the one screen that needs the distinction.
 *
 * `fetch` rejects with a `TypeError` when the request never reaches a server (offline, DNS,
 * CORS, API down); that is not an `ApiError`, and the store's own fallback text ("Login
 * failed.") would tell the user nothing about what to do next. */
export function describeLoginFailure(error: unknown): LoginFailure {
  if (error instanceof ApiError) {
    if (error.code === "ACCOUNT_LOCKED") {
      const until = lockedUntil(error.details);
      return {
        kind: "locked",
        message: until
          ? `This account is locked after too many failed attempts. Try again after ${until}.`
          : error.message,
      };
    }
    if (error.status === 429) {
      return { kind: "rate_limited", message: error.message };
    }
    if (error.status === 401) {
      return { kind: "invalid_credentials", message: error.message };
    }
    return { kind: "unknown", message: error.message };
  }
  if (error instanceof TypeError) {
    return {
      kind: "network",
      message: "Can't reach RAAD. Check your connection and try again.",
    };
  }
  return { kind: "unknown", message: "Sign-in failed. Please try again." };
}
