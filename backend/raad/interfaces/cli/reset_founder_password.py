"""Founder password recovery CLI (ADR-0017 Amendment, 2026-07-29). Entry point:
`python -m raad.interfaces.cli.reset_founder_password`.

**The gap this closes.** `POST /auth/change-password` is self-service-only
(`user_id=principal.user_id`, hardcoded — `iam/api/routers.py`) — there is no way for anyone,
including another Founder, to reset a Founder's password over HTTP if that Founder is locked
out, and `bootstrap_founder.py` (this package's sibling) refuses to run once *any* user exists,
so it cannot be re-run to "recreate" a Founder either. Without this command, a locked-out
Founder account has no recovery path at all.

**Why a CLI, not a new HTTP endpoint or a reuse of the admin reset-password route.** Exactly
`bootstrap_founder.py`'s own reasoning, restated for the opposite precondition: this command
stays behind the deployment's own trust boundary (whoever can already reach a shell/exec into
the running environment) rather than becoming new, network-facing, unauthenticated attack
surface. It is deliberately **not** the same code path as `POST /users/{id}/reset-password`
(`UserApplicationService.reset_password_to_temporary`) — that route requires an authenticated
caller who already holds `iam.users.reset_password`, which by definition does not exist when
the *only* Founder is the one who's locked out. This command instead reuses the plain,
already-existing `UserApplicationService.change_password` (the same method `POST
/auth/change-password` itself calls) directly via the shared composition root.

**What this does, exactly:**
1. Looks up the target by email. Refuses (clean error, nothing touched) if no such user exists,
   or if the user that does exist is not `role=founder` — this command recovers a Founder
   account specifically, not a general "reset anyone's password" bypass. (An admin resetting a
   *non*-Founder user's password already has `POST /users/{id}/reset-password` for that, which
   correctly requires an authenticated, permissioned caller instead of shell access.)
2. `UserApplicationService.change_password(...)` — validates the operator-supplied password
   against the real `PasswordPolicy`, hashes it via the real `PasswordHasher`, and stores it.
   This clears `is_password_change_required` (it already does for any `change_password_hash`
   call) and does **not** revoke existing sessions — unlike the admin-reset route, an operator
   recovering their own account is not resetting someone *else's* credential out from under
   them.

**Credential handling.** Identical convention to `bootstrap_founder.py`: email and password are
read only from `--email`/`--password` or `RAAD_RESET_FOUNDER_EMAIL`/
`RAAD_RESET_FOUNDER_PASSWORD`, never hardcoded or auto-generated. The password is never
printed, logged, or included in any error message this module raises itself. Prefer the
environment-variable form in a real shell — a CLI argument is visible to other processes on the
same host via `ps`/`/proc`.

**No new dependency.** `argparse`/`asyncio`/`os`/`sys` are stdlib, matching this codebase's
existing CLI tooling discipline (`bootstrap_founder.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from raad.core.config.settings import get_settings
from raad.core.di.bootstrap import build_container
from raad.core.errors.exceptions import AppError
from raad.core.logging.setup import configure_logging, get_logger
from raad.core.tenancy.principal import Principal, Role
from raad.modules.iam.application.commands import ChangePasswordCommand
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.iam.domain.value_objects import Email

logger = get_logger("raad.cli.reset_founder_password")

# Attributed as the actor on the `UserPasswordChanged` domain event this command causes — a
# synthetic, non-persisted Principal used only for audit attribution, the identical convention
# `bootstrap_founder.py`'s own `_SYSTEM_ACTOR` already establishes.
_SYSTEM_ACTOR = Principal(user_id="system-password-recovery", role=Role.FOUNDER, org_id=None)


class RecoveryError(Exception):
    """Any recovery precondition failure — caught at the CLI boundary (`main`) and reported as
    a clean one-line message and a non-zero exit code, never a raw traceback."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reset-founder-password",
        description=(
            "Resets an existing Founder account's password. Refuses to run against any account "
            "that is not an active Founder. See docs/runbooks/founder-password-recovery.md for "
            "the full operator guide."
        ),
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "The Founder account's login email. Falls back to RAAD_RESET_FOUNDER_EMAIL if "
            "omitted. Required (from one of the two sources)."
        ),
    )
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "The new password. Falls back to RAAD_RESET_FOUNDER_PASSWORD if omitted. Required "
            "(from one of the two sources). Prefer the environment variable over this flag - a "
            "CLI argument is visible to other processes on the same host (ps/procfs)."
        ),
    )
    return parser.parse_args(argv)


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """CLI flag takes precedence over the environment variable when both are given - the
    reverse would silently ignore a flag the operator just typed."""
    email = args.email or os.environ.get("RAAD_RESET_FOUNDER_EMAIL")
    password = args.password or os.environ.get("RAAD_RESET_FOUNDER_PASSWORD")
    if not email:
        raise RecoveryError(
            "No Founder email provided - pass --email or set RAAD_RESET_FOUNDER_EMAIL."
        )
    if not password:
        raise RecoveryError(
            "No new password provided - pass --password or set "
            "RAAD_RESET_FOUNDER_PASSWORD. A password is never auto-generated."
        )
    return email, password


async def _reset(email: str, password: str) -> str:
    """Returns the Founder's user_id on success. Raises `RecoveryError` if no matching, active
    Founder account exists; propagates any `AppError` subclass (password-policy violation,
    etc.) unchanged - none of those exception paths ever interpolate the password."""
    settings = get_settings()
    settings.validate_on_startup()
    configure_logging(settings.observability)
    container = build_container(settings)

    user_service = container.resolve(UserApplicationService)

    lookup_uow = container.resolve(IamUnitOfWork)
    async with lookup_uow:
        user = await lookup_uow.users.get_by_email(Email(email))
    if user is None:
        raise RecoveryError(
            f"No account found for {email!r}. This command only resets an existing Founder "
            "account - see docs/runbooks/founder-password-recovery.md."
        )
    if user.role is not Role.FOUNDER:
        raise RecoveryError(
            f"{email!r} is not a Founder account (role={user.role.value}). This command "
            "recovers Founder accounts only - an admin with iam.users.reset_password can reset "
            "any other role via POST /users/{id}/reset-password instead."
        )

    await user_service.change_password(
        ChangePasswordCommand(
            user_id=str(user.id),
            new_plain_password=password,
            actor=_SYSTEM_ACTOR,
        ),
        uow=container.resolve(IamUnitOfWork),
    )
    return str(user.id)


def main(argv: list[str] | None = None) -> int:
    try:
        email, password = _resolve_credentials(_parse_args(argv))
        user_id = asyncio.run(_reset(email, password))
    except (RecoveryError, AppError) as exc:
        # `str(exc)` is safe to print for every exception type reachable here - checked at each
        # reused call site above; never the password.
        print(f"Founder password reset failed: {exc}", file=sys.stderr)
        return 1

    logger.info("founder_password_reset", extra={"user_id": user_id, "email": email})
    print(f"Password reset for Founder account (user_id={user_id}, email={email}).")
    print("It can now log in via POST /auth/login with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
