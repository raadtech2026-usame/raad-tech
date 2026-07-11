"""JWT token service (Backend LLD §17 `security`: "jwt issue/verify").

`TokenService` is the authentication contract every module depends on to issue/verify
tokens; `JwtTokenService` is its concrete HS256 implementation, built on the standard
library only (`hmac`/`hashlib`/`base64`/`json`) rather than a third-party JWT dependency —
this phase adds no new package dependency (Rule: Workflow #2, only approved deps).

No refresh-token *persistence* or session management lives here (out of scope for this
phase) — issuing a refresh token only produces a signed, stateless claim; revocation/rotation
is a `modules/iam` concern for a later phase.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from raad.core.security.claims import TokenClaims, TokenType
from raad.core.security.exceptions import InvalidTokenError, TokenExpiredError
from raad.core.tenancy.principal import Role
from raad.core.time.clock import Clock

_SUPPORTED_ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


class TokenService(ABC):
    @abstractmethod
    def issue_token_pair(
        self, *, subject: str, role: Role, org_id: str | None
    ) -> TokenPair:
        raise NotImplementedError

    @abstractmethod
    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        """Verifies signature and expiry, and that `token_type` matches `expected_type`
        (rejects e.g. a refresh token presented where an access token is required). Raises
        `InvalidTokenError` / `TokenExpiredError` (both `AuthenticationError`) on failure —
        never returns a claims object for an invalid token."""
        raise NotImplementedError


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class JwtTokenService(TokenService):
    """HS256-only by construction — the Backend LLD's `AuthSettings.jwt_algorithm` default is
    HS256 and no external identity provider / asymmetric-key flow is in scope for this phase.
    Fails fast on construction if given anything else, rather than silently ignoring it."""

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str,
        access_token_ttl_seconds: int,
        refresh_token_ttl_seconds: int,
        clock: Clock,
    ) -> None:
        if algorithm != _SUPPORTED_ALGORITHM:
            raise ValueError(
                f"JwtTokenService only supports {_SUPPORTED_ALGORITHM}, got {algorithm!r}"
            )
        if not secret_key:
            raise ValueError("secret_key must not be empty")
        self._secret_key = secret_key.encode("utf-8")
        self._algorithm = algorithm
        self._access_ttl = timedelta(seconds=access_token_ttl_seconds)
        self._refresh_ttl = timedelta(seconds=refresh_token_ttl_seconds)
        self._clock = clock

    def issue_token_pair(
        self, *, subject: str, role: Role, org_id: str | None
    ) -> TokenPair:
        issued_at = self._clock.now()
        access = self._encode(
            subject=subject,
            role=role,
            org_id=org_id,
            token_type=TokenType.ACCESS,
            issued_at=issued_at,
            ttl=self._access_ttl,
        )
        refresh = self._encode(
            subject=subject,
            role=role,
            org_id=org_id,
            token_type=TokenType.REFRESH,
            issued_at=issued_at,
            ttl=self._refresh_ttl,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(self._access_ttl.total_seconds()),
        )

    def decode(self, token: str, *, expected_type: TokenType) -> TokenClaims:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
        except ValueError as exc:
            raise InvalidTokenError("Malformed token.") from exc

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_signature = hmac.new(
            self._secret_key, signing_input, hashlib.sha256
        ).digest()
        try:
            actual_signature = _b64url_decode(signature_b64)
        except Exception as exc:
            raise InvalidTokenError("Malformed token signature.") from exc

        if not hmac.compare_digest(expected_signature, actual_signature):
            raise InvalidTokenError("Token signature verification failed.")

        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:
            raise InvalidTokenError("Malformed token payload.") from exc

        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        if self._clock.now() >= expires_at:
            raise TokenExpiredError("Token has expired.")

        token_type = TokenType(payload["token_type"])
        if token_type is not expected_type:
            raise InvalidTokenError(
                f"Expected a {expected_type.value} token, got {token_type.value}."
            )

        return TokenClaims(
            subject=payload["sub"],
            role=Role(payload["role"]),
            org_id=payload["org_id"],
            token_type=token_type,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=expires_at,
            token_id=payload["jti"],
        )

    def _encode(
        self,
        *,
        subject: str,
        role: Role,
        org_id: str | None,
        token_type: TokenType,
        issued_at: datetime,
        ttl: timedelta,
    ) -> str:
        header = {"alg": self._algorithm, "typ": "JWT"}
        expires_at = issued_at + ttl
        payload = {
            "sub": subject,
            "role": role.value,
            "org_id": org_id,
            "token_type": token_type.value,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_hex(16),
        }
        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(self._secret_key, signing_input, hashlib.sha256).digest()
        return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"
