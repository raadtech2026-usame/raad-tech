import { apiRequest } from "./client";
import type { Principal, Role, TokenPair } from "./types";

/** Wire shape of `backend/raad/modules/iam/api/schemas.py`'s `TokenResponse`/`PrincipalResponse`
 * — snake_case, exactly as the backend serializes it. Mapped to the camelCase `TokenPair`/
 * `Principal` types the rest of the app uses immediately after each call below. */
interface PrincipalWire {
  user_id: string;
  role: Role;
  organization_id: string | null;
  region_ids: string[];
}

interface TokenResponseWire {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  principal: PrincipalWire;
}

function toPrincipal(wire: PrincipalWire): Principal {
  return {
    userId: wire.user_id,
    role: wire.role,
    organizationId: wire.organization_id,
    regionIds: wire.region_ids,
  };
}

function toTokenPair(wire: TokenResponseWire): TokenPair {
  return {
    accessToken: wire.access_token,
    tokenType: wire.token_type,
    expiresIn: wire.expires_in,
    refreshToken: wire.refresh_token,
    principal: toPrincipal(wire.principal),
  };
}

export async function login(identifier: string, password: string): Promise<TokenPair> {
  const wire = await apiRequest<TokenResponseWire>("/auth/login", {
    method: "POST",
    body: { identifier, password },
    anonymous: true,
  });
  return toTokenPair(wire);
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const wire = await apiRequest<TokenResponseWire>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
    anonymous: true,
  });
  return toTokenPair(wire);
}

export async function logout(refreshToken: string): Promise<void> {
  await apiRequest<void>("/auth/logout", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export async function getMe(): Promise<Principal> {
  const wire = await apiRequest<PrincipalWire>("/auth/me");
  return toPrincipal(wire);
}
