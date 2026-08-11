"""Auth-code generation/hashing for the `0x0102` credential (ADR-0025 §3). Stdlib-only
(`secrets`/`hashlib`/`hmac` — no new dependency, `.claude/rules/workflow.md` #2), mirroring
`backend/raad/core/security/password_hashing.py`'s `Pbkdf2PasswordHasher` algorithm/format
choice exactly (PBKDF2-HMAC-SHA256) — this is a separate deployable with no shared code with
the backend (`.claude/rules/architecture.md` #2), so the precedent is followed, not imported.

**Iteration count is lower than the backend's own 260,000** — that figure is tuned for
human-chosen, low-entropy *passwords*, where a slow KDF is the whole point (resisting offline
brute-force of a weak secret). This module's input is always a 32-byte `secrets.token_urlsafe`
value the platform itself mints (high entropy, never human-chosen) — the KDF here exists to
avoid storing the raw credential at rest, not to slow down a guessing attack that both the
random keyspace and this deployable's own auth-code rate limiting (device sessions, `.claude/
rules/jt808.md` #5: unauthenticated devices are rejected and audited) already make impractical.
A lower, still-deliberate iteration count keeps every `0x0102` authentication (a real-time,
high-frequency device-plane operation, unlike an interactive login) cheap enough not to become
its own bottleneck.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode

_ALGORITHM_ID = "pbkdf2_sha256"
_ITERATIONS = 10_000
_SALT_BYTES = 16
_CODE_BYTES = 24  # secrets.token_urlsafe(24) -> a 32-character URL-safe string


def generate_code() -> str:
    """A fresh, cryptographically random auth code (ADR-0025 §3: "the platform mints a
    cryptographically random code on `0x0100` success")."""
    return secrets.token_urlsafe(_CODE_BYTES)


def hash_code(code: str) -> str:
    """Stored format: `pbkdf2_sha256$<iterations>$<salt_b64>$<derived_key_b64>` — mirrors
    `Pbkdf2PasswordHasher.hash`'s identical format, so the iteration count travels with the
    hash and can be raised later without invalidating already-issued codes."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(code, salt, _ITERATIONS)
    return "$".join(
        [
            _ALGORITHM_ID,
            str(_ITERATIONS),
            b64encode(salt).decode("ascii"),
            b64encode(derived).decode("ascii"),
        ]
    )


def verify_code(code: str, hashed_code: str) -> bool:
    try:
        algorithm_id, iterations_str, salt_b64, derived_b64 = hashed_code.split("$")
        if algorithm_id != _ALGORITHM_ID:
            return False
        iterations = int(iterations_str)
        salt = b64decode(salt_b64)
        expected = b64decode(derived_b64)
    except (ValueError, TypeError):
        return False

    actual = _derive(code, salt, iterations)
    return hmac.compare_digest(actual, expected)


def _derive(code: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, iterations)
