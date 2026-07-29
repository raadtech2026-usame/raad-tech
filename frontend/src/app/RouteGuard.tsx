import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "../shared/stores/authStore";
import type { Role } from "../shared/api/types";

interface RouteGuardProps {
  /** Omit to allow any authenticated role. `.claude/rules/frontend.md` #2: this is
   * *presentation* of server-enforced scope (redirect to a sensible place, hide nav a role
   * can't use) — the real authorization is RBAC + `ScopeResolver` + domain policies on the
   * backend; this guard must never be the only thing standing between a role and a capability
   * it shouldn't have. */
  allowedRoles?: Role[];
  /** ADR-0017 / ADR-0017 Amendment: when true, a signed-in principal still holding a one-time
   * hand-off temporary password (`Principal.isPasswordChangeRequired`) is redirected to
   * `/change-password` instead of the guarded content. Only set on `/platform`/`/org` — never
   * on `/mobile-only` or `/change-password` itself: Driver/Parent have no web change-password
   * screen to be sent to at all (`.claude/rules/flutter.md` #1), and the gate route obviously
   * can't gate itself. */
  enforcePasswordChange?: boolean;
  children: ReactNode;
}

export function RouteGuard({
  allowedRoles,
  enforcePasswordChange = false,
  children,
}: RouteGuardProps) {
  const status = useAuthStore((s) => s.status);
  const principal = useAuthStore((s) => s.principal);
  const location = useLocation();

  if (status !== "authenticated" || !principal) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(principal.role)) {
    return <Navigate to="/" replace />;
  }

  if (enforcePasswordChange && principal.isPasswordChangeRequired) {
    return <Navigate to="/change-password" replace />;
  }

  return <>{children}</>;
}
