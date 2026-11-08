"""Concrete cross-module adapters for the two ERP ports introduced by ADR-0040.

Both live in `core/di/` — the composition root — for exactly the reason
`session_cap_adapter.py` does: they reach into another module's **application-layer facade**
without either owning module importing past the other's boundary
(`.claude/rules/backend.md` #3: "cross-context data comes from the owning module's application
service," never a direct cross-module DB read). `tests/architecture/test_module_boundaries.py`
Rule 1 restricts `raad.modules.*` importing another module's `domain`/`infra`; this file imports
neither, and is not itself inside `raad.modules.*`.

  * `TransportOpsStudentContextAdapter` — `school_erp` -> `transport_ops`. Resolves which
    route/vehicle/driver a student is currently assigned to, so a `StudentInvoice` can capture
    it at issue time (ADR-0040 §3).
  * `BillingSubscriptionRevenueAdapter` — `platform_finance` -> `billing`. Reads collected SaaS
    revenue for the platform P&L, so subscription income is never recorded twice.
  * `BillingOnboardingAdapter` — `organization` -> `billing`. Opens an organization's
    subscription during onboarding (ADR-0040 §5).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from raad.core.di.container import Container
from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import Principal
from raad.modules.billing.application.commands import OpenOrganizationSubscriptionCommand
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.value_objects import PlanId, PlanStatus
from raad.modules.organization.application.ports import BillingProvisioningPort
from raad.modules.platform_finance.application.ports import SubscriptionRevenuePort
from raad.modules.school_erp.application.ports import (
    StudentTransportContext,
    StudentTransportContextPort,
)
from raad.modules.transport_ops.application.ports import (
    StudentBillingPort,
    TransportOpsUnitOfWork,
)
from raad.modules.transport_ops.application.services import (
    StudentAssignmentApplicationService,
)

logger = get_logger("raad.erp.adapters")


class TransportOpsStudentContextAdapter(StudentTransportContextPort):
    """Resolves a student's active transport assignment through `transport_ops`' own
    **application service** on a per-call Unit of Work — the same shape
    `PlatformStatsApplicationService` uses, and the only shape `.claude/rules/backend.md` #3
    permits.

    **A miss is not an error.** A student with no active assignment yields an empty context and
    the invoice is issued without transport attribution, which is an ordinary situation (a school
    billing a student before assigning them a bus), not a failure. Likewise a repository that
    raises: the exception is logged and swallowed, because failing to *decorate* an invoice with
    its bus must never fail the invoice itself — the money owed is the same either way.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    async def resolve(self, *, student_id: str) -> StudentTransportContext:
        contexts = await self.resolve_many(student_ids=[student_id])
        return contexts.get(student_id, StudentTransportContext())

    async def resolve_many(
        self, *, student_ids: list[str]
    ) -> dict[str, StudentTransportContext]:
        if not student_ids:
            return {}
        try:
            service: StudentAssignmentApplicationService = self._container.resolve(
                StudentAssignmentApplicationService
            )
            resolved: dict[str, StudentTransportContext] = {}
            for student_id in student_ids:
                # A fresh UoW per student: `get_active_assignment_for_student` opens its own
                # `async with uow:` block, and a UoW cannot be re-entered once exited.
                uow: TransportOpsUnitOfWork = self._container.resolve(TransportOpsUnitOfWork)
                assignment = await service.get_active_assignment_for_student(
                    student_id, uow=uow
                )
                if assignment is None:
                    continue
                resolved[student_id] = StudentTransportContext(
                    route_id=assignment.route_id or None,
                    vehicle_id=assignment.vehicle_id or None,
                    # `StudentAssignment` carries no driver — a driver is assigned to a *trip*,
                    # not to a student. Left `None` rather than resolved from an unrelated
                    # aggregate: an invoice must not claim a driver the assignment never named.
                    driver_id=None,
                )
            return resolved
        except Exception:  # noqa: BLE001 - see class docstring
            logger.exception(
                "Failed to resolve student transport context; issuing invoices without "
                "transport attribution",
                extra={"student_count": len(student_ids)},
            )
            return {}


class BillingSubscriptionRevenueAdapter(SubscriptionRevenuePort):
    """Collected SaaS revenue in a window, read from `billing`'s own invoice repository.

    Reuses the **already-existing** `InvoiceRepository.sum_paid_amount_between` rather than
    adding a query — that method was built for ADR-0020's revenue KPI and answers exactly this
    question. `billing.Money` is float-backed, so the value is converted through `str` into a
    `Decimal` here (never `Decimal(float)`, which would carry the binary expansion straight into
    the platform ledger).
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    async def collected_between(self, *, start: date, end: date) -> Decimal:
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            total = await uow.invoices.sum_paid_amount_between(
                start=datetime.combine(start, time.min),
                end=datetime.combine(end, time.max),
            )
        return Decimal(str(total or 0)).quantize(Decimal("0.01"))

    async def invoiced_between(self, *, start: date, end: date) -> Decimal:
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            total = await uow.invoices.sum_issued_amount_between(
                start=datetime.combine(start, time.min),
                end=datetime.combine(end, time.max),
            )
        return Decimal(str(total or 0)).quantize(Decimal("0.01"))

    async def receivables_asof(self, *, as_of: date) -> Decimal:
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            total = await uow.invoices.sum_outstanding_amount(
                as_of=datetime.combine(as_of, time.max)
            )
        return Decimal(str(total or 0)).quantize(Decimal("0.01"))

    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        # Same datetime bounds as `collected_between`/`invoiced_between`/`receivables_asof`,
        # so the check covers exactly the invoices those three sum.
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            return await uow.invoices.revenue_currencies_between(
                start=datetime.combine(start, time.min),
                end=datetime.combine(end, time.max),
            )


class BillingOnboardingAdapter(BillingProvisioningPort):
    """Opens an Organization's subscription at onboarding time (ADR-0040 §5).

    Delegates straight to `BillingApplicationService.open_organization_subscription`, which
    already finds-or-opens the subscription, computes the period from the plan's own billing
    cycle, and issues the first invoice. **No date arithmetic exists on this side** — a second
    implementation of RAAD's billing calendar is exactly the kind of drift that produces two
    different renewal dates for the same customer.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    async def ensure_plan_is_offerable(self, *, plan_id: str) -> None:
        """Validate the plan before onboarding writes anything — see the port's own docstring.

        Reads through `billing`'s repository rather than its application service only because no
        service method exposes a bare plan lookup; the Unit of Work is `billing`'s own, obtained
        from the composition root, so this remains that module's persistence, not a cross-module
        table read (`.claude/rules/backend.md` #3).
        """
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        async with uow:
            plan = await uow.plans.get(PlanId(plan_id))
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        if plan.status is not PlanStatus.ACTIVE:
            raise DomainError(
                f"Plan {plan.name!r} is not active and cannot be assigned to a new organization."
            )

    async def open_subscription_for_organization(
        self, *, organization_id: str, plan_id: str, actor: Principal
    ) -> None:
        service: BillingApplicationService = self._container.resolve(
            BillingApplicationService
        )
        uow: BillingUnitOfWork = self._container.resolve(BillingUnitOfWork)
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=organization_id, plan_id=plan_id, actor=actor
            ),
            uow=uow,
        )


class TransportOpsStudentBillingAdapter(StudentBillingPort):
    """Sets a student's recurring monthly transportation fee in school_erp (ADR-0048)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def set_student_monthly_fee(
        self,
        *,
        organization_id: str,
        student_id: str,
        monthly_fee: str | float | Decimal,
        currency: str = "USD",
        actor: Principal,
    ) -> None:
        from raad.modules.school_erp.application.commands import SetStudentBillingFeeCommand
        from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
        from raad.modules.school_erp.application.services import ParentFinanceApplicationService

        erp_service: ParentFinanceApplicationService = self._container.resolve(
            ParentFinanceApplicationService
        )
        erp_uow: SchoolErpUnitOfWork = self._container.resolve(SchoolErpUnitOfWork)
        transport_uow: TransportOpsUnitOfWork = self._container.resolve(
            TransportOpsUnitOfWork
        )

        command = SetStudentBillingFeeCommand(
            student_id=student_id,
            monthly_fee=str(monthly_fee),
            currency=currency,
            actor=actor,
        )
        await erp_service.set_student_billing_fee(
            command,
            school_erp_uow=erp_uow,
            transport_ops_uow=transport_uow,
        )

    async def ensure_parent_billing_profile(
        self,
        *,
        organization_id: str,
        parent_id: str,
        currency: str = "USD",
        due_day: int = 10,
        billing_start_period: str | None = None,
        actor: Principal,
    ) -> None:
        from datetime import datetime, timezone
        from raad.modules.school_erp.application.commands import (
            CreateOrUpdateParentBillingProfileCommand,
        )
        from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
        from raad.modules.school_erp.application.services import ParentFinanceApplicationService
        from raad.modules.school_erp.domain.value_objects import ParentId

        erp_service: ParentFinanceApplicationService = self._container.resolve(
            ParentFinanceApplicationService
        )
        erp_uow: SchoolErpUnitOfWork = self._container.resolve(SchoolErpUnitOfWork)
        transport_uow: TransportOpsUnitOfWork = self._container.resolve(
            TransportOpsUnitOfWork
        )

        async with erp_uow:
            existing = await erp_uow.parent_billing_profiles.get_by_parent(
                ParentId(parent_id)
            )
            if existing is not None:
                return

        period = billing_start_period or datetime.now(timezone.utc).strftime("%Y-%m")
        command = CreateOrUpdateParentBillingProfileCommand(
            organization_id=organization_id,
            parent_id=parent_id,
            currency=currency,
            billing_start_period=period,
            due_day=due_day,
            actor=actor,
        )
        await erp_service.create_or_update_billing_profile(
            command,
            school_erp_uow=erp_uow,
            transport_ops_uow=transport_uow,
        )

