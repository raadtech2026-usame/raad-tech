import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../shared/stores/authStore";
import { RouteGuard } from "./RouteGuard";

function renderGuardedRoute(allowedRoles?: ("org_admin" | "founder")[]) {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route
          path="/dashboard"
          element={
            <RouteGuard allowedRoles={allowedRoles}>
              <div>Protected content</div>
            </RouteGuard>
          }
        />
        <Route path="/" element={<div>Home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RouteGuard", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: null,
      accessToken: null,
      refreshToken: null,
      status: "signed_out",
      error: null,
    });
  });

  it("redirects to /login when not authenticated", () => {
    renderGuardedRoute();
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("renders children when authenticated and no role restriction is given", () => {
    useAuthStore.setState({
      status: "authenticated",
      principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
    });
    renderGuardedRoute();
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("redirects to / when the role is not in allowedRoles", () => {
    useAuthStore.setState({
      status: "authenticated",
      principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
    });
    renderGuardedRoute(["founder"]);
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("renders children when the role is in allowedRoles", () => {
    useAuthStore.setState({
      status: "authenticated",
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
    });
    renderGuardedRoute(["founder"]);
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });
});
