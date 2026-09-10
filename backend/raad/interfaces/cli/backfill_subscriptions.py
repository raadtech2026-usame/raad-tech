"""Subscription backfill CLI. Entry point:
`python -m raad.interfaces.cli.backfill_subscriptions --plan-id <ULID> [--apply]`.

**Why this exists.** `open_organization_subscription` failed on every call for the entire life of
the feature (a flush-ordering defect, fixed 2026-09-09), so every organization onboarded before
that fix exists with **no subscription row**. On its own that was invisible, because
`OrganizationAccessPolicy` granted access when no subscription existed. Now that the policy denies
it — the platform owner's rule is that no subscription means no dashboard — those organizations
would be locked out the moment the change deploys. This command is the remediation.

**Why a CLI rather than a migration or a data script.** Period start/end, the first invoice and
the initial status all come from `BillingApplicationService.open_organization_subscription`, which
computes them from the plan's own billing cycle. Hand-written SQL would be a second, drifting
implementation of RAAD's billing calendar — the exact failure mode `BillingProvisioningPort`'s
docstring already warns about — and would skip the domain events and `audit_entries` rows that
make a subscription's origin traceable. Going through the real service means a backfilled
subscription is indistinguishable from one opened through onboarding, because it *is* one.
A migration is doubly wrong: it would bake a specific plan id into the schema history.

**Dry run by default.** Nothing is written without `--apply`. The default output is exactly the
report an operator needs to decide, including the organizations this command deliberately will
*not* touch.

**Idempotent.** `open_organization_subscription` finds an existing non-terminal subscription
before opening a new one, so re-running never creates a duplicate. An organization that already
has one is skipped before the service is even called, so it does not accrue a second invoice.

**No new dependency** — `argparse`/`asyncio` are stdlib, matching `bootstrap_founder`'s shape.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from raad.core.config.settings import get_settings
from raad.core.di.bootstrap import build_container
from raad.core.tenancy.principal import SYSTEM_PRINCIPAL
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.billing.application.commands import (
    OpenOrganizationSubscriptionCommand,
)
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.value_objects import PlanId
from raad.modules.organization.application.ports import OrganizationUnitOfWork

#: Reuses the codebase's existing non-human actor rather than inventing one. The first attempt
#: here used a descriptive `"SYSTEM-BACKFILL-SUBSCRIPTION"` and every write failed on
#: `StringDataRightTruncationError` — `audit_entries.actor_user_id` is `CHAR(26)`, and 28
#: characters do not fit. That is the same `CHAR(26)` trap CLAUDE.md's Permanent Engineering
#: Lessons already records for composite `aggregate_id` values; `SYSTEM_PRINCIPAL` exists
#: precisely so no caller has to rediscover it.
_ACTOR = SYSTEM_PRINCIPAL


@dataclass(frozen=True)
class _Candidate:
    organization_id: str
    name: str
    status: str
    user_count: int

    @property
    def is_orphan(self) -> bool:
        """No user has ever been provisioned, so nobody can log in to it.

        These are the residue of the failed-onboarding retries: the organization committed, the
        admin provisioning then failed, and the old code reported success anyway. Giving one a
        subscription would bill for a tenant that cannot be used, so they are reported for a
        human decision instead — deactivating or deleting them is not this command's call.
        """
        return self.user_count == 0


async def _load_candidates(container) -> tuple[list[_Candidate], set[str]]:
    """Every organization, plus the ids that already hold a subscription."""
    org_uow: OrganizationUnitOfWork = container.resolve(OrganizationUnitOfWork)
    org_uow.scope = TenantRegionScope(organization_ids=None)
    async with org_uow:
        organizations = await org_uow.organizations.list_all()

    billing_uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
    billing_uow.scope = TenantRegionScope(organization_ids=None)
    async with billing_uow:
        subscriptions = await billing_uow.subscriptions.list_all()
    subscribed = {str(s.organization_id) for s in subscriptions}

    from raad.modules.iam.application.ports import IamUnitOfWork

    iam_uow: IamUnitOfWork = container.resolve(IamUnitOfWork)
    iam_uow.scope = TenantRegionScope(organization_ids=None)
    async with iam_uow:
        users = await iam_uow.users.list_all()
    users_per_org: dict[str, int] = {}
    for user in users:
        if user.organization_id:
            key = str(user.organization_id)
            users_per_org[key] = users_per_org.get(key, 0) + 1

    candidates = [
        _Candidate(
            organization_id=str(org.id),
            name=org.name,
            status=org.status.value,
            user_count=users_per_org.get(str(org.id), 0),
        )
        for org in organizations
    ]
    return candidates, subscribed


async def _backfill(plan_id: str, *, apply: bool) -> int:
    settings = get_settings()
    container = build_container(settings)

    candidates, subscribed = await _load_candidates(container)

    already = [c for c in candidates if c.organization_id in subscribed]
    orphans = [
        c for c in candidates if c.organization_id not in subscribed and c.is_orphan
    ]
    targets = [
        c for c in candidates if c.organization_id not in subscribed and not c.is_orphan
    ]

    print(f"Organizations total .......... {len(candidates)}")
    print(f"  already subscribed ......... {len(already)}")
    print(f"  will be backfilled ......... {len(targets)}")
    print(f"  skipped, no user account ... {len(orphans)}")
    print()

    if orphans:
        print("SKIPPED — no user has ever been provisioned, so nobody can log in.")
        print("These are the residue of failed onboarding retries. Review and deactivate or")
        print("delete them yourself; this command will not bill an unusable tenant.")
        for candidate in orphans:
            print(f"  {candidate.organization_id}  {candidate.name}")
        print()

    if not targets:
        print("Nothing to backfill.")
        return 0

    service: BillingApplicationService = container.resolve(BillingApplicationService)
    print(f"{'APPLYING' if apply else 'DRY RUN — no rows written'} (plan {plan_id})")
    failures = 0
    for candidate in targets:
        if not apply:
            print(f"  would subscribe  {candidate.organization_id}  {candidate.name}")
            continue
        try:
            uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
            uow.scope = TenantRegionScope(organization_ids=None)
            invoice = await service.open_organization_subscription(
                OpenOrganizationSubscriptionCommand(
                    organization_id=candidate.organization_id,
                    plan_id=plan_id,
                    actor=_ACTOR,
                ),
                uow=uow,
            )
            print(
                f"  subscribed       {candidate.organization_id}  {candidate.name}  "
                f"invoice {invoice.number} {invoice.amount} {invoice.currency}"
            )
        except Exception as exc:  # noqa: BLE001 - reported per row, never aborts the run
            failures += 1
            print(f"  FAILED           {candidate.organization_id}  {candidate.name}: {exc}")

    if failures:
        print(f"\n{failures} organization(s) failed. Re-run to retry — this is idempotent.")
    return 1 if failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m raad.interfaces.cli.backfill_subscriptions",
        description=(
            "Open a subscription for every organization that has none, through the real "
            "billing application service. Dry run unless --apply is given."
        ),
    )
    parser.add_argument(
        "--plan-id",
        required=True,
        help="ULID of an ACTIVE plan to subscribe the affected organizations to.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without this the command only reports what it would do.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        PlanId(args.plan_id)  # fail on a malformed id before touching the database
    except Exception as exc:  # noqa: BLE001
        print(f"Invalid --plan-id: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_backfill(args.plan_id, apply=args.apply))
    except Exception as exc:  # noqa: BLE001
        print(f"Backfill aborted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
