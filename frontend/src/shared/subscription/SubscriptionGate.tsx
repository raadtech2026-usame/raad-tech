import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { LoadingScreen } from "../components/LoadingScreen/LoadingScreen";
import { useSubscriptionGate } from "./useSubscriptionGate";

/** Where a tenant whose organization has no usable subscription is sent (ADR-0039, amended
 * 2026-09-09). Deliberately outside the gated branch of the router, or the redirect loops. */
export const SUBSCRIPTION_REQUIRED_PATH = "/org/subscription";

/**
 * Blocks the Organization dashboard until the tenant's subscription is in good standing.
 *
 * **Its own component rather than another flag on `RouteGuard`.** `RouteGuard` answers "who are
 * you" — authentication, role, forced password change — from state already in memory, and needs
 * no data fetching. Folding a subscription lookup into it would give every guarded route in the
 * app a react-query dependency for a question only the `/org` branch asks. Separate components,
 * composed by the router, keep each one testable on its own.
 *
 * **Mounted above `AppShell`, so the redirect happens before any protected page loads.** The
 * alternative — mount first, react to the resulting 403s — means the user watches a dashboard
 * fill with errors before being moved, which is exactly what the requirement rules out.
 *
 * Presentation only (`.claude/rules/frontend.md` #2): `interfaces/http/subscription_guard`
 * refuses every `/api/v1` route server-side regardless of what this component decides.
 */
export function SubscriptionGate({ children }: { children: ReactNode }) {
  const gate = useSubscriptionGate();

  if (gate.status === "checking") {
    return <LoadingScreen label="Checking your subscription…" />;
  }
  if (gate.status === "blocked") {
    return <Navigate to={SUBSCRIPTION_REQUIRED_PATH} replace />;
  }
  return <>{children}</>;
}
