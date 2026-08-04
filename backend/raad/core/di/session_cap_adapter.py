"""`SystemSettingSessionCapAdapter` — the concrete `iam.application.ports.SessionCapPort`
(ADR-0019). Lives in `core/di/`, not inside `modules/iam/`, precisely so it can reach across
into `platform_audit`'s **application-layer facade**
(`PlatformAuditApplicationService.get_system_setting`) without `iam` itself importing past
another module's boundary — `core/` is the composition root and already does this for every
module (`.claude/rules/backend.md` #3: "cross-context data comes from the owning module's
application service," never a direct cross-module DB read). `tests/architecture/
test_module_boundaries.py`'s Rule 1 only restricts `raad.modules.*` importing another module's
`domain`/`infra` — this file imports neither, and isn't itself inside `raad.modules.*` at all.
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import Role
from raad.modules.iam.application.ports import SessionCapPort
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.queries import GetSystemSettingQuery
from raad.modules.platform_audit.application.services import (
    PlatformAuditApplicationService,
)

logger = get_logger("raad.iam.session_cap")

SESSION_CAP_SETTING_KEY = "session_cap"

#: Mirrors `LockoutSettings`' own "hardcoded, documented default" posture — used only if the
#: `system_settings` row is missing, malformed, or lacks this specific role's key (an admin
#: could delete/edit it into an invalid shape via `PATCH /admin/settings`). Values match the
#: seed migration's own starting defaults: tighter for parent/driver (the literal
#: one-account-shared-with-many-parents scenario ADR-0019 names), looser for RAAD-staff/
#: org_admin roles that legitimately use multiple devices.
_DEFAULT_MAX_SESSIONS: dict[str, int] = {
    "parent": 3,
    "driver": 3,
    "org_admin": 10,
    "founder": 20,
    "regional_manager": 20,
    "support_staff": 20,
    "finance_staff": 20,
}


class SystemSettingSessionCapAdapter(SessionCapPort):
    """Fails **toward availability, not toward blocking login** — an optional-in-principle
    hardening control (like `RateLimitMiddleware`'s Redis-unreachable fail-open path) must never
    take `/auth/login`/`/auth/refresh` down because its own configuration is temporarily
    missing/malformed. Resolves a fresh `PlatformAuditUnitOfWork` per call (mirrors `iam.api.
    deps.get_iam_uow`'s identical "resolve without entering, let the service's own `async with
    uow:` own the transaction" pattern) — this port has no long-lived state of its own beyond
    the `Container` reference.
    """

    def __init__(self, container: Container) -> None:
        self._container = container
        self._warned_missing = False

    async def get_max_sessions(self, *, role: Role) -> int:
        service = self._container.resolve(PlatformAuditApplicationService)
        uow = self._container.resolve(PlatformAuditUnitOfWork)
        role_key = role.value.lower()
        default = _DEFAULT_MAX_SESSIONS.get(role_key, _DEFAULT_MAX_SESSIONS["org_admin"])

        setting = await service.get_system_setting(
            GetSystemSettingQuery(key=SESSION_CAP_SETTING_KEY), uow=uow
        )
        if setting is None or not isinstance(setting.value, dict):
            self._warn_once(f"missing or malformed system_settings row: {setting!r}")
            return default

        value = setting.value.get(role_key)
        if not isinstance(value, int) or value <= 0:
            self._warn_once(f"role {role_key!r} missing/invalid in session_cap setting")
            return default
        return value

    def _warn_once(self, detail: str) -> None:
        if not self._warned_missing:
            logger.warning("session_cap_setting_unreadable", extra={"detail": detail})
            self._warned_missing = True


__all__ = ["SESSION_CAP_SETTING_KEY", "SystemSettingSessionCapAdapter"]
