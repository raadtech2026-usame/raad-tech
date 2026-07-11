"""JWT, password hashing, and RBAC foundation (Backend LLD §17 `security`). Public surface of
this package — Phase 4.3 (Authentication & Security Foundation).

Deliberately not implemented here: login/registration flows, refresh-token persistence,
session management, and the concrete RBAC permission matrix — those depend on `modules/iam`
and are out of scope for this phase (foundation/interfaces only).
"""

from raad.core.security.claims import TokenClaims, TokenType
from raad.core.security.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
)
from raad.core.security.password_hashing import PasswordHasher, Pbkdf2PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.permissions import Permission, PermissionEvaluator
from raad.core.security.tokens import JwtTokenService, TokenPair, TokenService
from raad.core.security.utils import constant_time_equals, generate_secure_token

__all__ = [
    "InvalidCredentialsError",
    "InvalidTokenError",
    "JwtTokenService",
    "Permission",
    "PermissionEvaluator",
    "PasswordHasher",
    "PasswordPolicy",
    "Pbkdf2PasswordHasher",
    "TokenClaims",
    "TokenExpiredError",
    "TokenPair",
    "TokenService",
    "TokenType",
    "constant_time_equals",
    "generate_secure_token",
]
