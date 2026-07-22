/** Wire types mirroring the backend exactly — `backend/raad/modules/iam/api/schemas.py` and
 * `backend/raad/core/errors/envelope.py`. Roles are transported lower-case snake_case
 * (`core.tenancy.principal.Role` case-folded, see that schemas module's own docstring). */

export type Role =
  | "founder"
  | "regional_manager"
  | "support_staff"
  | "finance_staff"
  | "org_admin"
  | "driver"
  | "parent";

export interface Principal {
  userId: string;
  role: Role;
  organizationId: string | null;
  regionIds: string[];
}

export interface TokenPair {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  refreshToken: string;
  principal: Principal;
}

/** `core/errors/envelope.py`'s `ErrorEnvelope` — the one error shape every endpoint returns
 * (`.claude/rules/api.md` #4: "do not invent a different error shape per module"). */
export interface ApiErrorDetail {
  code: string;
  message: string;
  correlationId: string | null;
  details?: unknown;
  reason?: string | null;
  requiredAction?: string | null;
}

/** API Contracts §7's two pagination envelope shapes (`backend/raad/interfaces/http/
 * pagination.py`'s `OffsetPageResponse`/`CursorPageResponse`) — every list endpoint returns
 * one of these two, never a bare array (`.claude/rules/api.md` #4's "standard envelope"
 * principle extended to lists). */
export interface OffsetPage<T> {
  data: T[];
  page: { total: number; page: number; pageSize: number };
}

export interface CursorPage<T> {
  data: T[];
  page: { limit: number; nextCursor: string | null; hasMore: boolean };
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly correlationId: string | null;
  readonly details?: unknown;
  readonly reason?: string | null;
  readonly requiredAction?: string | null;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
    this.correlationId = detail.correlationId;
    this.details = detail.details;
    this.reason = detail.reason;
    this.requiredAction = detail.requiredAction;
  }
}
