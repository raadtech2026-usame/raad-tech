"""Application service for `school_erp` (Backend LLD §4/§6).

Orchestrates use cases: loads aggregates through the Unit of Work, calls domain behaviour, buffers
the resulting events onto the outbox, commits once. Contains no business rules of its own — every
invariant lives on the aggregate (`domain/entities.py`).

**Three things this service owns that the domain deliberately cannot:**

1. **Tenant enforcement on writes** (`_enforce_own_organization`). Any command carrying a
   client-supplied `organization_id` needs it — ADR-0021's repository-layer scope closes reads,
   not writes.
2. **Cross-aggregate coordination.** Recording a payment creates a `StudentPayment` *and*
   advances its `StudentInvoice`. One transaction, one commit, both or neither.
3. **Cross-module resolution.** A student's route/vehicle/driver comes from
   `StudentTransportContextPort`, never from a `transport_ops` table read
   (`.claude/rules/backend.md` #3).

**`Decimal` is constructed here and nowhere earlier.** Commands carry amount *strings*; this is
the boundary where they become exact decimals. A `float` never exists anywhere in this path.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    MAX_PAGE_SIZE,
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.school_erp.application.commands import (
    ArchiveFeePlanCommand,
    ArchiveFinancialCategoryCommand,
    CancelParentInvoiceCommand,
    CancelStudentInvoiceCommand,
    CreateFeePlanCommand,
    CreateFinancialCategoryCommand,
    CreateOrUpdateParentBillingProfileCommand,
    GenerateParentInvoicesCommand,
    GenerateStudentInvoicesCommand,
    IssueStudentInvoiceCommand,
    RecordExpenseCommand,
    RecordIncomeCommand,
    RecordParentPaymentCommand,
    RecordStudentPaymentCommand,
    SetParentBillingProfileStatusCommand,
    SetStudentBillingFeeCommand,
    UpdateFeePlanCommand,
    UpdateFinancialCategoryCommand,
    VoidExpenseCommand,
    VoidIncomeCommand,
    VoidParentPaymentCommand,
    VoidStudentPaymentCommand,
)
from raad.modules.school_erp.application.ports import (
    SchoolErpUnitOfWork,
    StudentTransportContextPort,
)
from raad.modules.school_erp.application.queries import (
    ExpenseDTO,
    FeePlanDTO,
    FinancialCategoryDTO,
    FinanceSummaryDTO,
    GenerationFamilyDTO,
    GenerationLineDTO,
    GenerationSkipDTO,
    IncomeDTO,
    MyInvoicesDTO,
    ParentBillingProfileDTO,
    ParentChildFinancialDTO,
    ParentFinancialSummaryDTO,
    ParentInvoiceDetailDTO,
    ParentInvoiceGenerationPreviewDTO,
    ParentInvoiceSummaryDTO,
    ParentPaymentDTO,
    ParentStudentFeeDTO,
    ParentStudentFeesDTO,
    ProfitAndLossDTO,
    StudentBillingFeeDTO,
    StudentChargeDTO,
    StudentFinanceDTO,
    StudentInvoiceDTO,
    StudentParentDTO,
    StudentPaymentDTO,
    StudentPaymentEntryDTO,
    VehicleFinanceDTO,
    VehicleFinanceReportDTO,
    VehicleParentIncomeDTO,
    VehicleStudentIncomeDTO,
    expense_to_dto,
    fee_plan_to_dto,
    finance_totals_to_dto,
    financial_category_to_dto,
    income_to_dto,
    parent_billing_profile_to_dto,
    parent_invoice_to_detail_dto,
    parent_invoice_to_summary_dto,
    parent_payment_to_dto,
    student_billing_fee_to_dto,
    student_invoice_to_dto,
    student_payment_to_dto,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
)
from raad.modules.transport_ops.application.queries import (
    GetParentByIdQuery,
    GetStudentByIdQuery,
    ListParentsForStudentQuery,
    ListStudentsForParentQuery,
    StudentForParentDTO,
)
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentApplicationService,
    StudentParentApplicationService,
)
from raad.modules.school_erp.domain.entities import (
    BilledChild,
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
    LineAllocation,
    ParentBillingProfile,
    ParentInvoice,
    ParentPayment,
    PaymentAllocationInput,
    StudentBillingProfile,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    CategoryKind,
    DriverId,
    ExpenseId,
    FeePlanId,
    FinancialCategoryId,
    IncomeId,
    IncomeType,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
    ParentPaymentId,
    RouteId,
    StudentBillingProfileId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)

_ZERO = Decimal("0.00")
logger = logging.getLogger(__name__)
#: `_plan_generation` skip reasons an admin must act on; the others are expected outcomes.
_GENERATION_REASONS_NEEDING_ADMIN = frozenset({"no_fee", "currency_mismatch"})


@dataclass(frozen=True)
class _PlannedLine:
    """One child the monthly run will bill, at their own fee (ADR-0048)."""

    student_id: str
    full_name: str
    amount: Decimal
    vehicle_id: str | None
    route_id: str | None


@dataclass(frozen=True)
class _PlannedFamily:
    profile: ParentBillingProfile
    parent_name: str
    lines: list[_PlannedLine]


def _decimal(value: str | None, *, field: str, default: Decimal = _ZERO) -> Decimal:
    """The single place a client-supplied amount becomes a `Decimal`.

    Rejects a non-numeric string with a `DomainError` rather than letting `InvalidOperation`
    escape as a 500 — a malformed amount is the caller's mistake, not the server's.
    """
    if value is None or value == "":
        return default
    try:
        # ROUND_HALF_UP, matching `Money`'s own explicit choice. This runs before `Money` is
        # constructed, so the default (banker's rounding) here would quietly win over it.
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise DomainError(f"{field} must be a decimal amount: {value!r}") from exc


def _enforce_own_organization(*, actor: Principal, organization_id: str) -> None:
    """Mirrors `billing.application.services._enforce_own_organization` exactly.

    Every ERP write command carries a client-supplied `organization_id` with no cross-aggregate
    reference to transitively validate it against, so this is the only thing standing between an
    Org Admin and writing a financial row into another school's ledger. ADR-0021's repository
    scope covers reads; this covers writes.
    """
    if actor.role is not Role.ORG_ADMIN:
        return
    if organization_id != actor.org_id:
        raise AuthorizationError(
            "org_admin may only manage school finance within their own organization."
        )


# ==================================================================================================
# Parent financial summary (2026-09-10 explicit user directive, "Parent & Student Domain
# Restructure + Parent Payments") — helpers shared by `ParentFinanceApplicationService` below.
# ==================================================================================================

#: Falls back to `Money`'s own precedent (`infra/repositories.py`'s `_DEFAULT_CURRENCY`) for the
#: "no rows to derive a currency from" case (a family with zero invoices). Declared separately
#: here — the application layer cannot import `infra` (`.claude/rules/backend.md` #2).
_PARENT_FINANCE_DEFAULT_CURRENCY = "USD"


def _ensure_single_currency(*currency_sets: set[str], figure: str) -> str | None:
    """Refuses to present a total that adds amounts in different currencies.

    Every figure here is a plain `SUM(amount)`, and the old queries labelled that sum with
    `MIN(currency)` — so USD 100 and SOS 50,000 came back as "50100.00 SOS". A wrong number that
    looks right is worse than no number, so this fails loudly instead (finance P0.5). Real
    multi-currency needs a base currency per organization, which is a separate, pending decision.
    """
    currencies = set().union(*currency_sets)
    if len(currencies) > 1:
        raise ConflictError(
            f"{figure} cannot be calculated: the finance records it covers use more than one "
            f"currency ({', '.join(sorted(currencies))}), and amounts in different currencies "
            "cannot be added together. Contact RAAD support to correct the records."
        )
    return next(iter(currencies), None)


def _money(value: Decimal) -> str:
    """See `application/queries.py`'s own `_money` — duplicated here rather than imported
    (a private, single-line helper), matching `_decimal`'s own module-local precedent above."""
    return f"{value:.2f}"


def _payment_method(value: str) -> StudentPaymentMethod:
    try:
        return StudentPaymentMethod(value)
    except ValueError as exc:
        raise DomainError(f"Unknown payment method: {value!r}") from exc


def _income_type(value: str | None) -> IncomeType:
    try:
        return IncomeType(value or IncomeType.OTHER.value)
    except ValueError as exc:
        raise DomainError(f"income_type must be 'daily_vehicle' or 'other': {value!r}") from exc


class SchoolErpApplicationService:
    """ADR-0038/ADR-0040. The Organization -> Student money flow, and only that."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        transport_context: StudentTransportContextPort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        #: Optional so the service is constructible in a test or a CLI without wiring
        #: `transport_ops`. When absent, invoices are issued with no transport context — the
        #: same outcome as a student with no assignment, which is already a supported case.
        self._transport_context = transport_context

    # ==========================================================================================
    # FinancialCategory
    # ==========================================================================================

    async def create_financial_category(
        self, command: CreateFinancialCategoryCommand, *, uow: SchoolErpUnitOfWork
    ) -> FinancialCategoryDTO:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            parent_id: FinancialCategoryId | None = None
            if command.parent_category_id:
                parent = await uow.financial_categories.get(
                    FinancialCategoryId(command.parent_category_id)
                )
                if parent is None:
                    raise NotFoundError("Parent category not found")
                # A category tree that mixes sides of the ledger would let an expense be filed
                # under an income heading — checked here because a domain object cannot see its
                # own siblings.
                if parent.kind.value != command.kind:
                    raise DomainError(
                        "A category's parent must be on the same side of the ledger"
                    )
                parent_id = parent.id

            category = FinancialCategory.create(
                id=FinancialCategoryId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                name=command.name,
                kind=CategoryKind(command.kind),
                parent_category_id=parent_id,
                description=command.description,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.financial_categories.add(category)
            uow.record_events(category.pull_domain_events())
            await uow.commit()
            return financial_category_to_dto(category)

    async def update_financial_category(
        self, command: UpdateFinancialCategoryCommand, *, uow: SchoolErpUnitOfWork
    ) -> FinancialCategoryDTO:
        async with uow:
            category = await self._get_category_or_raise(uow, command.category_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(category.organization_id)
            )
            category.rename(
                name=command.name,
                description=command.description,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(category.pull_domain_events())
            await uow.commit()
            return financial_category_to_dto(category)

    async def archive_financial_category(
        self, command: ArchiveFinancialCategoryCommand, *, uow: SchoolErpUnitOfWork
    ) -> FinancialCategoryDTO:
        async with uow:
            category = await self._get_category_or_raise(uow, command.category_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(category.organization_id)
            )
            category.archive(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(category.pull_domain_events())
            await uow.commit()
            return financial_category_to_dto(category)

    # ==========================================================================================
    # FeePlan
    # ==========================================================================================

    async def create_fee_plan(
        self, command: CreateFeePlanCommand, *, uow: SchoolErpUnitOfWork
    ) -> FeePlanDTO:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            fee_plan = FeePlan.create(
                id=FeePlanId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                name=command.name,
                amount=Money(
                    amount=_decimal(command.amount, field="amount"),
                    currency=command.currency,
                ),
                default_discount_amount=_decimal(
                    command.default_discount_amount, field="default_discount_amount"
                ),
                description=command.description,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.fee_plans.add(fee_plan)
            uow.record_events(fee_plan.pull_domain_events())
            await uow.commit()
            return fee_plan_to_dto(fee_plan)

    async def update_fee_plan(
        self, command: UpdateFeePlanCommand, *, uow: SchoolErpUnitOfWork
    ) -> FeePlanDTO:
        async with uow:
            fee_plan = await self._get_fee_plan_or_raise(uow, command.fee_plan_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(fee_plan.organization_id)
            )
            fee_plan.update_details(
                name=command.name,
                amount=Money(
                    amount=_decimal(command.amount, field="amount"),
                    currency=command.currency,
                ),
                default_discount_amount=_decimal(
                    command.default_discount_amount, field="default_discount_amount"
                ),
                description=command.description,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(fee_plan.pull_domain_events())
            await uow.commit()
            return fee_plan_to_dto(fee_plan)

    async def archive_fee_plan(
        self, command: ArchiveFeePlanCommand, *, uow: SchoolErpUnitOfWork
    ) -> FeePlanDTO:
        async with uow:
            fee_plan = await self._get_fee_plan_or_raise(uow, command.fee_plan_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(fee_plan.organization_id)
            )
            fee_plan.archive(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(fee_plan.pull_domain_events())
            await uow.commit()
            return fee_plan_to_dto(fee_plan)

    # ==========================================================================================
    # StudentInvoice
    # ==========================================================================================

    async def issue_student_invoice(
        self, command: IssueStudentInvoiceCommand, *, uow: SchoolErpUnitOfWork
    ) -> StudentInvoiceDTO:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        period = BillingPeriod(command.period)

        async with uow:
            if await uow.student_invoices.exists_for_student_period(
                student_id=StudentId(command.student_id), period=period
            ):
                raise ConflictError(
                    f"Student {command.student_id} already has an invoice for {period}"
                )

            amount, discount = await self._resolve_invoice_amounts(uow, command)
            context = await self._resolve_transport_context(command.student_id)

            invoice = StudentInvoice.issue(
                id=StudentInvoiceId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                student_id=StudentId(command.student_id),
                fee_plan_id=FeePlanId(command.fee_plan_id) if command.fee_plan_id else None,
                period=period,
                amount=amount,
                due_date=command.due_date,
                discount_amount=discount,
                route_id=RouteId(context.route_id) if context.route_id else None,
                vehicle_id=VehicleId(context.vehicle_id) if context.vehicle_id else None,
                driver_id=DriverId(context.driver_id) if context.driver_id else None,
                notes=command.notes,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.student_invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return student_invoice_to_dto(invoice)

    async def generate_student_invoices(
        self, command: GenerateStudentInvoicesCommand, *, uow: SchoolErpUnitOfWork
    ) -> list[StudentInvoiceDTO]:
        """The monthly billing run.

        **Idempotent**: a student who already has an invoice for the period is skipped rather
        than double-charged, so a partially-failed batch can simply be re-run. That is enforced
        twice — by the existence check here and by `ux_erp_student_invoices__student_period` in
        the database, because a check alone loses a race.

        Transport context is resolved for the whole cohort in **one** port call, not one per
        student — the N+1 this codebase has already had to fix elsewhere.
        """
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        period = BillingPeriod(command.period)

        async with uow:
            fee_plan = await self._get_fee_plan_or_raise(uow, command.fee_plan_id)
            if str(fee_plan.organization_id) != command.organization_id:
                raise DomainError("Fee plan belongs to a different organization")

            contexts = await self._resolve_transport_contexts(command.student_ids)
            issued: list[StudentInvoice] = []

            for student_id in command.student_ids:
                if await uow.student_invoices.exists_for_student_period(
                    student_id=StudentId(student_id), period=period
                ):
                    continue

                context = contexts.get(student_id)
                invoice = StudentInvoice.issue(
                    id=StudentInvoiceId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    student_id=StudentId(student_id),
                    fee_plan_id=fee_plan.id,
                    period=period,
                    amount=fee_plan.amount,
                    due_date=command.due_date,
                    discount_amount=fee_plan.default_discount_amount,
                    route_id=(
                        RouteId(context.route_id) if context and context.route_id else None
                    ),
                    vehicle_id=(
                        VehicleId(context.vehicle_id)
                        if context and context.vehicle_id
                        else None
                    ),
                    driver_id=(
                        DriverId(context.driver_id) if context and context.driver_id else None
                    ),
                    notes=None,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.student_invoices.add(invoice)
                uow.record_events(invoice.pull_domain_events())
                issued.append(invoice)

            await uow.commit()
            return [student_invoice_to_dto(invoice) for invoice in issued]

    async def cancel_student_invoice(
        self, command: CancelStudentInvoiceCommand, *, uow: SchoolErpUnitOfWork
    ) -> StudentInvoiceDTO:
        async with uow:
            invoice = await self._get_invoice_or_raise(uow, command.invoice_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(invoice.organization_id)
            )
            invoice.cancel(
                reason=command.reason,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return student_invoice_to_dto(invoice)

    async def mark_overdue_invoices(self, *, uow: SchoolErpUnitOfWork) -> int:
        """Scheduled sweep: flags issued/partially-paid invoices whose due date has passed.

        Idempotent — `StudentInvoice.mark_overdue` is a no-op on an already-overdue, paid or
        cancelled invoice, so running the job twice in a row changes nothing the second time.
        Returns how many invoices actually transitioned, for the job's own log line.
        """
        async with uow:
            today = self._clock.now().date()
            candidates = await uow.student_invoices.list_overdue_candidates(as_of=today)
            for invoice in candidates:
                invoice.mark_overdue(clock=self._clock, actor_id=None)
                uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return len(candidates)

    # ==========================================================================================
    # StudentPayment
    # ==========================================================================================

    async def record_student_payment(
        self, command: RecordStudentPaymentCommand, *, uow: SchoolErpUnitOfWork
    ) -> StudentPaymentDTO:
        """Creates the payment and advances its invoice in one transaction.

        These are one business fact. Committing the payment without advancing the invoice would
        leave a school looking at an unpaid bill it has already been paid for — which is why both
        aggregates share this Unit of Work rather than each owning their own.
        """
        async with uow:
            invoice = await self._get_invoice_or_raise(uow, command.invoice_id)
            _enforce_own_organization(
                actor=command.actor, organization_id=str(invoice.organization_id)
            )

            amount = Money(
                amount=_decimal(command.amount, field="amount"),
                currency=command.currency,
            )
            payment = StudentPayment.record(
                id=StudentPaymentId(self._id_generator.new_id()),
                organization_id=invoice.organization_id,
                invoice_id=invoice.id,
                student_id=invoice.student_id,
                amount=amount,
                method=StudentPaymentMethod(command.method),
                received_on=command.received_on,
                reference=command.reference,
                notes=command.notes,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            # Raises if the invoice is cancelled or the currency mismatches — before the payment
            # row is ever added, so a rejected payment leaves nothing behind.
            invoice.apply_payment(
                amount=amount, clock=self._clock, actor_id=command.actor.user_id
            )

            uow.student_payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return student_payment_to_dto(payment)

    async def void_student_payment(
        self, command: VoidStudentPaymentCommand, *, uow: SchoolErpUnitOfWork
    ) -> StudentPaymentDTO:
        """Voids a payment and reverses its effect on the invoice, in one transaction.

        Financial rows are never hard-deleted (`.claude/rules/database.md` #5), so the payment
        stays as a voided record and the invoice's `amount_paid` is decremented back.
        """
        async with uow:
            payment = await uow.student_payments.get(
                StudentPaymentId(command.payment_id)
            )
            if payment is None:
                raise NotFoundError("Student payment not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(payment.organization_id)
            )
            if payment.is_voided:
                return student_payment_to_dto(payment)

            invoice = await uow.student_invoices.get(payment.invoice_id)
            if invoice is None:
                raise NotFoundError("Student invoice not found")

            payment.void(
                reason=command.reason, clock=self._clock, actor_id=command.actor.user_id
            )
            invoice.reverse_payment(
                amount=payment.amount, clock=self._clock, actor_id=command.actor.user_id
            )

            uow.record_events(payment.pull_domain_events())
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return student_payment_to_dto(payment)

    # ==========================================================================================
    # Income / Expense
    # ==========================================================================================

    async def record_income(
        self, command: RecordIncomeCommand, *, uow: SchoolErpUnitOfWork
    ) -> IncomeDTO:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            category_id = await self._validate_category(
                uow, command.category_id, expected=CategoryKind.INCOME
            )
            income = Income.record(
                id=IncomeId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                category_id=category_id,
                amount=Money(
                    amount=_decimal(command.amount, field="amount"),
                    currency=command.currency,
                ),
                occurred_on=command.occurred_on,
                description=command.description,
                reference=command.reference,
                income_type=_income_type(command.income_type),
                vehicle_id=VehicleId(command.vehicle_id) if command.vehicle_id else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.income.add(income)
            uow.record_events(income.pull_domain_events())
            await uow.commit()
            return income_to_dto(income)

    async def void_income(
        self, command: VoidIncomeCommand, *, uow: SchoolErpUnitOfWork
    ) -> IncomeDTO:
        async with uow:
            income = await uow.income.get(IncomeId(command.income_id))
            if income is None:
                raise NotFoundError("Income record not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(income.organization_id)
            )
            income.void(
                reason=command.reason, clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(income.pull_domain_events())
            await uow.commit()
            return income_to_dto(income)

    async def record_expense(
        self, command: RecordExpenseCommand, *, uow: SchoolErpUnitOfWork
    ) -> ExpenseDTO:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            category_id = await self._validate_category(
                uow, command.category_id, expected=CategoryKind.EXPENSE
            )
            expense = Expense.record(
                id=ExpenseId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                category_id=category_id,
                amount=Money(
                    amount=_decimal(command.amount, field="amount"),
                    currency=command.currency,
                ),
                occurred_on=command.occurred_on,
                description=command.description,
                reference=command.reference,
                vehicle_id=VehicleId(command.vehicle_id) if command.vehicle_id else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.expenses.add(expense)
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
            return expense_to_dto(expense)

    async def void_expense(
        self, command: VoidExpenseCommand, *, uow: SchoolErpUnitOfWork
    ) -> ExpenseDTO:
        async with uow:
            expense = await uow.expenses.get(ExpenseId(command.expense_id))
            if expense is None:
                raise NotFoundError("Expense record not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(expense.organization_id)
            )
            expense.void(
                reason=command.reason, clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
            return expense_to_dto(expense)

    # ==========================================================================================
    # Read models
    # ==========================================================================================

    async def get_finance_summary(
        self, *, period: str | None, uow: SchoolErpUnitOfWork
    ) -> FinanceSummaryDTO:
        """ADR-0042 decision 5: sourced from `ParentInvoice`, the real Parent-facing billing
        aggregate, not `StudentInvoice` — `billed_amount` is now "Expected Billing",
        `outstanding_amount` is "Receivables" in every consumer's own display labels (the wire
        field names are kept stable; only the frontend's rendered text changed)."""
        async with uow:
            billing_period = BillingPeriod(period) if period else None
            _ensure_single_currency(
                await uow.parent_invoices.currencies_for_period(period=billing_period),
                figure="The finance summary",
            )
            totals = await uow.parent_invoices.summarise_totals(period=billing_period)
            return finance_totals_to_dto(totals)

    async def get_vehicle_financial_overview(
        self,
        *,
        period: str | None = None,
        start: date | None = None,
        end: date | None = None,
        uow: SchoolErpUnitOfWork,
    ) -> list[VehicleFinanceDTO]:
        """Income and cost per bus for a window (ADR-0047 §7): `start`/`end` when given,
        otherwise the calendar month `period`, otherwise all time.

        Five grouped queries, one per source, joined in memory on a handful of rows — never one
        query per vehicle. Student income is keyed by each allocation's frozen vehicle, so a
        student who later changed buses leaves their earlier money on the earlier bus.
        """
        start, end = self._window(period=period, start=start, end=end)
        async with uow:
            currency = await self._window_currency(uow, start=start, end=end, figure="The vehicle financial overview")
            billing = {
                row.vehicle_id: row
                for row in await uow.parent_invoices.summarise_lines_by_vehicle_between(
                    start=start, end=end
                )
            }
            student_income = await uow.parent_payments.student_income_by_vehicle_between(
                start=start, end=end
            )
            manual_income = await uow.income.sum_by_vehicle_and_type_between(
                start=start, end=end
            )
            expenses = await uow.expenses.sum_by_vehicle_between(start=start, end=end)

        vehicle_ids: set[str | None] = set(billing) | set(student_income) | set(expenses)
        vehicle_ids |= {vehicle_id for vehicle_id, _ in manual_income}
        rows: list[VehicleFinanceDTO] = []
        for vehicle_id in vehicle_ids:
            summary = billing.get(vehicle_id)
            students = student_income.get(vehicle_id, _ZERO)
            daily = (
                manual_income.get((vehicle_id, IncomeType.DAILY_VEHICLE.value), _ZERO)
                if vehicle_id
                else _ZERO
            )
            other = (
                manual_income.get((vehicle_id, IncomeType.OTHER.value), _ZERO)
                if vehicle_id
                else _ZERO
            )
            # Organization-wide cost (no `vehicle_id`) is never charged to the Unassigned row.
            cost = expenses.get(vehicle_id, _ZERO) if vehicle_id else _ZERO
            total = students + daily + other
            rows.append(
                VehicleFinanceDTO(
                    vehicle_id=vehicle_id,
                    student_count=summary.student_count if summary else 0,
                    billed_amount=_money(summary.billed_amount if summary else _ZERO),
                    outstanding_amount=_money(summary.outstanding_amount if summary else _ZERO),
                    student_income=_money(students),
                    daily_income=_money(daily),
                    other_income=_money(other),
                    total_income=_money(total),
                    expense_amount=_money(cost),
                    # Cash in minus cost attributed to this bus: an unpaid invoice is not income.
                    net_amount=_money(total - cost),
                    currency=currency,
                )
            )
        rows.sort(key=lambda row: (row.vehicle_id is None, row.vehicle_id or ""))
        return rows

    async def get_profit_and_loss(
        self, *, start: date, end: date, uow: SchoolErpUnitOfWork
    ) -> ProfitAndLossDTO:
        """Three income lines from three disjoint sources (ADR-0047 §6/§7), so nothing can be
        counted twice: student income from payment allocations *received* in the window (cash
        basis — this replaces the old invoice-date approximation), and the two manual `Income`
        types. Every source's currencies are checked first (finance P0.5)."""
        async with uow:
            window_currency = _ensure_single_currency(
                await uow.parent_payments.currencies_between(start=start, end=end),
                await uow.income.currencies_between(start=start, end=end),
                await uow.expenses.currencies_between(start=start, end=end),
                figure="Profit & Loss",
            )
            student_revenue = await uow.parent_payments.sum_student_income_between(
                start=start, end=end
            )
            by_type = await uow.income.sum_by_type_between(start=start, end=end)
            total_expenses = await uow.expenses.sum_between(start=start, end=end)
            income_by_category = await uow.income.sum_by_category_between(
                start=start, end=end
            )
            expenses_by_category = await uow.expenses.sum_by_category_between(
                start=start, end=end
            )
            totals = await uow.parent_invoices.summarise_totals(period=None)

        daily_income = by_type.get(IncomeType.DAILY_VEHICLE.value, _ZERO)
        other_income = by_type.get(IncomeType.OTHER.value, _ZERO)
        total_income = student_revenue + daily_income + other_income
        return ProfitAndLossDTO(
            start=start,
            end=end,
            student_revenue=_money(student_revenue),
            daily_vehicle_income=_money(daily_income),
            other_income=_money(other_income),
            total_income=_money(total_income),
            total_expenses=_money(total_expenses),
            net_profit=_money(total_income - total_expenses),
            income_by_category={k: _money(v) for k, v in income_by_category.items()},
            expenses_by_category={k: _money(v) for k, v in expenses_by_category.items()},
            # The currency the window's rows are actually in; the all-time label only when the
            # window holds no rows at all.
            currency=window_currency or totals.currency,
        )

    async def list_invoices_for_vehicle(
        self, *, vehicle_id: str, period: str | None, uow: SchoolErpUnitOfWork
    ) -> list[StudentInvoiceDTO]:
        """Backs the printable per-bus report."""
        async with uow:
            invoices = await uow.student_invoices.list_for_vehicle_period(
                vehicle_id=VehicleId(vehicle_id),
                period=BillingPeriod(period) if period else None,
            )
            return [student_invoice_to_dto(invoice) for invoice in invoices]

    async def list_invoices_for_student(
        self, *, student_id: str, uow: SchoolErpUnitOfWork
    ) -> list[StudentInvoiceDTO]:
        async with uow:
            invoices = await uow.student_invoices.list_for_student(StudentId(student_id))
            return [student_invoice_to_dto(invoice) for invoice in invoices]

    async def list_payments_for_invoice(
        self, *, invoice_id: str, uow: SchoolErpUnitOfWork
    ) -> list[StudentPaymentDTO]:
        async with uow:
            payments = await uow.student_payments.list_for_invoice(
                StudentInvoiceId(invoice_id)
            )
            return [student_payment_to_dto(payment) for payment in payments]

    # ==========================================================================================
    # Internals
    # ==========================================================================================

    @classmethod
    def _window(
        cls, *, period: str | None, start: date | None, end: date | None
    ) -> tuple[date, date]:
        if start is not None or end is not None:
            window_start = start or date(1970, 1, 1)
            window_end = end or date(9999, 12, 31)
            if window_start > window_end:
                raise DomainError("start must not be after end")
            return window_start, window_end
        return cls._period_bounds(BillingPeriod(period) if period else None)

    @staticmethod
    async def _window_currency(
        uow: SchoolErpUnitOfWork, *, start: date, end: date, figure: str
    ) -> str:
        """Every source a vehicle figure adds up, checked for a single currency (P0.5)."""
        currency = _ensure_single_currency(
            await uow.parent_invoices.currencies_invoiced_between(start=start, end=end),
            await uow.parent_payments.currencies_between(start=start, end=end),
            await uow.income.currencies_between(start=start, end=end),
            await uow.expenses.currencies_between(start=start, end=end),
            figure=figure,
        )
        return currency or _PARENT_FINANCE_DEFAULT_CURRENCY

    @staticmethod
    def _period_bounds(period: BillingPeriod | None) -> tuple[date, date]:
        """Calendar bounds for a `YYYY-MM`, or an all-time window when no period is given.

        The end date is computed as "first of next month minus one day" rather than from a
        hardcoded month-length table, so February and leap years are correct without a special
        case.
        """
        if period is None:
            return date(1970, 1, 1), date(9999, 12, 31)
        year, month = (int(part) for part in str(period).split("-"))
        start = date(year, month, 1)
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        return start, date.fromordinal(next_month.toordinal() - 1)

    async def _resolve_invoice_amounts(
        self, uow: SchoolErpUnitOfWork, command: IssueStudentInvoiceCommand
    ) -> tuple[Money, Decimal]:
        """An explicit amount always wins; a fee plan fills in what was not supplied.

        This is what lets a school bill "the standard fee, but waive 10 for this family" without
        needing a second fee plan, and what makes the ordinary call a two-field one.
        """
        if command.fee_plan_id:
            fee_plan = await self._get_fee_plan_or_raise(uow, command.fee_plan_id)
            amount = Money(
                amount=(
                    _decimal(command.amount, field="amount")
                    if command.amount
                    else fee_plan.amount.amount
                ),
                currency=command.currency or fee_plan.amount.currency,
            )
            discount = (
                _decimal(command.discount_amount, field="discount_amount")
                if command.discount_amount is not None
                else fee_plan.default_discount_amount
            )
            return amount, discount

        if not command.amount or not command.currency:
            raise DomainError(
                "amount and currency are required when no fee_plan_id is supplied"
            )
        return (
            Money(
                amount=_decimal(command.amount, field="amount"),
                currency=command.currency,
            ),
            _decimal(command.discount_amount, field="discount_amount"),
        )

    async def _resolve_transport_context(self, student_id: str):
        from raad.modules.school_erp.application.ports import StudentTransportContext

        if self._transport_context is None:
            return StudentTransportContext()
        return await self._transport_context.resolve(student_id=student_id)

    async def _resolve_transport_contexts(self, student_ids: list[str]) -> dict:
        if self._transport_context is None:
            return {}
        return await self._transport_context.resolve_many(student_ids=student_ids)

    async def _validate_category(
        self,
        uow: SchoolErpUnitOfWork,
        category_id: str | None,
        *,
        expected: CategoryKind,
    ) -> FinancialCategoryId | None:
        """Filing an expense under an income heading (or the reverse) would quietly corrupt every
        Profit & Loss breakdown built on it, so the kind is checked, not assumed."""
        if not category_id:
            return None
        category = await uow.financial_categories.get(FinancialCategoryId(category_id))
        if category is None:
            raise NotFoundError("Financial category not found")
        if category.kind is not expected:
            raise DomainError(
                f"Category {category.name!r} is an {category.kind.value} category, "
                f"not an {expected.value} category"
            )
        return category.id

    async def _get_category_or_raise(
        self, uow: SchoolErpUnitOfWork, category_id: str
    ) -> FinancialCategory:
        category = await uow.financial_categories.get(FinancialCategoryId(category_id))
        if category is None:
            raise NotFoundError("Financial category not found")
        return category

    async def _get_fee_plan_or_raise(
        self, uow: SchoolErpUnitOfWork, fee_plan_id: str
    ) -> FeePlan:
        fee_plan = await uow.fee_plans.get(FeePlanId(fee_plan_id))
        if fee_plan is None:
            raise NotFoundError("Fee plan not found")
        return fee_plan

    async def _get_invoice_or_raise(
        self, uow: SchoolErpUnitOfWork, invoice_id: str
    ) -> StudentInvoice:
        invoice = await uow.student_invoices.get(StudentInvoiceId(invoice_id))
        if invoice is None:
            raise NotFoundError("Student invoice not found")
        return invoice


def _due_date_for(period: BillingPeriod, due_day: int) -> date:
    """The invoice due date for a billing period and a Billing Profile's `due_day` (1-28),
    clamped to the period's own last real day — never overflows past `due_day <= 28` needs to
    clamp, this exists purely as a defensive floor/ceiling since `_MAX_DUE_DAY` already keeps
    `due_day` at or below 28, which every month has."""
    year, month = (int(part) for part in str(period).split("-"))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, last_day))


class ParentFinanceApplicationService:
    """ADR-0042 (2026-09-11, supersedes ADR-0041 §1's `StudentInvoice`-grouping read model).
    Owns the real Parent-facing billing aggregates — `ParentBillingProfile`, `ParentInvoice` —
    composing `transport_ops`'s own application services only for what `school_erp` cannot
    resolve from its own tables: which students are a parent's own active children, their
    current transport assignment, and a parent's/student's display name. Never a cross-module DB
    read (`.claude/rules/backend.md` #3).

    Every method takes **both** Units of Work explicitly, mirroring `iam`'s `/me` routes and this
    class's own pre-ADR-0042 shape — `school_erp_uow` for this module's own aggregates,
    `transport_ops_uow` for the composed reads.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        parent_service: ParentApplicationService,
        student_parent_service: StudentParentApplicationService,
        transport_context: StudentTransportContextPort | None = None,
        student_service: StudentApplicationService | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._parent_service = parent_service
        self._student_parent_service = student_parent_service
        #: Needed only by the student- and vehicle-level reads (ADR-0047), which name students
        #: across families. Unbound in a test that never calls them; those reads fail loudly.
        self._student_service = student_service
        #: Optional for the identical reason `SchoolErpApplicationService`'s own constructor
        #: already documents — constructible in a test without wiring `transport_ops`'s adapter.
        self._transport_context = transport_context

    async def _resolve_children(
        self, parent_id: str, *, transport_ops_uow: TransportOpsUnitOfWork
    ) -> list[StudentForParentDTO]:
        """Every one of this parent's children, any status — the all-time family view
        (`get_parent_financial_summary`) shows a graduated child's history too. `get_parent_by_id`
        alone (discarded here) is what turns an out-of-scope `parent_id` into a `NotFoundError`
        before this method ever reaches `student_parents`."""
        await self._parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=parent_id), uow=transport_ops_uow
        )
        return await self._student_parent_service.list_students_for_parent(
            ListStudentsForParentQuery(parent_id=parent_id), uow=transport_ops_uow
        )

    async def _resolve_active_children(
        self, parent_id: str, *, transport_ops_uow: TransportOpsUnitOfWork
    ) -> list[StudentForParentDTO]:
        """Only *active* children are billed — a graduated/transferred/disabled child is not a
        current transportation beneficiary, the identical reasoning `StudentAssignment`'s own
        active-only CR-1 gate already applies elsewhere in this codebase."""
        children = await self._resolve_children(parent_id, transport_ops_uow=transport_ops_uow)
        return [child for child in children if child.status == "active"]

    async def _resolve_transport_contexts(self, student_ids: list[str]) -> dict:
        from raad.modules.school_erp.application.ports import StudentTransportContext

        if self._transport_context is None or not student_ids:
            return {}
        return await self._transport_context.resolve_many(student_ids=student_ids)

    async def _resolve_parent_names(
        self, parent_ids: list[str], *, transport_ops_uow: TransportOpsUnitOfWork
    ) -> dict[str, str]:
        unique_ids = sorted({pid for pid in parent_ids if pid})
        if not unique_ids:
            return {}
        parents = await self._parent_service.list_parents_by_ids(
            unique_ids, uow=transport_ops_uow
        )
        return {parent.id: parent.full_name for parent in parents}

    # ==========================================================================================
    # ParentBillingProfile
    # ==========================================================================================

    async def create_or_update_billing_profile(
        self,
        command: CreateOrUpdateParentBillingProfileCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentBillingProfileDTO:
        """Creates the family's Billing Profile if none exists yet, otherwise edits the existing
        one in place (`ParentBillingProfile.update_fee`) — never a second row per parent
        (`ux_erp_parent_billing_profiles__org_parent`). Confirms the parent both exists and
        belongs to the caller's own organization before writing anything — the same tenant-scope
        check `_resolve_children` already establishes for every other composed read/write here.
        """
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        parent_dto = await self._parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=command.parent_id), uow=transport_ops_uow
        )
        if parent_dto.organization_id != command.organization_id:
            raise DomainError(
                f"Parent {command.parent_id} does not belong to organization "
                f"{command.organization_id}."
            )

        billing_start = BillingPeriod(command.billing_start_period)

        async with school_erp_uow:
            existing = await school_erp_uow.parent_billing_profiles.get_by_parent(
                ParentId(command.parent_id)
            )
            if existing is None:
                profile = ParentBillingProfile.open(
                    id=ParentBillingProfileId(self._id_generator.new_id()),
                    organization_id=OrganizationId(command.organization_id),
                    parent_id=ParentId(command.parent_id),
                    currency=command.currency,
                    billing_start_period=billing_start,
                    due_day=command.due_day,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                school_erp_uow.parent_billing_profiles.add(profile)
            else:
                profile = existing
                profile.update_terms(
                    currency=command.currency,
                    billing_start_period=billing_start,
                    due_day=command.due_day,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
            school_erp_uow.record_events(profile.pull_domain_events())
            await school_erp_uow.commit()
            return parent_billing_profile_to_dto(profile)

    async def set_billing_profile_status(
        self,
        command: SetParentBillingProfileStatusCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
    ) -> ParentBillingProfileDTO:
        async with school_erp_uow:
            profile = await school_erp_uow.parent_billing_profiles.get(
                ParentBillingProfileId(command.billing_profile_id)
            )
            if profile is None:
                raise NotFoundError("Parent billing profile not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(profile.organization_id)
            )
            if command.is_active:
                profile.activate(clock=self._clock, actor_id=command.actor.user_id)
            else:
                profile.deactivate(clock=self._clock, actor_id=command.actor.user_id)
            school_erp_uow.record_events(profile.pull_domain_events())
            await school_erp_uow.commit()
            return parent_billing_profile_to_dto(profile)

    async def get_billing_profile(
        self,
        parent_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentBillingProfileDTO | None:
        await self._parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=parent_id), uow=transport_ops_uow
        )
        async with school_erp_uow:
            profile = await school_erp_uow.parent_billing_profiles.get_by_parent(
                ParentId(parent_id)
            )
            return parent_billing_profile_to_dto(profile) if profile else None

    # ==========================================================================================
    # ParentInvoice — monthly generation
    # ==========================================================================================

    async def generate_parent_invoices(
        self,
        command: GenerateParentInvoicesCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> list[ParentInvoiceDetailDTO]:
        """The monthly billing run: every `active` `ParentBillingProfile` in this organization
        whose `billing_start_period` has arrived gets one invoice, with one line per active
        child at that child's own fee and a total that is their sum (ADR-0048). Who is billed,
        and at what, is decided by `_plan_generation`, which the preview shares.

        **Idempotent**, backed twice over: a parent already invoiced for the period is skipped
        here *and* by the partial unique index `ux_erp_parent_invoices__org_parent_period`,
        because a check alone loses a race. A cancelled invoice does not count, so a corrected
        bill can be generated after cancelling a wrong one.
        """
        dtos, _skipped = await self._generate_parent_invoices(
            command, school_erp_uow=school_erp_uow, transport_ops_uow=transport_ops_uow
        )
        return dtos

    async def _generate_parent_invoices(
        self,
        command: GenerateParentInvoicesCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> tuple[list[ParentInvoiceDetailDTO], list[GenerationSkipDTO]]:
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        period = BillingPeriod(command.period)

        async with school_erp_uow:
            families, skipped = await self._plan_generation(
                organization_id=command.organization_id,
                period=period,
                school_erp_uow=school_erp_uow,
                transport_ops_uow=transport_ops_uow,
            )
            issued: list[tuple[ParentInvoice, _PlannedFamily]] = []
            for family in families:
                invoice = ParentInvoice.generate(
                    id=ParentInvoiceId(self._id_generator.new_id()),
                    organization_id=family.profile.organization_id,
                    parent_id=family.profile.parent_id,
                    period=period,
                    currency=family.profile.currency,
                    due_date=_due_date_for(period, family.profile.due_day),
                    children=[
                        BilledChild(
                            line_id=self._id_generator.new_id(),
                            student_id=line.student_id,
                            amount=line.amount,
                            vehicle_id=line.vehicle_id,
                            route_id=line.route_id,
                        )
                        for line in family.lines
                    ],
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                school_erp_uow.parent_invoices.add(invoice)
                school_erp_uow.record_events(invoice.pull_domain_events())
                issued.append((invoice, family))

            await school_erp_uow.commit()

        return [
            parent_invoice_to_detail_dto(
                invoice,
                parent_name=family.parent_name,
                student_names={line.student_id: line.full_name for line in family.lines},
            )
            for invoice, family in issued
        ], skipped

    async def preview_parent_invoice_generation(
        self,
        *,
        organization_id: str,
        period: str,
        actor: Principal,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentInvoiceGenerationPreviewDTO:
        """What the monthly run would issue for `period`, and why each family or student it
        leaves out is left out — writes nothing. Built by the same `_plan_generation` the run
        uses, so the preview cannot disagree with the result."""
        _enforce_own_organization(actor=actor, organization_id=organization_id)
        billing_period = BillingPeriod(period)
        async with school_erp_uow:
            families, skipped = await self._plan_generation(
                organization_id=organization_id,
                period=billing_period,
                school_erp_uow=school_erp_uow,
                transport_ops_uow=transport_ops_uow,
            )
        totals: dict[str, Decimal] = {}
        family_dtos: list[GenerationFamilyDTO] = []
        for family in families:
            total = sum((line.amount for line in family.lines), _ZERO)
            currency = family.profile.currency
            totals[currency] = totals.get(currency, _ZERO) + total
            family_dtos.append(
                GenerationFamilyDTO(
                    parent_id=str(family.profile.parent_id),
                    parent_name=family.parent_name,
                    currency=currency,
                    total=_money(total),
                    lines=[
                        GenerationLineDTO(
                            student_id=line.student_id,
                            full_name=line.full_name,
                            amount=_money(line.amount),
                            vehicle_id=line.vehicle_id,
                        )
                        for line in family.lines
                    ],
                )
            )
        return ParentInvoiceGenerationPreviewDTO(
            organization_id=organization_id,
            period=str(billing_period),
            families=family_dtos,
            skipped=skipped,
            totals_by_currency={code: _money(amount) for code, amount in sorted(totals.items())},
        )

    async def _plan_generation(
        self,
        *,
        organization_id: str,
        period: BillingPeriod,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> tuple[list["_PlannedFamily"], list[GenerationSkipDTO]]:
        """Decides, without writing anything, which families are invoiced for `period` and at
        what amount (ADR-0048). The caller has already entered `school_erp_uow`.

        - A family is billed when its Billing Profile is active and has started, and it has no
          live invoice for the period yet (the idempotency rule).
        - Each of its **active** children is billed at the child's own fee. A child with no fee
          set is skipped and reported (`no_fee`), never priced by guessing; a fee of 0.00 is
          skipped silently as `free`; a fee in another currency than the family's account is
          reported (`currency_mismatch`).
        - **A child is billed once per period**, even when two guardians both have a Billing
          Profile: the payer is the guardian whose link is primary, else the lowest parent id,
          and a child already on another family's live invoice for the period is skipped. The
          per-family unique index alone cannot see this, because the two invoices are for
          different parents.

        Every child's fee and transport context is fetched in one batched query each.
        """
        profiles = sorted(
            (
                profile
                for profile in await school_erp_uow.parent_billing_profiles.list_active_for_billing(
                    as_of_period=period
                )
                if str(profile.organization_id) == organization_id
            ),
            key=lambda profile: str(profile.parent_id),
        )
        parent_names = await self._resolve_parent_names(
            [str(profile.parent_id) for profile in profiles], transport_ops_uow=transport_ops_uow
        )
        skipped: list[GenerationSkipDTO] = []
        children_by_parent: dict[str, list[StudentForParentDTO]] = {}
        for profile in profiles:
            parent_id = str(profile.parent_id)
            parent_name = parent_names.get(parent_id, parent_id)
            if await school_erp_uow.parent_invoices.exists_for_parent_period(
                parent_id=profile.parent_id, period=period
            ):
                skipped.append(GenerationSkipDTO(parent_id, parent_name, "already_invoiced"))
                continue
            children = await self._resolve_active_children(
                parent_id, transport_ops_uow=transport_ops_uow
            )
            if not children:
                skipped.append(GenerationSkipDTO(parent_id, parent_name, "no_active_children"))
                continue
            children_by_parent[parent_id] = children

        claims: dict[str, list[tuple[bool, str]]] = {}
        for parent_id, children in children_by_parent.items():
            for child in children:
                claims.setdefault(child.student_id, []).append((child.is_primary, parent_id))
        payer = {
            student_id: sorted(candidates, key=lambda c: (not c[0], c[1]))[0][1]
            for student_id, candidates in claims.items()
        }
        student_ids = sorted(claims)
        already_billed = await school_erp_uow.parent_invoices.billed_student_ids_for_period(
            period=period
        )
        fees = await school_erp_uow.student_billing_profiles.list_by_students(student_ids)
        contexts = await self._resolve_transport_contexts(student_ids)

        families: list[_PlannedFamily] = []
        for profile in profiles:
            parent_id = str(profile.parent_id)
            children = children_by_parent.get(parent_id)
            if children is None:
                continue
            parent_name = parent_names.get(parent_id, parent_id)
            lines: list[_PlannedLine] = []
            for child in children:

                def skip(reason: str) -> None:
                    skipped.append(
                        GenerationSkipDTO(
                            parent_id, parent_name, reason, child.student_id, child.full_name
                        )
                    )

                if child.student_id in already_billed or payer[child.student_id] != parent_id:
                    skip("billed_by_another_parent")
                    continue
                fee = fees.get(child.student_id)
                if fee is None:
                    skip("no_fee")
                    continue
                if not fee.is_billable:
                    skip("free")
                    continue
                if fee.monthly_fee.currency != profile.currency:
                    skip("currency_mismatch")
                    continue
                context = contexts.get(child.student_id)
                lines.append(
                    _PlannedLine(
                        student_id=child.student_id,
                        full_name=child.full_name,
                        amount=fee.monthly_fee.amount,
                        vehicle_id=context.vehicle_id if context else None,
                        route_id=context.route_id if context else None,
                    )
                )
            if lines:
                families.append(
                    _PlannedFamily(profile=profile, parent_name=parent_name, lines=lines)
                )
        return families, skipped

    # ==========================================================================================
    # StudentBillingProfile (ADR-0048) — each student's own monthly fee
    # ==========================================================================================

    async def set_student_billing_fee(
        self,
        command: SetStudentBillingFeeCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> StudentBillingFeeDTO:
        """Sets or changes one student's monthly fee. The student must be in the caller's scope
        (`get_student_by_id` 404s otherwise) and, for an Org Admin, in their own organization;
        the fee row takes the student's organization, never a client-supplied one. Future
        invoices only — every invoice already generated keeps its own frozen line amount."""
        student = await self._require_student_service().get_student_by_id(
            GetStudentByIdQuery(student_id=command.student_id), uow=transport_ops_uow
        )
        _enforce_own_organization(actor=command.actor, organization_id=student.organization_id)
        fee = Money(
            amount=_decimal(command.monthly_fee, field="monthly_fee"),
            currency=command.currency,
        )
        async with school_erp_uow:
            profile = await school_erp_uow.student_billing_profiles.get_by_student(
                StudentId(command.student_id)
            )
            if profile is None:
                profile = StudentBillingProfile.open(
                    id=StudentBillingProfileId(self._id_generator.new_id()),
                    organization_id=OrganizationId(student.organization_id),
                    student_id=StudentId(command.student_id),
                    monthly_fee=fee,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                school_erp_uow.student_billing_profiles.add(profile)
            else:
                profile.change_fee(
                    monthly_fee=fee, clock=self._clock, actor_id=command.actor.user_id
                )
            school_erp_uow.record_events(profile.pull_domain_events())
            await school_erp_uow.commit()
            return student_billing_fee_to_dto(profile)

    async def get_parent_student_fees(
        self,
        parent_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentStudentFeesDTO:
        """Every child of this family with their own fee, and what one month bills the family:
        the sum over its active, priced children. The same arithmetic the monthly run uses."""
        children = await self._resolve_children(parent_id, transport_ops_uow=transport_ops_uow)
        async with school_erp_uow:
            fees = await school_erp_uow.student_billing_profiles.list_by_students(
                [child.student_id for child in children]
            )
        total = _ZERO
        currencies: set[str] = set()
        unpriced = 0
        students: list[ParentStudentFeeDTO] = []
        for child in children:
            fee = fees.get(child.student_id)
            students.append(
                ParentStudentFeeDTO(
                    student_id=child.student_id,
                    full_name=child.full_name,
                    status=child.status,
                    monthly_fee=_money(fee.monthly_fee.amount) if fee else None,
                    currency=fee.monthly_fee.currency if fee else None,
                )
            )
            if child.status != "active":
                continue
            if fee is None:
                unpriced += 1
                continue
            total += fee.monthly_fee.amount
            currencies.add(fee.monthly_fee.currency)
        single = len(currencies) <= 1
        return ParentStudentFeesDTO(
            parent_id=parent_id,
            monthly_total=_money(total) if single else None,
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            unpriced_active_students=unpriced,
            students=students,
        )

    async def cancel_parent_invoice(
        self,
        command: CancelParentInvoiceCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentInvoiceSummaryDTO:
        async with school_erp_uow:
            invoice = await school_erp_uow.parent_invoices.get(
                ParentInvoiceId(command.invoice_id)
            )
            if invoice is None:
                raise NotFoundError(f"Parent invoice {command.invoice_id!r} not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(invoice.organization_id)
            )
            invoice.cancel(
                reason=command.reason, clock=self._clock, actor_id=command.actor.user_id
            )
            school_erp_uow.record_events(invoice.pull_domain_events())
            await school_erp_uow.commit()

        parent_dto = await self._parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=str(invoice.parent_id)), uow=transport_ops_uow
        )
        return parent_invoice_to_summary_dto(invoice, parent_name=parent_dto.full_name)

    async def list_parent_invoices(
        self,
        *,
        page: int,
        page_size: int,
        period: str | None,
        status: str | None,
        parent_id: str | None,
        vehicle_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        organization_id: str | None = None,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> OffsetPage[ParentInvoiceSummaryDTO]:
        """The Finance page's primary listing (ADR-0042) — real `ParentInvoice` rows, never a
        grouped scan over `StudentInvoice`.

        **`vehicle_id` resolves the family's *current* vehicle, not the invoice's own frozen
        one (2026-09-12 fix).** `ParentInvoiceLine.vehicle_id` is captured once, at issue time
        (ADR-0040 §3, "a bill is a historical record") — filtering on it directly matched
        nothing whenever a line predates its family's transportation being assigned (as every
        line in this environment's own data does), and would keep matching a stale vehicle
        forever after a family later changes buses. Filtering is discovery, not accounting: it
        walks Parent -> this invoice's own linked children -> each child's current active
        `StudentAssignment` (via the same `StudentTransportContextPort` invoice generation
        itself uses) -> vehicle, applied in Python over an already-fetched page (still no
        repository-level join, same reason as before) — never mutates `invoice.lines`, which
        stay exactly the frozen historical record ADR-0040 §3 requires. `date_from`/`date_to`
        (ISO `YYYY-MM-DD`, inclusive) filter on `invoice_date` in Python for the unrelated
        reason the repository's own `filterable_fields` has no range operator, only `eq`
        (Finance UI cleanup, 2026-09-12) — this is the Parent Invoices page's own From/To
        filter, deliberately independent of `period` (`YYYY-MM`), which callers may still pass
        on its own. `page_size` above `MAX_PAGE_SIZE` (report builders ask for up to 1000 in one
        call) is paged internally in `MAX_PAGE_SIZE` chunks — `OffsetPageRequest` rejects a
        larger size outright in its own constructor, the same reasoning `core/di/
        report_definitions._collect` documents for the identical constraint.
        """
        filters: list[FilterCondition] = []
        if organization_id:
            # Narrows *within* the caller's resolved scope (ADR-0021 still applies underneath) —
            # how RAAD staff look at one school's invoices.
            filters.append(
                FilterCondition(field="organization_id", op="eq", value=organization_id)
            )
        if period:
            filters.append(FilterCondition(field="period", op="eq", value=period))
        if parent_id:
            filters.append(FilterCondition(field="parent_id", op="eq", value=parent_id))
        if status:
            filters.append(FilterCondition(field="status", op="eq", value=status))
        sort = [SortSpec(field="period", descending=True)]

        async with school_erp_uow:
            if page_size <= MAX_PAGE_SIZE:
                offset_page = await school_erp_uow.parent_invoices.list_page(
                    OffsetPageRequest(page=page, page_size=page_size),
                    filters=filters,
                    sort=sort,
                    search=None,
                )
                rows, total = list(offset_page.data), offset_page.total
            else:
                rows, total = [], 0
                page_number = 1
                while len(rows) < page_size:
                    chunk_size = min(MAX_PAGE_SIZE, page_size - len(rows))
                    chunk = await school_erp_uow.parent_invoices.list_page(
                        OffsetPageRequest(page=page_number, page_size=chunk_size),
                        filters=filters,
                        sort=sort,
                        search=None,
                    )
                    rows.extend(chunk.data)
                    total = chunk.total
                    if len(chunk.data) < chunk_size:
                        break
                    page_number += 1

        if date_from:
            start = date.fromisoformat(date_from)
            rows = [invoice for invoice in rows if invoice.invoice_date >= start]
            total = len(rows)
        if date_to:
            end = date.fromisoformat(date_to)
            rows = [invoice for invoice in rows if invoice.invoice_date <= end]
            total = len(rows)
        if vehicle_id:
            # 2026-09-12 fix: this used to check `line.vehicle_id` — frozen on the invoice at
            # issue time (ADR-0040 §3, "a bill is a historical record"). Every invoice line in
            # this environment's own real data has `vehicle_id=None`, because every invoice here
            # was generated before its family's transportation was assigned; the filter matched
            # nothing, ever, for any vehicle. Even where a line's `vehicle_id` *is* populated,
            # it is only ever the vehicle at issue time — if a family later moves to a different
            # bus (`ParentApplicationService.set_family_transportation`), a stale line would keep
            # the family filed under the old one forever. Vehicle filtering is discovery, not
            # accounting: it must resolve the family's *current* vehicle — Parent -> this
            # invoice's own linked children -> each child's current active `StudentAssignment`
            # -> vehicle (`transport_context`) — never the frozen line. `invoice.lines` is left
            # completely untouched; only the *filter* changes.
            current_vehicle_by_parent: dict[str, str | None] = {}
            matching_rows = []
            for invoice in rows:
                parent_id_str = str(invoice.parent_id)
                if parent_id_str not in current_vehicle_by_parent:
                    children = await self._resolve_active_children(
                        parent_id_str, transport_ops_uow=transport_ops_uow
                    )
                    contexts = await self._resolve_transport_contexts(
                        [child.student_id for child in children]
                    )
                    # Every child of one family shares the same vehicle by construction
                    # (`set_family_transportation`/`register_parent_with_children`) — the first
                    # currently-assigned child's vehicle *is* the family's vehicle.
                    current_vehicle_by_parent[parent_id_str] = next(
                        (
                            context.vehicle_id
                            for context in contexts.values()
                            if context.vehicle_id
                        ),
                        None,
                    )
                if current_vehicle_by_parent[parent_id_str] == vehicle_id:
                    matching_rows.append(invoice)
            rows = matching_rows
            # A Python-side filter narrows what the repository's own `total` already counted —
            # honest only about what this call actually returns, not a claim about how many
            # matching rows exist beyond the page it fetched.
            total = len(rows)

        parent_names = await self._resolve_parent_names(
            [str(invoice.parent_id) for invoice in rows], transport_ops_uow=transport_ops_uow
        )
        summaries = [
            parent_invoice_to_summary_dto(
                invoice,
                parent_name=parent_names.get(str(invoice.parent_id), str(invoice.parent_id)),
            )
            for invoice in rows
        ]
        return OffsetPage(data=summaries, total=total, page=page, page_size=page_size)

    async def get_parent_invoice_detail(
        self,
        invoice_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentInvoiceDetailDTO:
        async with school_erp_uow:
            invoice = await school_erp_uow.parent_invoices.get(ParentInvoiceId(invoice_id))
            if invoice is None:
                raise NotFoundError(f"Parent invoice {invoice_id!r} not found")

        parent_dto = await self._parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=str(invoice.parent_id)), uow=transport_ops_uow
        )
        children = await self._resolve_children(
            str(invoice.parent_id), transport_ops_uow=transport_ops_uow
        )
        student_names = {child.student_id: child.full_name for child in children}
        return parent_invoice_to_detail_dto(
            invoice, parent_name=parent_dto.full_name, student_names=student_names
        )

    # ==========================================================================================
    # ParentPayment — the payment ledger (ADR-0047, amends ADR-0042 §4)
    # ==========================================================================================

    async def record_parent_payment(
        self,
        command: RecordParentPaymentCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentPaymentDTO:
        """Records money received against one Parent Invoice and applies it to the students'
        lines, in one transaction — the payment row and the invoice move together or not at all.

        Guards, in order, before anything is written: a repeated `idempotency_key` returns the
        payment it first recorded (a double-submitted form never pays twice); the invoice must
        exist in the caller's scope and belong to their organization; it must not be cancelled
        (409) or already fully paid (409, the P0.1 duplicate-payment guard); the currency must
        match (400); the allocation must name only students billed on this invoice, each within
        their remaining balance, and sum exactly to the amount (400). Without an allocation the
        amount is split pro-rata to remaining balances (ADR-0047 §3).
        """
        async with school_erp_uow:
            if command.idempotency_key:
                existing = await school_erp_uow.parent_payments.get_by_idempotency_key(
                    command.idempotency_key
                )
                if existing is not None:
                    if str(existing.invoice_id) != command.invoice_id:
                        raise ConflictError(
                            "This idempotency key was already used for a different invoice"
                        )
                    _enforce_own_organization(
                        actor=command.actor, organization_id=str(existing.organization_id)
                    )
                    invoice = await school_erp_uow.parent_invoices.get(existing.invoice_id)
                    payment = existing
                else:
                    payment = None
            else:
                payment = None

            if payment is None:
                invoice = await school_erp_uow.parent_invoices.get(
                    ParentInvoiceId(command.invoice_id)
                )
                if invoice is None:
                    raise NotFoundError(f"Parent invoice {command.invoice_id!r} not found")
                _enforce_own_organization(
                    actor=command.actor, organization_id=str(invoice.organization_id)
                )
                total = _decimal(command.amount, field="amount")
                if total <= _ZERO:
                    raise DomainError("Payment amount must be greater than zero")
                money = Money(amount=total, currency=command.currency)
                invoice.ensure_accepts_payment(money.currency)
                line_allocations = self._resolve_allocations(invoice, command, total)

                payment_id = self._id_generator.new_id()
                invoice.apply_payment(
                    payment_id=payment_id,
                    allocations=line_allocations,
                    currency=money.currency,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                payment = ParentPayment.record(
                    id=ParentPaymentId(payment_id),
                    organization_id=invoice.organization_id,
                    parent_id=invoice.parent_id,
                    invoice_id=invoice.id,
                    amount=money,
                    method=_payment_method(command.method),
                    received_on=command.received_on,
                    reference=command.reference,
                    notes=command.notes,
                    idempotency_key=command.idempotency_key,
                    allocations=[
                        PaymentAllocationInput(
                            allocation_id=self._id_generator.new_id(),
                            line_id=allocation.line_id,
                            student_id=str(invoice.line_for(allocation.line_id).student_id),
                            vehicle_id=(
                                str(invoice.line_for(allocation.line_id).vehicle_id)
                                if invoice.line_for(allocation.line_id).vehicle_id
                                else None
                            ),
                            amount=allocation.amount,
                        )
                        for allocation in line_allocations
                    ],
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                school_erp_uow.parent_payments.add(payment)
                school_erp_uow.record_events(invoice.pull_domain_events())
                school_erp_uow.record_events(payment.pull_domain_events())
                await school_erp_uow.commit()

        names = await self._student_names_for_parent(
            str(payment.parent_id), transport_ops_uow=transport_ops_uow
        )
        return parent_payment_to_dto(
            payment, period=str(invoice.period) if invoice else "", student_names=names
        )

    @staticmethod
    def _resolve_allocations(
        invoice: ParentInvoice, command: RecordParentPaymentCommand, total: Decimal
    ) -> list[LineAllocation]:
        if not command.allocations:
            return invoice.default_allocation(total)
        allocations: list[LineAllocation] = []
        for requested in command.allocations:
            line = next(
                (item for item in invoice.lines if str(item.student_id) == requested.student_id),
                None,
            )
            if line is None:
                raise DomainError(
                    f"Student {requested.student_id!r} is not billed on this invoice"
                )
            allocations.append(
                LineAllocation(
                    line_id=str(line.id),
                    amount=_decimal(requested.amount, field="allocations.amount"),
                )
            )
        allocated = sum((allocation.amount for allocation in allocations), _ZERO)
        if allocated != total:
            raise DomainError(
                f"The allocations add up to {allocated:.2f} but the payment is {total:.2f}"
            )
        return allocations

    async def void_parent_payment(
        self,
        command: VoidParentPaymentCommand,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentPaymentDTO:
        """Voids a payment (a reason is required, P0.4) and reverses exactly its allocations on
        the invoice, in one transaction. Voiding an already-voided payment changes nothing — the
        invoice is never reversed twice."""
        async with school_erp_uow:
            payment = await school_erp_uow.parent_payments.get(
                ParentPaymentId(command.payment_id)
            )
            if payment is None:
                raise NotFoundError("Parent payment not found")
            _enforce_own_organization(
                actor=command.actor, organization_id=str(payment.organization_id)
            )
            invoice = await school_erp_uow.parent_invoices.get(payment.invoice_id)
            if invoice is None:
                raise NotFoundError("Parent invoice not found")
            if payment.void(
                reason=command.reason, clock=self._clock, actor_id=command.actor.user_id
            ):
                invoice.reverse_payment(
                    payment_id=str(payment.id),
                    allocations=payment.as_line_allocations(),
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                school_erp_uow.record_events(payment.pull_domain_events())
                school_erp_uow.record_events(invoice.pull_domain_events())
                await school_erp_uow.commit()

        names = await self._student_names_for_parent(
            str(payment.parent_id), transport_ops_uow=transport_ops_uow
        )
        return parent_payment_to_dto(payment, period=str(invoice.period), student_names=names)

    async def list_invoice_payments(
        self,
        invoice_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> list[ParentPaymentDTO]:
        async with school_erp_uow:
            invoice = await school_erp_uow.parent_invoices.get(ParentInvoiceId(invoice_id))
            if invoice is None:
                raise NotFoundError(f"Parent invoice {invoice_id!r} not found")
            payments = await school_erp_uow.parent_payments.list_for_invoice(invoice.id)
        names = await self._student_names_for_parent(
            str(invoice.parent_id), transport_ops_uow=transport_ops_uow
        )
        return [
            parent_payment_to_dto(payment, period=str(invoice.period), student_names=names)
            for payment in payments
        ]

    async def list_parent_payments(
        self,
        parent_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> list[ParentPaymentDTO]:
        """Every payment this family made, newest first. `_resolve_children` is what 404s an
        out-of-scope `parent_id` before anything is read."""
        children = await self._resolve_children(parent_id, transport_ops_uow=transport_ops_uow)
        names = {child.student_id: child.full_name for child in children}
        async with school_erp_uow:
            payments = await school_erp_uow.parent_payments.list_for_parent(ParentId(parent_id))
            invoices = await school_erp_uow.parent_invoices.list_for_parent(ParentId(parent_id))
        periods = {str(invoice.id): str(invoice.period) for invoice in invoices}
        return [
            parent_payment_to_dto(
                payment, period=periods.get(str(payment.invoice_id), ""), student_names=names
            )
            for payment in payments
        ]

    async def _student_names_for_parent(
        self, parent_id: str, *, transport_ops_uow: TransportOpsUnitOfWork
    ) -> dict[str, str]:
        children = await self._resolve_children(parent_id, transport_ops_uow=transport_ops_uow)
        return {child.student_id: child.full_name for child in children}

    def _require_student_service(self) -> StudentApplicationService:
        if self._student_service is None:
            raise LookupError(
                "ParentFinanceApplicationService was built without a StudentApplicationService"
            )
        return self._student_service

    # ==========================================================================================
    # Student-level finance (ADR-0047 §2)
    # ==========================================================================================

    async def get_student_finance(
        self,
        student_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> StudentFinanceDTO:
        """One student's own financial history: their line on every Parent Invoice, the part of
        each family payment allocated to them, and the resulting balance. Totals exclude
        cancelled invoices and voided payments; both are still listed, marked. Legacy
        `StudentInvoice`/`StudentPayment` rows are listed read-only and never added to the
        totals (their money is already inside the Parent Invoices ADR-0042 copied from them).

        `get_student_by_id` is what 404s a student outside the caller's scope.
        """
        student = await self._require_student_service().get_student_by_id(
            GetStudentByIdQuery(student_id=student_id), uow=transport_ops_uow
        )
        linked_parents = await self._student_parent_service.list_parents_for_student(
            ListParentsForStudentQuery(student_id=student_id), uow=transport_ops_uow
        )

        async with school_erp_uow:
            invoices = await school_erp_uow.parent_invoices.list_for_student(
                StudentId(student_id)
            )
            payments = await school_erp_uow.parent_payments.list_for_student(
                StudentId(student_id)
            )
            legacy_invoices = await school_erp_uow.student_invoices.list_for_student(
                StudentId(student_id)
            )
            fee = await school_erp_uow.student_billing_profiles.get_by_student(
                StudentId(student_id)
            )
            legacy_payments: list[StudentPayment] = []
            for legacy in legacy_invoices:
                legacy_payments.extend(
                    await school_erp_uow.student_payments.list_for_invoice(legacy.id)
                )

        billable = [inv for inv in invoices if inv.status != ParentInvoiceStatus.CANCELLED]
        _ensure_single_currency(
            {inv.amount.currency for inv in billable},
            figure="This student's financial summary",
        )
        currency = billable[0].amount.currency if billable else _PARENT_FINANCE_DEFAULT_CURRENCY

        parent_names = {parent.parent_id: parent.full_name for parent in linked_parents}
        missing = [str(inv.parent_id) for inv in invoices if str(inv.parent_id) not in parent_names]
        parent_names.update(
            await self._resolve_parent_names(missing, transport_ops_uow=transport_ops_uow)
        )

        charges: list[StudentChargeDTO] = []
        total_charged = total_paid = total_balance = _ZERO
        invoices_by_id = {str(inv.id): inv for inv in invoices}
        for invoice in invoices:
            for line in invoice.lines:
                if str(line.student_id) != student_id:
                    continue
                charges.append(
                    StudentChargeDTO(
                        invoice_id=str(invoice.id),
                        invoice_number=parent_invoice_to_summary_dto(
                            invoice, parent_name=""
                        ).invoice_number,
                        line_id=str(line.id),
                        period=str(invoice.period),
                        parent_id=str(invoice.parent_id),
                        parent_name=parent_names.get(
                            str(invoice.parent_id), str(invoice.parent_id)
                        ),
                        amount=_money(line.amount.amount),
                        amount_paid=_money(line.amount_paid),
                        balance_due=_money(line.balance_due),
                        invoice_status=invoice.status.value,
                        due_date=invoice.due_date.isoformat(),
                        vehicle_id=str(line.vehicle_id) if line.vehicle_id else None,
                        currency=invoice.amount.currency,
                    )
                )
                if invoice.status != ParentInvoiceStatus.CANCELLED:
                    total_charged += line.amount.amount
                    total_paid += line.amount_paid
                    total_balance += line.balance_due

        entries: list[StudentPaymentEntryDTO] = []
        for payment in payments:
            share = sum(
                (a.amount.amount for a in payment.allocations if str(a.student_id) == student_id),
                _ZERO,
            )
            invoice = invoices_by_id.get(str(payment.invoice_id))
            period = str(invoice.period) if invoice else ""
            entries.append(
                StudentPaymentEntryDTO(
                    payment_id=str(payment.id),
                    invoice_id=str(payment.invoice_id),
                    invoice_number=parent_payment_to_dto(
                        payment, period=period, student_names={}
                    ).invoice_number,
                    period=period,
                    received_on=payment.received_on,
                    method=payment.method.value,
                    reference=payment.reference,
                    amount=_money(share),
                    payment_total=_money(payment.amount.amount),
                    currency=payment.amount.currency,
                    is_voided=payment.is_voided,
                    voided_reason=payment.voided_reason,
                )
            )

        return StudentFinanceDTO(
            student_id=student.id,
            full_name=student.full_name,
            status=student.status,
            parents=[
                StudentParentDTO(
                    parent_id=parent.parent_id,
                    full_name=parent.full_name,
                    is_primary=parent.is_primary,
                )
                for parent in linked_parents
            ],
            currency=currency,
            total_charged=_money(total_charged),
            total_paid=_money(total_paid),
            balance_due=_money(total_balance),
            charges=charges,
            payments=entries,
            legacy_invoices=[student_invoice_to_dto(inv) for inv in legacy_invoices],
            legacy_payments=[student_payment_to_dto(pay) for pay in legacy_payments],
            monthly_fee=_money(fee.monthly_fee.amount) if fee else None,
            monthly_fee_currency=fee.monthly_fee.currency if fee else None,
        )

    # ==========================================================================================
    # Per-vehicle financial report (ADR-0047 §7)
    # ==========================================================================================

    async def get_vehicle_finance_report(
        self,
        vehicle_id: str,
        *,
        start: date,
        end: date,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> VehicleFinanceReportDTO:
        """Everything one bus earned and cost in a window, with the rows behind each figure.
        Student income uses each allocation's frozen vehicle (ADR-0047 §5): money for a student
        who rode this bus in September stays on this bus after they move in October."""
        if start > end:
            raise DomainError("start must not be after end")
        vehicle = VehicleId(vehicle_id)
        async with school_erp_uow:
            currency = await SchoolErpApplicationService._window_currency(
                school_erp_uow, start=start, end=end, figure="This vehicle's financial report"
            )
            billing = next(
                (
                    row
                    for row in await school_erp_uow.parent_invoices.summarise_lines_by_vehicle_between(
                        start=start, end=end
                    )
                    if row.vehicle_id == vehicle_id
                ),
                None,
            )
            student_rows = await school_erp_uow.parent_payments.student_income_rows_between(
                vehicle_id=vehicle, start=start, end=end
            )
            incomes = await school_erp_uow.income.list_for_vehicle_between(
                vehicle_id=vehicle, start=start, end=end
            )
            expenses = await school_erp_uow.expenses.list_for_vehicle_between(
                vehicle_id=vehicle, start=start, end=end
            )

        student_ids = sorted({row.student_id for row in student_rows})
        students = (
            await self._require_student_service().list_students_by_ids(
                student_ids, uow=transport_ops_uow
            )
            if student_ids
            else []
        )
        student_names = {student.id: student.full_name for student in students}
        parent_names = await self._resolve_parent_names(
            [row.parent_id for row in student_rows], transport_ops_uow=transport_ops_uow
        )

        by_parent: dict[str, Decimal] = {}
        for row in student_rows:
            by_parent[row.parent_id] = by_parent.get(row.parent_id, _ZERO) + row.amount
        daily = [i for i in incomes if i.income_type is IncomeType.DAILY_VEHICLE]
        other = [i for i in incomes if i.income_type is IncomeType.OTHER]
        by_category: dict[str, Decimal] = {}
        for expense in expenses:
            key = str(expense.category_id) if expense.category_id else ""
            by_category[key] = by_category.get(key, _ZERO) + expense.amount.amount

        student_income = sum((row.amount for row in student_rows), _ZERO)
        daily_income = sum((i.amount.amount for i in daily), _ZERO)
        other_income = sum((i.amount.amount for i in other), _ZERO)
        total_income = student_income + daily_income + other_income
        total_expenses = sum((e.amount.amount for e in expenses), _ZERO)
        return VehicleFinanceReportDTO(
            vehicle_id=vehicle_id,
            start=start,
            end=end,
            currency=currency,
            student_income=_money(student_income),
            daily_income=_money(daily_income),
            other_income=_money(other_income),
            total_income=_money(total_income),
            total_expenses=_money(total_expenses),
            net_amount=_money(total_income - total_expenses),
            billed_amount=_money(billing.billed_amount if billing else _ZERO),
            outstanding_amount=_money(billing.outstanding_amount if billing else _ZERO),
            income_by_student=sorted(
                (
                    VehicleStudentIncomeDTO(
                        student_id=row.student_id,
                        full_name=student_names.get(row.student_id, row.student_id),
                        parent_id=row.parent_id,
                        parent_name=parent_names.get(row.parent_id, row.parent_id),
                        amount=_money(row.amount),
                    )
                    for row in student_rows
                ),
                key=lambda item: item.full_name,
            ),
            income_by_parent=sorted(
                (
                    VehicleParentIncomeDTO(
                        parent_id=parent_id,
                        full_name=parent_names.get(parent_id, parent_id),
                        amount=_money(amount),
                    )
                    for parent_id, amount in by_parent.items()
                ),
                key=lambda item: item.full_name,
            ),
            daily_entries=[income_to_dto(i) for i in daily],
            other_entries=[income_to_dto(i) for i in other],
            expenses_by_category={key: _money(value) for key, value in by_category.items()},
            expense_entries=[expense_to_dto(e) for e in expenses],
        )

    # ==========================================================================================
    # Parent self-service (ADR-0047 §9) and scheduled generation
    # ==========================================================================================

    async def get_my_invoices(
        self,
        principal: Principal,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> MyInvoicesDTO:
        """The calling parent's own invoices and non-voided payments. The only identity input
        is `principal.user_id` — there is no `parent_id` a caller could supply, so this cannot
        be pointed at another family (the ADR-0023 construction). 404 when the caller has no
        `Parent` record, including every non-parent role."""
        parent = await self._parent_service.get_parent_by_user_id(
            principal.user_id, uow=transport_ops_uow
        )
        if parent is None or principal.role is not Role.PARENT:
            raise NotFoundError("No parent profile is linked to this account")
        children = await self._resolve_children(parent.id, transport_ops_uow=transport_ops_uow)
        names = {child.student_id: child.full_name for child in children}
        async with school_erp_uow:
            invoices = await school_erp_uow.parent_invoices.list_for_parent(ParentId(parent.id))
            payments = await school_erp_uow.parent_payments.list_for_parent(ParentId(parent.id))
        billable = [inv for inv in invoices if inv.status != ParentInvoiceStatus.CANCELLED]
        _ensure_single_currency(
            {inv.amount.currency for inv in billable}, figure="Your invoice summary"
        )
        periods = {str(inv.id): str(inv.period) for inv in invoices}
        return MyInvoicesDTO(
            parent_id=parent.id,
            currency=(
                billable[0].amount.currency if billable else _PARENT_FINANCE_DEFAULT_CURRENCY
            ),
            total_due=_money(sum((inv.amount.amount for inv in billable), _ZERO)),
            total_paid=_money(sum((inv.amount_paid for inv in billable), _ZERO)),
            balance_due=_money(sum((inv.balance_due for inv in billable), _ZERO)),
            invoices=[
                parent_invoice_to_detail_dto(
                    invoice, parent_name=parent.full_name, student_names=names
                )
                for invoice in invoices
            ],
            payments=[
                parent_payment_to_dto(
                    payment,
                    period=periods.get(str(payment.invoice_id), ""),
                    student_names=names,
                )
                for payment in payments
                if not payment.is_voided
            ],
        )

    async def generate_parent_invoices_for_all_organizations(
        self,
        *,
        period: str,
        actor: Principal,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> int:
        """The scheduled monthly run (ADR-0047 §9): `generate_parent_invoices` once per
        organization that has an active Billing Profile due for `period`. Idempotent through the
        same unique index the manual button relies on, so a second tick in the same month issues
        nothing. One organization failing is logged by the caller and does not stop the rest —
        each organization commits on its own."""
        async with school_erp_uow:
            profiles = await school_erp_uow.parent_billing_profiles.list_active_for_billing(
                as_of_period=BillingPeriod(period)
            )
        organization_ids = sorted({str(profile.organization_id) for profile in profiles})
        issued = 0
        for organization_id in organization_ids:
            results, skipped = await self._generate_parent_invoices(
                GenerateParentInvoicesCommand(
                    organization_id=organization_id, period=period, actor=actor
                ),
                school_erp_uow=school_erp_uow,
                transport_ops_uow=transport_ops_uow,
            )
            issued += len(results)
            # Nobody is watching an unattended run: a child it could not price would otherwise
            # go unbilled in silence. Named by id only — no student name reaches the logs.
            needs_attention = [
                item for item in skipped if item.reason in _GENERATION_REASONS_NEEDING_ADMIN
            ]
            if needs_attention:
                logger.warning(
                    "parent_invoice_students_not_billed",
                    extra={
                        "organization_id": organization_id,
                        "period": period,
                        "count": len(needs_attention),
                        "student_ids": [item.student_id for item in needs_attention],
                        "reasons": sorted({item.reason for item in needs_attention}),
                    },
                )
        return issued

    # ==========================================================================================
    # Family-level all-time summary (2026-09-10 explicit user directive, rewritten for ADR-0042)
    # ==========================================================================================

    async def get_parent_financial_summary(
        self,
        parent_id: str,
        *,
        school_erp_uow: SchoolErpUnitOfWork,
        transport_ops_uow: TransportOpsUnitOfWork,
    ) -> ParentFinancialSummaryDTO:
        """The Parent detail page's "Financial Summary" — this parent's own `ParentInvoice`
        rows (ADR-0042). Per-child figures are each child's own lines: what they were charged and
        what payments were actually allocated to them (ADR-0047 §2) — exact, not a pro-rata
        estimate. The family total is the sum of the same lines, so nothing is counted twice.
        """
        children = await self._resolve_children(parent_id, transport_ops_uow=transport_ops_uow)

        async with school_erp_uow:
            invoices = await school_erp_uow.parent_invoices.list_for_parent(ParentId(parent_id))
        billable = [inv for inv in invoices if inv.status != ParentInvoiceStatus.CANCELLED]
        _ensure_single_currency(
            {inv.amount.currency for inv in billable},
            figure="This family's financial summary",
        )

        currency = billable[0].amount.currency if billable else _PARENT_FINANCE_DEFAULT_CURRENCY

        per_child_due: dict[str, Decimal] = {child.student_id: _ZERO for child in children}
        per_child_paid: dict[str, Decimal] = {child.student_id: _ZERO for child in children}
        per_child_count: dict[str, int] = {child.student_id: 0 for child in children}
        total_due = _ZERO
        total_paid = _ZERO
        total_outstanding = _ZERO
        for invoice in billable:
            total_due += invoice.amount.amount
            total_paid += invoice.amount_paid
            total_outstanding += invoice.balance_due
            for line in invoice.lines:
                sid = str(line.student_id)
                if sid not in per_child_due:
                    continue
                per_child_due[sid] += line.amount.amount
                per_child_paid[sid] += line.amount_paid
                per_child_count[sid] += 1

        child_dtos = [
            ParentChildFinancialDTO(
                student_id=child.student_id,
                full_name=child.full_name,
                status=child.status,
                total_due=_money(per_child_due[child.student_id]),
                total_paid=_money(per_child_paid[child.student_id]),
                outstanding=_money(
                    max(per_child_due[child.student_id] - per_child_paid[child.student_id], _ZERO)
                ),
                invoice_count=per_child_count[child.student_id],
            )
            for child in children
        ]

        if total_due <= _ZERO:
            summary_status = "no_invoices"
        elif total_paid <= _ZERO:
            summary_status = "unpaid"
        elif total_paid >= total_due:
            summary_status = "paid"
        else:
            summary_status = "partially_paid"

        return ParentFinancialSummaryDTO(
            parent_id=parent_id,
            currency=currency,
            total_due=_money(total_due),
            total_paid=_money(total_paid),
            outstanding=_money(total_outstanding),
            status=summary_status,
            children=child_dtos,
        )


