"""PII / sensitive-data redaction (Backend LLD §13.2 — mandatory).

Given minors' data and payment flows, structured log payloads are scrubbed of known-sensitive
fields before emission. This is a generic, key-driven filter — it holds no business logic, only
the redaction policy for logging.
"""

from __future__ import annotations

from typing import Any

_REDACTED = "***REDACTED***"

_SENSITIVE_KEYS = {
    "password",
    "token",
    "jwt",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "payment_secret",
    "authorization",
    "provider_credentials",
}

_MASKED_KEYS = {"msisdn", "phone", "phone_number"}


def mask_msisdn(msisdn: str) -> str:
    """Masks a phone number, keeping only the last 3-4 digits (§13.2)."""
    if not msisdn:
        return msisdn
    visible = msisdn[-4:] if len(msisdn) > 4 else msisdn[-3:]
    return f"{'*' * max(len(msisdn) - len(visible), 0)}{visible}"


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a shallow-redacted copy of a log payload. Full coordinate precision, raw
    msisdn, tokens, payment secrets, and passwords never reach the log sink."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in _SENSITIVE_KEYS:
            redacted[key] = _REDACTED
        elif lowered in _MASKED_KEYS and isinstance(value, str):
            redacted[key] = mask_msisdn(value)
        elif isinstance(value, dict):
            redacted[key] = redact(value)
        else:
            redacted[key] = value
    return redacted
