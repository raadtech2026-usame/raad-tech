"""Password strength policy (Backend LLD §17 `security`), configured by
`AuthSettings.password_policy` (`core/config/settings.py`) rather than hardcoded, so it can be
tightened without a code change. Enforcement (calling `validate` from a registration/password-
change use-case) belongs to `modules/iam`, not implemented in this phase.
"""

from __future__ import annotations

from raad.core.config.settings import PasswordPolicySettings
from raad.core.errors.exceptions import ValidationError


class PasswordPolicy:
    def __init__(self, settings: PasswordPolicySettings) -> None:
        self._settings = settings

    def validate(self, password: str) -> None:
        violations: list[str] = []
        settings = self._settings

        if len(password) < settings.min_length:
            violations.append(f"must be at least {settings.min_length} characters long")
        if settings.require_uppercase and not any(c.isupper() for c in password):
            violations.append("must contain an uppercase letter")
        if settings.require_lowercase and not any(c.islower() for c in password):
            violations.append("must contain a lowercase letter")
        if settings.require_digit and not any(c.isdigit() for c in password):
            violations.append("must contain a digit")
        if settings.require_special and all(c.isalnum() for c in password):
            violations.append("must contain a special character")

        if violations:
            raise ValidationError(
                "Password does not meet the required policy.",
                details={"violations": violations},
            )
