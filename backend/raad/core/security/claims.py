"""Token claims model (Backend LLD §17 `security`, §18.2).

`TokenClaims` is the decoded payload of an access/refresh token — the authentication
*contract* between `TokenService` and its callers. Framework-free (no FastAPI, no JWT
library types leak out of `tokens.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from raad.core.tenancy.principal import Role


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class TokenClaims:
    """`org_id` is `None` for RAAD-staff roles, mirroring `Principal.org_id` (§9.2)."""

    subject: str
    role: Role
    org_id: str | None
    token_type: TokenType
    issued_at: datetime
    expires_at: datetime
    token_id: str
