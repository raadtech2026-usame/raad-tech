import { create } from "zustand";
import { configureAuthTokenGetter, configureUnauthorizedHandler } from "../api/client";
import { login as loginApi, logout as logoutApi, refresh as refreshApi } from "../api/authApi";
import { ApiError, type Principal } from "../api/types";

/** Session state — access/refresh tokens live **only** in this in-memory store, never
 * `localStorage`/`sessionStorage`/a cookie (`.claude/rules/frontend.md` #5: "No persistent
 * browser storage of sensitive data"). Deliberate consequence: a hard page reload loses the
 * session and the user must log in again — the accepted trade-off for a SPA whose backend
 * issues raw tokens over JSON (not an httpOnly cookie) rather than reaching for
 * `localStorage`, a common but insecure shortcut this rule exists specifically to rule out.
 */
interface AuthState {
  principal: Principal | null;
  accessToken: string | null;
  refreshToken: string | null;
  status: "signed_out" | "authenticating" | "authenticated";
  error: string | null;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Attempts to exchange the current refresh token for a new pair. Returns whether it
   * succeeded — `shared/api/client.ts`'s 401-retry hook calls this, never the reverse. */
  refreshSession: () => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  principal: null,
  accessToken: null,
  refreshToken: null,
  status: "signed_out",
  error: null,

  async login(identifier, password) {
    set({ status: "authenticating", error: null });
    try {
      const pair = await loginApi(identifier, password);
      set({
        principal: pair.principal,
        accessToken: pair.accessToken,
        refreshToken: pair.refreshToken,
        status: "authenticated",
        error: null,
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Login failed.";
      set({ status: "signed_out", error: message });
      throw error;
    }
  },

  async logout() {
    const { refreshToken } = get();
    if (refreshToken) {
      try {
        await logoutApi(refreshToken);
      } catch {
        // Best-effort - the server-side refresh token revocation failing must not block the
        // client from clearing its own session state below.
      }
    }
    set({ principal: null, accessToken: null, refreshToken: null, status: "signed_out" });
  },

  async refreshSession() {
    const { refreshToken } = get();
    if (!refreshToken) {
      return false;
    }
    try {
      const pair = await refreshApi(refreshToken);
      set({
        principal: pair.principal,
        accessToken: pair.accessToken,
        refreshToken: pair.refreshToken,
        status: "authenticated",
      });
      return true;
    } catch {
      set({ principal: null, accessToken: null, refreshToken: null, status: "signed_out" });
      return false;
    }
  },
}));

configureAuthTokenGetter(() => useAuthStore.getState().accessToken);
configureUnauthorizedHandler(() => useAuthStore.getState().refreshSession());
