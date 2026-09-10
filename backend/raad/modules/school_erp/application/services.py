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

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.school_erp.application.commands import (
    ArchiveFeePlanCommand,
    ArchiveFinancialCategoryCommand,
    CancelStudentInvoiceCommand,
    CreateFeePlanCommand,
    CreateFinancialCategoryCommand,
    GenerateStudentInvoicesCommand,
    IssueStudentInvoiceCommand,
    RecordExpenseCommand,
    RecordIncomeCommand,
    RecordStudentPaymentCommand,
    UpdateFeePlanCommand,
    UpdateFinancialCategoryCommand,
    VoidExpenseCommand,
    VoidIncomeCommand,
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
    IncomeDTO,
    ProfitAndLossDTO,
    StudentInvoiceDTO,
    StudentPaymentDTO,
    VehicleFinanceDTO,
    expense_to_dto,
    fee_plan_to_dto,
    finance_totals_to_dto,
    financial_category_to_dto,
    income_to_dto,
    student_invoice_to_dto,
    student_payment_to_dto,
    vehicle_finance_to_dto,
)
from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
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
    Money,
    OrganizationId,
    RouteId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)

_ZERO = Decimal("0.00")


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
        async with uow:
            totals = await uow.student_invoices.summarise_totals(
                period=BillingPeriod(period) if period else None
            )
            return finance_totals_to_dto(totals)

    async def get_vehicle_financial_overview(
        self, *, period: str | None, uow: SchoolErpUnitOfWork
    ) -> list[VehicleFinanceDTO]:
        """Revenue and cost per bus.

        Two grouped queries, not one per vehicle: invoices grouped by `vehicle_id`, and expenses
        grouped by `vehicle_id` over the same window, joined in memory on a handful of rows.
        """
        async with uow:
            billing_period = BillingPeriod(period) if period else None
            summaries = await uow.student_invoices.summarise_by_vehicle(
                period=billing_period
            )
            start, end = self._period_bounds(billing_period)
            expenses_by_vehicle = await uow.expenses.sum_by_vehicle_between(
                start=start, end=end
            )
            return [
                vehicle_finance_to_dto(
                    summary,
                    # The "Unassigned" summary row (`vehicle_id is None`) carries no attributed
                    # cost by construction: an expense with no `vehicle_id` is organization
                    # overhead, not that pseudo-bus's cost. `or ""` here used to make the two
                    # collapse onto the same key and charge every unattributed expense to it.
                    expense_amount=(
                        expenses_by_vehicle.get(summary.vehicle_id, _ZERO)
                        if summary.vehicle_id
                        else _ZERO
                    ),
                )
                for summary in summaries
            ]

    async def get_profit_and_loss(
        self, *, start: date, end: date, uow: SchoolErpUnitOfWork
    ) -> ProfitAndLossDTO:
        async with uow:
            student_revenue = await uow.student_payments.sum_between(start=start, end=end)
            other_income = await uow.income.sum_between(start=start, end=end)
            total_expenses = await uow.expenses.sum_between(start=start, end=end)
            income_by_category = await uow.income.sum_by_category_between(
                start=start, end=end
            )
            expenses_by_category = await uow.expenses.sum_by_category_between(
                start=start, end=end
            )
            totals = await uow.student_invoices.summarise_totals(period=None)

            total_income = student_revenue + other_income
            return ProfitAndLossDTO(
                start=start,
                end=end,
                student_revenue=f"{student_revenue:.2f}",
                other_income=f"{other_income:.2f}",
                total_income=f"{total_income:.2f}",
                total_expenses=f"{total_expenses:.2f}",
                net_profit=f"{total_income - total_expenses:.2f}",
                income_by_category={k: f"{v:.2f}" for k, v in income_by_category.items()},
                expenses_by_category={
                    k: f"{v:.2f}" for k, v in expenses_by_category.items()
                },
                currency=totals.currency,
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
