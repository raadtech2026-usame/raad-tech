import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/types";

vi.mock("../api/authApi", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  refresh: vi.fn(),
  getMe: vi.fn(),
}));

import * as authApi from "../api/authApi";
import { useAuthStore } from "./authStore";

const PRINCIPAL = {
  userId: "user-1",
  role: "org_admin" as const,
  organizationId: "org-1",
  regionIds: [],
};

const TOKEN_PAIR = {
  accessToken: "access-1",
  tokenType: "bearer",
  expiresIn: 900,
  refreshToken: "refresh-1",
  principal: PRINCIPAL,
};

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: null,
      accessToken: null,
      refreshToken: null,
      status: "signed_out",
      error: null,
    });
    vi.mocked(authApi.login).mockReset();
    vi.mocked(authApi.logout).mockReset();
    vi.mocked(authApi.refresh).mockReset();
  });

  it("login success stores the principal and tokens", async () => {
    vi.mocked(authApi.login).mockResolvedValueOnce(TOKEN_PAIR);

    await useAuthStore.getState().login("admin@example.com", "correct-password");

    const state = useAuthStore.getState();
    expect(state.status).toBe("authenticated");
    expect(state.principal).toEqual(PRINCIPAL);
    expect(state.accessToken).toBe("access-1");
    expect(state.refreshToken).toBe("refresh-1");
    expect(state.error).toBeNull();
  });

  it("login failure surfaces the error and stays signed out", async () => {
    vi.mocked(authApi.login).mockRejectedValueOnce(
      new ApiError(401, { code: "UNAUTHENTICATED", message: "Invalid credentials.", correlationId: null }),
    );

    await expect(
      useAuthStore.getState().login("admin@example.com", "wrong-password"),
    ).rejects.toBeInstanceOf(ApiError);

    const state = useAuthStore.getState();
    expect(state.status).toBe("signed_out");
    expect(state.principal).toBeNull();
    expect(state.error).toBe("Invalid credentials.");
  });

  it("logout clears session state even when the server call fails", async () => {
    useAuthStore.setState({
      principal: PRINCIPAL,
      accessToken: "access-1",
      refreshToken: "refresh-1",
      status: "authenticated",
      error: null,
    });
    vi.mocked(authApi.logout).mockRejectedValueOnce(new Error("network down"));

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.status).toBe("signed_out");
    expect(state.principal).toBeNull();
    expect(state.accessToken).toBeNull();
  });

  it("refreshSession with no refresh token returns false without calling the API", async () => {
    const result = await useAuthStore.getState().refreshSession();
    expect(result).toBe(false);
    expect(authApi.refresh).not.toHaveBeenCalled();
  });

  it("refreshSession success rotates both tokens", async () => {
    useAuthStore.setState({
      principal: PRINCIPAL,
      accessToken: "stale-access",
      refreshToken: "refresh-1",
      status: "authenticated",
      error: null,
    });
    vi.mocked(authApi.refresh).mockResolvedValueOnce({
      ...TOKEN_PAIR,
      accessToken: "fresh-access",
      refreshToken: "fresh-refresh",
    });

    const result = await useAuthStore.getState().refreshSession();

    expect(result).toBe(true);
    expect(useAuthStore.getState().accessToken).toBe("fresh-access");
    expect(useAuthStore.getState().refreshToken).toBe("fresh-refresh");
  });

  it("refreshSession failure signs the user out", async () => {
    useAuthStore.setState({
      principal: PRINCIPAL,
      accessToken: "stale-access",
      refreshToken: "expired-refresh",
      status: "authenticated",
      error: null,
    });
    vi.mocked(authApi.refresh).mockRejectedValueOnce(
      new ApiError(401, { code: "UNAUTHENTICATED", message: "Refresh token expired.", correlationId: null }),
    );

    const result = await useAuthStore.getState().refreshSession();

    expect(result).toBe(false);
    expect(useAuthStore.getState().status).toBe("signed_out");
    expect(useAuthStore.getState().principal).toBeNull();
  });
});
