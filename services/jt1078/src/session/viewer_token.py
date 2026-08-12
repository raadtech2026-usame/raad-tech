"""Signed, short-lived, single-use viewer tokens (ADR-0024 §5 point 2, §15 — D5 enforcement).
**The relay performs no user authentication and no RBAC of its own** — it trusts exactly one
thing: a token the Business API minted at session-creation time *after* full `enforce_d5()` +
RBAC evaluation (`interfaces/http/policy_guards.py`). This module is the *reference*
implementation of that signing scheme (HMAC-SHA256 over `session_id` + expiry, stdlib `hmac`/
`hashlib`/`secrets` only, mirroring `device-gateway`'s own `auth_code_hashing.py` precedent of
hand-rolling a narrow crypto need rather than a new dependency) — a real Business API adapter
would need to mint tokens with the *same* shared secret (an env var, composition-root-only,
matching ADR-0022's own "secrets are environment variables... never a database-editable setting"
precedent), not build a second, divergent scheme.

**Single-use is enforced by `SingleUseTokenGuard`** — a signature check alone only proves the
token was minted by someone holding the shared secret and hasn't expired; it does not, by itself,
prevent replay. `InMemorySingleUseTokenGuard` (default) is real but single-process-only — correct
for a single-relay-process deployment (this MVP's own topology, ADR-0024 §12), disclosed as a
real limitation the moment this relay is ever scaled to more than one process.
`RedisSingleUseTokenGuard` (bound whenever a broker is configured) gives a genuine cross-process
guarantee via `SET NX` (atomic "claim if not already claimed").
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod

from redis.asyncio import Redis

_DEFAULT_TTL_SECONDS = 30.0


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def mint_token(
    *, session_id: str, secret: bytes, ttl_seconds: float = _DEFAULT_TTL_SECONDS
) -> str:
    payload = json.dumps(
        {"session_id": session_id, "expires_at": time.time() + ttl_seconds}
    ).encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(signature)}"


def verify_token_signature(token: str, *, secret: bytes) -> str | None:
    """Checks the HMAC signature and expiry only — does *not* check single-use (see
    `SingleUseTokenGuard`, a separate, stateful concern). Returns the `session_id` on success,
    `None` on any failure (malformed token, bad signature, expired) — deliberately no distinction
    between failure reasons in the return value, so a caller can't be tempted to leak *why* a
    token was rejected to an unauthenticated client."""
    try:
        payload_part, signature_part = token.split(".")
        payload_bytes = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
    except Exception:  # noqa: BLE001 - any malformed input is just "invalid", not a crash
        return None

    expected_signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(payload_bytes)
        session_id = payload["session_id"]
        expires_at = payload["expires_at"]
    except (ValueError, KeyError, TypeError):
        return None

    if time.time() > expires_at:
        return None

    return session_id


class SingleUseTokenGuard(ABC):
    @abstractmethod
    async def claim(self, token: str) -> bool:
        """Returns `True` the first time this exact token string is claimed, `False` on every
        subsequent attempt (a real, already-used or racing-duplicate token)."""
        raise NotImplementedError


class InMemorySingleUseTokenGuard(SingleUseTokenGuard):
    def __init__(self, *, ttl_seconds: float = _DEFAULT_TTL_SECONDS * 4) -> None:
        self._ttl_seconds = ttl_seconds
        self._claimed: dict[str, float] = {}

    async def claim(self, token: str) -> bool:
        self._sweep()
        if token in self._claimed:
            return False
        self._claimed[token] = time.monotonic() + self._ttl_seconds
        return True

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [t for t, expiry in self._claimed.items() if expiry < now]
        for token in expired:
            del self._claimed[token]


class RedisSingleUseTokenGuard(SingleUseTokenGuard):
    def __init__(self, redis_client: Redis, *, ttl_seconds: float = _DEFAULT_TTL_SECONDS * 4) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    async def claim(self, token: str) -> bool:
        key = f"jt1078:viewer_token_claimed:{token}"
        claimed = await self._redis.set(key, "1", nx=True, ex=int(self._ttl_seconds))
        return bool(claimed)
