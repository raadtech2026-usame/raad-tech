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
  children: ReactNode;
}

export function RouteGuard({ allowedRoles, children }: RouteGuardProps) {
  const status = useAuthStore((s) => s.status);
  const principal = useAuthStore((s) => s.principal);
  const location = useLocation();

  if (status !== "authenticated" || !principal) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(principal.role)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
