/**
 * ADR-0039 §6 — client-side surfacing of a tenant-wide subscription block.
 *
 * **This is presentation, never authorization** (`.claude/rules/frontend.md` #2). The server
 * has already refused the request by the time anything here runs; this store exists only so the
 * user sees "your school's subscription is inactive" instead of a generic red toast on every
 * screen. Clearing this state grants nothing — the next API call is refused again by
 * `interfaces/http/subscription_guard`.
 *
 * Deliberately a tiny module-level store with subscribers rather than React context: the API
 * client (`shared/api/client.ts`) is a plain module with no React tree above it, and it is the
 * only thing that can observe the error. This mirrors `configureUnauthorizedHandler`'s own
 * established shape in that same file exactly, rather than inventing a second pattern for the
 * same problem.
 */

/** The wire code `core/policies/organization_access.py` emits. Part of the API contract — the
 * backend's own constant carries the same "must not be renamed without a version bump" note. */
export const ORGANIZATION_SUBSCRIPTION_INACTIVE = "ORGANIZATION_SUBSCRIPTION_INACTIVE";

/** What the backend discloses to an Org Admin (`subscription_guard._details_for`). Every field
 * is optional because an ordinary member (Driver, Parent) is deliberately told none of it. */
export interface SubscriptionBlockDetails {
  subscriptionStatus?: string | null;
  currentPeriodEnd?: string | null;
  gracePeriodEndsAt?: string | null;
}

export interface SubscriptionBlockState {
  blocked: boolean;
  message: string | null;
  details: SubscriptionBlockDetails | null;
}

const initialState: SubscriptionBlockState = {
  blocked: false,
  message: null,
  details: null,
};

let state: SubscriptionBlockState = initialState;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

/** `useSyncExternalStore` contract: must return a stable reference while nothing has changed,
 * or React re-renders forever. */
export function getSubscriptionBlockState(): SubscriptionBlockState {
  return state;
}

export function subscribeToSubscriptionBlock(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Called by the API client when a response carries the block code. Idempotent: repeated
 * reports of an unchanged block do not notify, so a page firing several parallel requests that
 * all fail the same way re-renders once, not once per request. */
export function reportSubscriptionBlocked(
  message: string,
  details: SubscriptionBlockDetails | null,
): void {
  if (
    state.blocked &&
    state.message === message &&
    JSON.stringify(state.details) === JSON.stringify(details)
  ) {
    return;
  }
  state = { blocked: true, message, details };
  emit();
}

/** Called after a successful authenticated response, and on sign-out. A tenant that has just
 * paid must not stay locked out of its own dashboard until a hard refresh. */
export function clearSubscriptionBlock(): void {
  if (!state.blocked) {
    return;
  }
  state = initialState;
  emit();
}

/** Normalises the backend's snake_case `details` payload. Returns `null` for the ordinary-member
 * case, where the backend deliberately sends no detail at all. */
export function parseSubscriptionBlockDetails(
  raw: unknown,
): SubscriptionBlockDetails | null {
  if (raw === null || typeof raw !== "object") {
    return null;
  }
  const record = raw as Record<string, unknown>;
  const read = (key: string): string | null =>
    typeof record[key] === "string" ? (record[key] as string) : null;
  return {
    subscriptionStatus: read("subscription_status"),
    currentPeriodEnd: read("current_period_end"),
    gracePeriodEndsAt: read("grace_period_ends_at"),
  };
}
