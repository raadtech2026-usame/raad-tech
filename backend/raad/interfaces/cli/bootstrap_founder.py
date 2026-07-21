"""Founder bootstrap CLI (Backend LLD §9.2's composition-root pattern, applied a third time).
Entry point: `python -m raad.interfaces.cli.bootstrap_founder`.

**The gap this closes.** Every documented way to create a `User` (`POST /users`, API Contracts
§4.1) requires an already-authenticated in-scope admin caller — confirmed by reading that route's
own `require_permission(Permission("iam.users.create"))` guard. With a brand-new, empty `users`
table, no such caller can ever exist, and no migration/script in this repository seeds one (the
`role_permissions` seed migration seeds permission *grants* for the `founder` role, never an
actual account). This is a genuine, previously-undocumented deployment gap, not a design this
file is overriding.

**Why a CLI, not a migration or an HTTP endpoint.** A migration-seeded account would be a fixed,
version-controlled identity — exactly the hardcoded-credential/permanent-backdoor shape this
command is required *not* to be. An HTTP "create the first user" endpoint would need to be
reachable without authentication, i.e. a new, network-facing, unauthenticated attack surface with
no equivalent anywhere else in this API. A one-time operator/CI-invoked CLI stays behind the
deployment's own trust boundary (whoever already controls the running environment), adds zero new
HTTP surface, and — like `interfaces/workers/bootstrap.py` before it — is a second, independent
entry point sharing the *same* composition root (`core.di.bootstrap.build_container`) as the HTTP
app. No new business logic exists here: this module only orchestrates three already-existing,
already-tested `UserApplicationService` methods in sequence.

**What this does, exactly:**
1. Refuses to run if `users` has *any* row at all (not just Founders) — the literal, enforced
   "brand-new deployment only" guarantee, checked via the same `UserRepository.list_all()` the
   `GET /users` read path already uses.
2. `UserApplicationService.invite_user(...)` — creates the `User` (`status=INVITED`, no password).
3. `UserApplicationService.change_password(...)` — validates the operator-supplied password against
   the real `PasswordPolicy` and hashes it via the real `PasswordHasher`, the same ports every
   other password-setting path in this codebase uses.
4. `UserApplicationService.activate_user(...)` — `status=ACTIVE`, immediately able to log in.

**Credential handling.** Email and password are read *only* from `--email`/`--password` CLI flags
or the `RAAD_BOOTSTRAP_FOUNDER_EMAIL`/`RAAD_BOOTSTRAP_FOUNDER_PASSWORD` environment variables —
never hardcoded, never auto-generated. The password is never printed, logged, or included in any
error message this module raises itself (`BootstrapError`'s own messages below only ever
interpolate `email`/`full_name`/counts, checked line by line). Prefer the environment-variable
form over `--password` in a real shell — a CLI argument is visible to other processes on the same
host via `ps`/`/proc`; an environment variable set via a secrets manager or a CI job's own
"masked variable" mechanism is not.

**Partial-failure note, flagged rather than silently engineered around.** Steps 2-4 above are
three separate `UnitOfWork` transactions (each of `invite_user`/`change_password`/`activate_user`
opens and commits its own, matching every other call site of these methods in this codebase — this
command does not alter that shape). If the process is interrupted between steps, the created
`User` row means a re-run's own "refuse if any user exists" guard (requirement, not a design
choice made here) will then also refuse to finish it. This is an accepted, documented trade-off,
not a hidden one — see `docs/runbooks/founder-bootstrap.md` for the manual recovery note.

**No new dependency.** `argparse`/`getpass`/`os`/`asyncio` are all stdlib, consistent with this
codebase's existing stdlib-first tooling discipline (no pytest, no Click/Typer, hand-rolled JWT).
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
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    InviteUserCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService

logger = get_logger("raad.cli.bootstrap_founder")

# Attributed as the actor on the three domain events this command causes (`UserInvited`/
# `UserPasswordChanged`/`UserActivated`) — a synthetic, non-persisted Principal used only for
# that attribution, the same "a null/system actor_id means system action" convention
# `core.db.mixins.AuditActorMixin`'s own docstring already establishes ("created_by/updated_by
# ... nullable — null means system"); this one is simply nameable in the audit trail rather than
# left null, so `GET /admin/audit` shows *something* more specific than "system" for the one
# action this command ever takes.
_SYSTEM_ACTOR = Principal(user_id="system-bootstrap", role=Role.FOUNDER, org_id=None)


class BootstrapError(Exception):
    """Any bootstrap precondition failure — caught at the CLI boundary (`main`) and reported as
    a clean one-line message and a non-zero exit code, never a raw traceback (this is an
    operator-facing tool, not an HTTP handler with a global exception mapper to lean on)."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bootstrap-founder",
        description=(
            "Creates the first Founder account in a brand-new deployment (an empty `users` "
            "table). Refuses to run if any user already exists. See "
            "docs/runbooks/founder-bootstrap.md for the full operator guide."
        ),
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Founder's login email. Falls back to RAAD_BOOTSTRAP_FOUNDER_EMAIL if omitted. "
            "Required (from one of the two sources)."
        ),
    )
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Founder's initial password. Falls back to RAAD_BOOTSTRAP_FOUNDER_PASSWORD if "
            "omitted. Required (from one of the two sources). Prefer the environment variable "
            "over this flag - a CLI argument is visible to other processes on the same host "
            "(ps/procfs); an environment variable set via a secrets manager or masked CI "
            "variable is not."
        ),
    )
    parser.add_argument(
        "--full-name",
        default="Founder",
        help="Display name stored on the account (default: 'Founder').",
    )
    return parser.parse_args(argv)


def _resolve_credentials(
    args: argparse.Namespace,
) -> tuple[str, str, str]:
    """CLI flag takes precedence over the environment variable when both are given - the
    reverse would silently ignore a flag the operator just typed."""
    email = args.email or os.environ.get("RAAD_BOOTSTRAP_FOUNDER_EMAIL")
    password = args.password or os.environ.get("RAAD_BOOTSTRAP_FOUNDER_PASSWORD")
    if not email:
        raise BootstrapError(
            "No Founder email provided - pass --email or set "
            "RAAD_BOOTSTRAP_FOUNDER_EMAIL."
        )
    if not password:
        raise BootstrapError(
            "No Founder password provided - pass --password or set "
            "RAAD_BOOTSTRAP_FOUNDER_PASSWORD. A password is never auto-generated."
        )
    return email, password, args.full_name


async def _bootstrap(email: str, password: str, full_name: str) -> str:
    """Returns the newly-created Founder's user_id on success. Raises `BootstrapError` if any
    user already exists; propagates any `AppError` subclass (invalid email shape, password-
    policy violation, etc.) from the reused application-service calls unchanged - none of
    those exception paths ever interpolate the password (confirmed against
    `core.security.password_policy.PasswordPolicy.validate`, `core.security.password_hashing.
    Pbkdf2PasswordHasher.hash`, and `iam.domain.value_objects.Email`/`PhoneNumber` before
    relying on that here)."""
    settings = get_settings()
    settings.validate_on_startup()
    configure_logging(settings.observability)
    container = build_container(settings)

    user_service = container.resolve(UserApplicationService)

    precheck_uow = container.resolve(IamUnitOfWork)
    async with precheck_uow:
        existing_users = await precheck_uow.users.list_all()
    if existing_users:
        raise BootstrapError(
            f"Refusing to bootstrap: {len(existing_users)} user(s) already exist. "
            "This command only runs against a brand-new, empty `users` table - see "
            "docs/runbooks/founder-bootstrap.md if a prior bootstrap attempt was interrupted."
        )

    invited = await user_service.invite_user(
        InviteUserCommand(
            organization_id=None,
            role=Role.FOUNDER,
            email=email,
            phone=None,
            full_name=full_name,
            actor=_SYSTEM_ACTOR,
        ),
        uow=container.resolve(IamUnitOfWork),
    )
    await user_service.change_password(
        ChangePasswordCommand(
            user_id=invited.id,
            new_plain_password=password,
            actor=_SYSTEM_ACTOR,
        ),
        uow=container.resolve(IamUnitOfWork),
    )
    await user_service.activate_user(
        ActivateUserCommand(user_id=invited.id, actor=_SYSTEM_ACTOR),
        uow=container.resolve(IamUnitOfWork),
    )
    return invited.id


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        email, password, full_name = _resolve_credentials(args)
        user_id = asyncio.run(_bootstrap(email, password, full_name))
    except (BootstrapError, AppError) as exc:
        # `str(exc)` is safe to print for every exception type reachable here - checked at each
        # reused call site above; never the password.
        print(f"Founder bootstrap failed: {exc}", file=sys.stderr)
        return 1

    logger.info("founder_bootstrapped", extra={"user_id": user_id, "email": email})
    print(f"Founder account created and activated (user_id={user_id}, email={email}).")
    print("It can now log in via POST /auth/login with the password you supplied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
