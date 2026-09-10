import { useQuery } from "@tanstack/react-query";
import { getCurrentSubscription, type SubscriptionStatus } from "../../features/billing/api";
import { useAuthStore } from "../stores/authStore";
import { getDashboardType } from "../auth/dashboard";

/**
 * Resolves whether the signed-in tenant's organization may open the dashboard at all
 * (ADR-0039, amended 2026-09-09).
 *
 * **Presentation, never authorization** (`.claude/rules/frontend.md` #2). Every `/api/v1` route
 * is already gated server-side by `interfaces/http/subscription_guard`, which is the real and
 * only enforcement. This hook exists so a blocked organization lands on the payment page
 * *before* a protected screen renders and fires a dozen requests that will each be refused —
 * the difference between a clear "settle your invoice" page and a dashboard of red error toasts.
 * Clearing it client-side grants nothing.
 *
 * **Reads the subscription directly rather than waiting for a 403.** `/billing/*` is exempt from
 * the server guard precisely so a blocked tenant can still reach the recovery path, which makes
 * `GET /billing/subscriptions/current` the one call that always answers. Waiting for some other
 * request to be refused would mean the redirect happens *after* the protected page mounted,
 * which is what the requirement rules out. The API client's own 403 interceptor stays in place
 * as the safety net for anything this misses.
 */

/** Mirrors `core/policies/organization_access._GRANTING_STATES`.
 *
 * A deliberate duplication of a server-side rule, and safe for one reason: it can only ever be
 * *more* restrictive in effect than the server, never less. If this list drifted wider, the user
 * would reach a dashboard whose every request the server still refuses; if it drifted narrower,
 * they see the payment page early. Neither grants access. `grace_period` grants because access
 * ends when grace *ends* — see the policy's own comment for why that ordering matters.
 */
const GRANTING_STATUSES: ReadonlySet<string> = new Set<SubscriptionStatus>([
  "trial",
  "active",
  "grace_period",
]);

export type SubscriptionGateState =
  | { status: "checking" }
  | { status: "allowed" }
  | { status: "blocked"; subscriptionStatus: SubscriptionStatus | null };

export function useSubscriptionGate(): SubscriptionGateState {
  const principal = useAuthStore((s) => s.principal);

  // Platform staff are not members of any tenant, so a tenant's subscription says nothing about
  // whether they may work — and blocking them would make suspension irreversible, since nobody
  // could inspect or reactivate a suspended school. Same carve-out the server makes.
  const isTenantUser =
    principal !== null && getDashboardType(principal.role) === "organization";

  const query = useQuery({
    queryKey: ["subscription-gate", principal?.organizationId ?? null],
    queryFn: getCurrentSubscription,
    enabled: isTenantUser,
    staleTime: 60_000,
    retry: false,
  });

  if (!isTenantUser) {
    return { status: "allowed" };
  }
  if (query.isPending) {
    return { status: "checking" };
  }
  if (query.isError) {
    // The recovery route itself is unreachable. Blocking here would strand the user on a page
    // that cannot load either, so this fails open and leaves enforcement entirely to the server
    // — which is where it actually lives. A transient network error must not look like a lapsed
    // subscription.
    return { status: "allowed" };
  }

  const subscription = query.data;
  if (subscription && GRANTING_STATUSES.has(subscription.status)) {
    return { status: "allowed" };
  }
  return {
    status: "blocked",
    subscriptionStatus: subscription?.status ?? null,
  };
}
