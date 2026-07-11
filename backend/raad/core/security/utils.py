"""Generic security utilities (Backend LLD §17 `security`) shared across the JWT and
password-hashing services — stdlib-only, no business meaning of their own.
"""

from __future__ import annotations

import hmac
import secrets


def generate_secure_token(num_bytes: int = 32) -> str:
    """URL-safe random token (e.g. for a future password-reset token or session identifier).
    Not used by anything in this phase — provided as a foundation primitive."""
    return secrets.token_urlsafe(num_bytes)


def constant_time_equals(a: str, b: str) -> bool:
    """Timing-safe string comparison — use instead of `==` for any secret comparison
    (tokens, API keys) to avoid leaking length/content via response-time side channels."""
    return hmac.compare_digest(a, b)
