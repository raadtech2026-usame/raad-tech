import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../../shared/stores/authStore";
import { ApiError, type Principal } from "../../shared/api/types";
import { LoginPage } from "./LoginPage";
import { ERROR_SETTLE_MS, SUCCESS_HOLD_MS } from "./useLoginPhase";

const orgAdmin: Principal = {
  userId: "u1",
  role: "org_admin",
  organizationId: "org-1",
  regionIds: [],
  isPasswordChangeRequired: false,
};

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/org" element={<div>Org dashboard</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockReducedMotion(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" ? reduced : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

/** Stands in for `authStore.login`: resolves by flipping the store to authenticated (as the real
 * one does), or rejects with the given error after setting the store's own error state. */
function stubLogin(outcome: { error?: unknown }) {
  useAuthStore.setState({
    login: vi.fn(async () => {
      useAuthStore.setState({ status: "authenticating", error: null });
      if (outcome.error) {
        useAuthStore.setState({ status: "signed_out", error: "failed" });
        throw outcome.error;
      }
      useAuthStore.setState({ status: "authenticated", principal: orgAdmin });
    }),
  });
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("Email or phone"), {
    target: { value: "admin@school.org" },
  });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-pass" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

function phase(container: HTMLElement) {
  return container.querySelector("main")?.getAttribute("data-phase");
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockReducedMotion(false);
    useAuthStore.setState({
      principal: null,
      accessToken: null,
      refreshToken: null,
      status: "signed_out",
      error: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows only the brand, the two fields and the sign-in button", () => {
    renderLogin();
    expect(screen.getByRole("heading", { level: 1, name: "Sign in to RAAD" })).toBeInTheDocument();
    expect(screen.getByAltText("RAAD")).toBeInTheDocument();
    expect(screen.getByLabelText("Email or phone")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText(/SOC-2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Authorized school staff/)).not.toBeInTheDocument();
  });

  it("keeps the animated scene out of the accessibility tree", () => {
    const { container } = renderLogin();
    const scene = container.querySelector("[data-phase][aria-hidden='true']");
    expect(scene).not.toBeNull();
  });

  it("sends an already signed-in user straight to their dashboard", () => {
    useAuthStore.setState({ status: "authenticated", principal: orgAdmin });
    renderLogin();
    expect(screen.getByText("Org dashboard")).toBeInTheDocument();
  });

  it("plays the success beat, then opens the dashboard", async () => {
    vi.useFakeTimers();
    stubLogin({});
    const { container } = renderLogin();

    await act(async () => fillAndSubmit());

    expect(phase(container)).toBe("success");
    expect(screen.getByRole("button", { name: "Signed in" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Signed in. Opening your dashboard.");
    expect(screen.queryByText("Org dashboard")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(SUCCESS_HOLD_MS);
    });
    expect(screen.getByText("Org dashboard")).toBeInTheDocument();
  });

  it("skips the success hold entirely under reduced motion", async () => {
    mockReducedMotion(true);
    stubLogin({});
    renderLogin();

    await act(async () => fillAndSubmit());

    expect(screen.getByText("Org dashboard")).toBeInTheDocument();
  });

  it("shows the server's message for wrong credentials, marks the fields, then settles", async () => {
    vi.useFakeTimers();
    stubLogin({
      error: new ApiError(401, {
        code: "UNAUTHENTICATED",
        message: "Invalid credentials.",
        correlationId: null,
      }),
    });
    const { container } = renderLogin();

    await act(async () => fillAndSubmit());

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Invalid credentials.");
    expect(phase(container)).toBe("error");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAttribute("aria-describedby", alert.id);
    expect(password).toHaveFocus();

    act(() => {
      vi.advanceTimersByTime(ERROR_SETTLE_MS);
    });
    expect(phase(container)).toBe("engaged");
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("clears the error as soon as the user edits a field", async () => {
    stubLogin({
      error: new ApiError(401, {
        code: "UNAUTHENTICATED",
        message: "Invalid credentials.",
        correlationId: null,
      }),
    });
    renderLogin();

    await act(async () => fillAndSubmit());
    expect(screen.getByRole("alert")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "another" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("tells a locked-out user when they can try again, and holds the locked state", async () => {
    vi.useFakeTimers();
    stubLogin({
      error: new ApiError(401, {
        code: "ACCOUNT_LOCKED",
        message: "Account is temporarily locked due to too many failed login attempts.",
        correlationId: null,
        details: { locked_until: "2026-09-30T14:05:00+00:00" },
      }),
    });
    const { container } = renderLogin();

    await act(async () => fillAndSubmit());

    expect(screen.getByRole("alert")).toHaveTextContent(/locked .* Try again after/);
    expect(phase(container)).toBe("locked");
    act(() => {
      vi.advanceTimersByTime(ERROR_SETTLE_MS * 2);
    });
    expect(phase(container)).toBe("locked");
  });

  it("explains a network failure instead of a generic 'Login failed.'", async () => {
    stubLogin({ error: new TypeError("Failed to fetch") });
    renderLogin();

    await act(async () => fillAndSubmit());

    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach RAAD.");
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("aria-invalid");
  });

  it("warns when Caps Lock is on in the password field", () => {
    renderLogin();
    const password = screen.getByLabelText("Password");
    fireEvent.keyUp(password, { key: "A", modifierCapsLock: true });
    expect(screen.getByText("Caps Lock is on")).toBeInTheDocument();
    fireEvent.keyUp(password, { key: "a", modifierCapsLock: false });
    expect(screen.queryByText("Caps Lock is on")).not.toBeInTheDocument();
  });

  it("toggles password visibility", () => {
    renderLogin();
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
  });
});
