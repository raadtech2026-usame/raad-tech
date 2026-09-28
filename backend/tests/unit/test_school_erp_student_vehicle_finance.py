"""ADR-0047 — student-level finance, vehicle income and the per-vehicle report, end to end
through the real application services over in-memory repositories.

The invariants under test, each asserted from more than one direction:

1. **One source per figure, so nothing is counted twice.** Student income is payment
   allocations; daily and other income are `Income` rows by type; expenses are `Expense` rows.
   The organization P&L equals the vehicle rows plus the money that belongs to no bus.
2. **Student and parent views are the same numbers at two grains.** A student's paid amount is
   their own allocations; the family's is the sum of its children's.
3. **Historical vehicle attribution is frozen at invoice generation.** A student who changes bus
   leaves earlier money on the earlier bus.
4. **Cash basis.** A payment counts in the window it was received, not the invoice's month.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.tenancy.principal import SYSTEM_PRINCIPAL, Principal, Role
from raad.modules.school_erp.application.commands import (
    CreateOrUpdateParentBillingProfileCommand,
    SetStudentBillingFeeCommand,
    GenerateParentInvoicesCommand,
    PaymentAllocationRequest,
    RecordExpenseCommand,
    RecordIncomeCommand,
    RecordParentPaymentCommand,
)
from raad.modules.school_erp.application.ports import StudentTransportContext
from raad.modules.school_erp.application.services import (
    ParentFinanceApplicationService,
    SchoolErpApplicationService,
)
from raad.modules.school_erp.domain.entities import (
    BilledChild,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    Money,
    OrganizationId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    StudentPaymentMethod,
)

from test_school_erp_application import (
    FakeSchoolErpUnitOfWork,
    FakeTransportContextPort,
    FixedClock,
    SequentialIdGenerator,
)

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ZT"
PARENT_A = "01J8Z3K9G6X8YV5T4N2R7QPRTA"
PARENT_B = "01J8Z3K9G6X8YV5T4N2R7QPRTB"
PARENT_X = "01J8Z3K9G6X8YV5T4N2R7QPRTX"  # belongs to OTHER_ORG
STUDENT_A1 = "01J8Z3K9G6X8YV5T4N2R7QSTA1"
STUDENT_A2 = "01J8Z3K9G6X8YV5T4N2R7QSTA2"
STUDENT_B1 = "01J8Z3K9G6X8YV5T4N2R7QSTB1"
STUDENT_X1 = "01J8Z3K9G6X8YV5T4N2R7QSTX1"
BUS_1 = "01J8Z3K9G6X8YV5T4N2R7QBS01"
BUS_2 = "01J8Z3K9G6X8YV5T4N2R7QBS02"
SEPTEMBER = (date(2026, 9, 1), date(2026, 9, 30))
OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))


@dataclass
class _Parent:
    id: str
    organization_id: str
    full_name: str
    user_id: str


@dataclass
class _Child:
    student_id: str
    full_name: str
    status: str = "active"
    is_primary: bool = True


@dataclass
class _Student:
    id: str
    full_name: str
    status: str = "active"
    organization_id: str = ORG


@dataclass
class _ParentForStudent:
    parent_id: str
    full_name: str
    is_primary: bool = True


class _ParentService:
    def __init__(self, parents: dict[str, _Parent]) -> None:
        self.parents = parents

    async def get_parent_by_id(self, query, *, uow):
        parent = self.parents.get(query.parent_id)
        if parent is None:
            raise NotFoundError("Parent not found")
        return parent

    async def list_parents_by_ids(self, parent_ids, *, uow):
        return [self.parents[pid] for pid in parent_ids if pid in self.parents]

    async def get_parent_by_user_id(self, user_id, *, uow):
        return next((p for p in self.parents.values() if p.user_id == user_id), None)


class _StudentParentService:
    def __init__(self, children: dict[str, list[_Child]], parents: dict[str, _Parent]) -> None:
        self.children = children
        self.parents = parents

    async def list_students_for_parent(self, query, *, uow):
        return list(self.children.get(query.parent_id, []))

    async def list_parents_for_student(self, query, *, uow):
        return [
            _ParentForStudent(parent_id=pid, full_name=self.parents[pid].full_name)
            for pid, kids in self.children.items()
            if any(kid.student_id == query.student_id for kid in kids)
        ]


class _StudentService:
    def __init__(self, students: dict[str, _Student]) -> None:
        self.students = students

    async def get_student_by_id(self, query, *, uow):
        student = self.students.get(query.student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def list_students_by_ids(self, student_ids, *, uow):
        return [self.students[sid] for sid in student_ids if sid in self.students]


class _TransportUow:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


def _admin(org: str = ORG) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org)


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc))
        self.parents = {
            PARENT_A: _Parent(PARENT_A, ORG, "Ahmed Mohamed", "user-parent-a"),
            PARENT_B: _Parent(PARENT_B, ORG, "Hassan Ali", "user-parent-b"),
            PARENT_X: _Parent(PARENT_X, OTHER_ORG, "Other School Parent", "user-parent-x"),
        }
        self.children = {
            PARENT_A: [_Child(STUDENT_A1, "Mohamed"), _Child(STUDENT_A2, "Aisha")],
            PARENT_B: [_Child(STUDENT_B1, "Yusuf")],
            PARENT_X: [_Child(STUDENT_X1, "Elsewhere")],
        }
        self.students = {
            sid: _Student(sid, name, organization_id=org)
            for sid, name, org in (
                (STUDENT_A1, "Mohamed", ORG),
                (STUDENT_A2, "Aisha", ORG),
                (STUDENT_B1, "Yusuf", ORG),
                (STUDENT_X1, "Elsewhere", OTHER_ORG),
            )
        }
        self.transport = FakeTransportContextPort(
            {
                STUDENT_A1: StudentTransportContext(vehicle_id=BUS_1),
                STUDENT_A2: StudentTransportContext(vehicle_id=BUS_1),
                STUDENT_B1: StudentTransportContext(vehicle_id=BUS_2),
                STUDENT_X1: StudentTransportContext(vehicle_id=BUS_2),
            }
        )
        ids = SequentialIdGenerator()
        self.parent_finance = ParentFinanceApplicationService(
            clock=self.clock,
            id_generator=ids,
            parent_service=_ParentService(self.parents),
            student_parent_service=_StudentParentService(self.children, self.parents),
            transport_context=self.transport,
            student_service=_StudentService(self.students),
        )
        self.school_finance = SchoolErpApplicationService(
            clock=self.clock, id_generator=ids, transport_context=self.transport
        )
        self.uow = FakeSchoolErpUnitOfWork()
        self.tuow = _TransportUow()
        self.actor = _admin()

    async def _price(self, fees: dict[str, str], org: str = ORG) -> None:
        for student_id, fee in fees.items():
            await self.parent_finance.set_student_billing_fee(
                SetStudentBillingFeeCommand(
                    student_id=student_id, monthly_fee=fee, currency="USD", actor=_admin(org)
                ),
                school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )

    async def _bill(
        self, parent_id: str, per_child: str | dict[str, str], period: str = "2026-09", org: str = ORG
    ):
        """Prices each of the family's children (ADR-0048), opens its billing account and runs
        the monthly generation."""
        fees = (
            {child.student_id: per_child for child in self.children[parent_id]}
            if isinstance(per_child, str)
            else per_child
        )
        await self._price(fees, org)
        await self.parent_finance.create_or_update_billing_profile(
            CreateOrUpdateParentBillingProfileCommand(
                organization_id=org, parent_id=parent_id, currency="USD",
                billing_start_period="2026-09", due_day=10, actor=_admin(org),
            ),
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        generated = await self.parent_finance.generate_parent_invoices(
            GenerateParentInvoicesCommand(organization_id=org, period=period, actor=_admin(org)),
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        return next(inv for inv in generated if inv.parent_id == parent_id)

    async def _pay(self, invoice_id: str, amount: str, *, on: date, only: dict[str, str] | None = None):
        return await self.parent_finance.record_parent_payment(
            RecordParentPaymentCommand(
                invoice_id=invoice_id, amount=amount, currency="USD", method="mobile_money",
                received_on=on, reference="EVC-1", notes=None,
                allocations=(
                    tuple(PaymentAllocationRequest(student_id=s, amount=a) for s, a in only.items())
                    if only else None
                ),
                idempotency_key=None, actor=self.actor,
            ),
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )

    async def _income(self, amount: str, *, on: date, income_type: str, vehicle: str | None):
        return await self.school_finance.record_income(
            RecordIncomeCommand(
                organization_id=ORG, category_id=None, amount=amount, currency="USD",
                occurred_on=on, description=f"{income_type} {amount}", reference=None,
                actor=self.actor, income_type=income_type, vehicle_id=vehicle,
            ),
            uow=self.uow,
        )

    async def _expense(self, amount: str, *, on: date, vehicle: str | None):
        return await self.school_finance.record_expense(
            RecordExpenseCommand(
                organization_id=ORG, category_id=None, amount=amount, currency="USD",
                occurred_on=on, description="Fuel", reference=None, vehicle_id=vehicle,
                actor=self.actor,
            ),
            uow=self.uow,
        )

    async def _student(self, student_id: str):
        return await self.parent_finance.get_student_finance(
            student_id, school_erp_uow=self.uow, transport_ops_uow=self.tuow
        )


# ---- Student level ----------------------------------------------------------------------


class StudentFinanceTests(_Base):
    async def test_each_student_has_their_own_charge_payment_and_balance(self) -> None:
        invoice = await self._bill(PARENT_A, "40.00")
        await self._pay(invoice.id, "40.00", on=date(2026, 9, 12), only={STUDENT_A1: "40.00"})

        mohamed = await self._student(STUDENT_A1)
        aisha = await self._student(STUDENT_A2)

        self.assertEqual((mohamed.total_charged, mohamed.total_paid, mohamed.balance_due), ("40.00", "40.00", "0.00"))
        self.assertEqual((aisha.total_charged, aisha.total_paid, aisha.balance_due), ("40.00", "0.00", "40.00"))
        self.assertEqual(len(mohamed.payments), 1)
        self.assertEqual(mohamed.payments[0].method, "mobile_money")
        self.assertEqual(mohamed.payments[0].reference, "EVC-1")
        self.assertEqual(aisha.payments, [])
        self.assertEqual(mohamed.parents[0].full_name, "Ahmed Mohamed")

    async def test_a_consolidated_family_payment_is_traceable_to_each_child(self) -> None:
        invoice = await self._bill(PARENT_A, "40.00")
        payment = await self._pay(invoice.id, "80.00", on=date(2026, 9, 12))

        for student_id in (STUDENT_A1, STUDENT_A2):
            finance = await self._student(student_id)
            self.assertEqual(finance.total_paid, "40.00")
            self.assertEqual(finance.payments[0].payment_id, payment.id)
            self.assertEqual(finance.payments[0].amount, "40.00")
            self.assertEqual(finance.payments[0].payment_total, "80.00")

    async def test_the_family_total_is_exactly_the_sum_of_its_children(self) -> None:
        invoice = await self._bill(PARENT_A, "40.00")
        await self._pay(invoice.id, "50.00", on=date(2026, 9, 12))
        summary = await self.parent_finance.get_parent_financial_summary(
            PARENT_A, school_erp_uow=self.uow, transport_ops_uow=self.tuow
        )
        children = [await self._student(STUDENT_A1), await self._student(STUDENT_A2)]
        self.assertEqual(
            Decimal(summary.total_paid), sum(Decimal(c.total_paid) for c in children)
        )
        self.assertEqual(
            Decimal(summary.outstanding), sum(Decimal(c.balance_due) for c in children)
        )

    async def test_legacy_student_invoices_are_listed_but_never_added_to_the_totals(self) -> None:
        """Their money is already inside the Parent Invoices ADR-0042 copied from them."""
        invoice = await self._bill(PARENT_A, "40.00")
        legacy = StudentInvoice.issue(
            id=StudentInvoiceId("01J8Z3K9G6X8YV5T4N2R7QGC01"),
            organization_id=OrganizationId(ORG), student_id=StudentId(STUDENT_A1),
            fee_plan_id=None, period=BillingPeriod("2026-08"),
            amount=Money(amount=Decimal("35.00"), currency="USD"),
            due_date=date(2026, 8, 30), clock=self.clock,
        )
        self.uow.student_invoices.add(legacy)
        self.uow.student_payments.add(
            StudentPayment.record(
                id=StudentPaymentId("01J8Z3K9G6X8YV5T4N2R7QGC02"),
                organization_id=OrganizationId(ORG), invoice_id=legacy.id,
                student_id=StudentId(STUDENT_A1),
                amount=Money(amount=Decimal("35.00"), currency="USD"),
                method=StudentPaymentMethod.CASH, received_on=date(2026, 8, 20), clock=self.clock,
            )
        )
        finance = await self._student(STUDENT_A1)
        self.assertEqual(finance.total_charged, "40.00")
        self.assertEqual(len(finance.legacy_invoices), 1)
        self.assertEqual(len(finance.legacy_payments), 1)
        self.assertEqual(invoice.amount, "80.00")

    async def test_an_unknown_student_is_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self._student("01J8Z3K9G6X8YV5T4N2R7QNONE")


# ---- Vehicle level and the income model ---------------------------------------------------


class VehicleIncomeTests(_Base):
    async def test_daily_income_must_name_a_bus(self) -> None:
        with self.assertRaises(DomainError):
            await self._income("25.00", on=date(2026, 9, 3), income_type="daily_vehicle", vehicle=None)

    async def test_an_unknown_income_type_is_refused(self) -> None:
        with self.assertRaises(DomainError):
            await self._income("25.00", on=date(2026, 9, 3), income_type="student", vehicle=BUS_1)

    async def test_three_income_sources_stay_separate_per_bus(self) -> None:
        invoice = await self._bill(PARENT_A, "40.00")
        await self._pay(invoice.id, "80.00", on=date(2026, 9, 12))
        await self._income("25.00", on=date(2026, 9, 3), income_type="daily_vehicle", vehicle=BUS_1)
        await self._income("30.00", on=date(2026, 9, 4), income_type="daily_vehicle", vehicle=BUS_1)
        await self._income("100.00", on=date(2026, 9, 5), income_type="other", vehicle=BUS_1)
        await self._expense("45.00", on=date(2026, 9, 6), vehicle=BUS_1)

        rows = {
            r.vehicle_id: r
            for r in await self.school_finance.get_vehicle_financial_overview(
                start=SEPTEMBER[0], end=SEPTEMBER[1], uow=self.uow
            )
        }
        bus = rows[BUS_1]
        self.assertEqual(
            (bus.student_income, bus.daily_income, bus.other_income, bus.total_income),
            ("80.00", "55.00", "100.00", "235.00"),
        )
        self.assertEqual((bus.expense_amount, bus.net_amount), ("45.00", "190.00"))

    async def test_organization_totals_equal_the_bus_rows_plus_unattributed_money(self) -> None:
        """No double counting across the three levels: every unit of money in P&L is either on
        exactly one bus row or belongs to no bus."""
        a = await self._bill(PARENT_A, "40.00")
        b = await self._bill(PARENT_B, "50.00")
        await self._pay(a.id, "80.00", on=date(2026, 9, 12))
        await self._pay(b.id, "20.00", on=date(2026, 9, 13))
        await self._income("25.00", on=date(2026, 9, 3), income_type="daily_vehicle", vehicle=BUS_2)
        await self._income("500.00", on=date(2026, 9, 3), income_type="other", vehicle=None)
        await self._expense("40.00", on=date(2026, 9, 6), vehicle=BUS_1)
        await self._expense("300.00", on=date(2026, 9, 6), vehicle=None)

        pnl = await self.school_finance.get_profit_and_loss(
            start=SEPTEMBER[0], end=SEPTEMBER[1], uow=self.uow
        )
        rows = await self.school_finance.get_vehicle_financial_overview(
            start=SEPTEMBER[0], end=SEPTEMBER[1], uow=self.uow
        )
        self.assertEqual(
            (pnl.student_revenue, pnl.daily_vehicle_income, pnl.other_income, pnl.total_income),
            ("100.00", "25.00", "500.00", "625.00"),
        )
        self.assertEqual((pnl.total_expenses, pnl.net_profit), ("340.00", "285.00"))
        bus_income = sum(Decimal(r.total_income) for r in rows)
        bus_cost = sum(Decimal(r.expense_amount) for r in rows)
        self.assertEqual(bus_income + Decimal("500.00"), Decimal(pnl.total_income))
        self.assertEqual(bus_cost + Decimal("300.00"), Decimal(pnl.total_expenses))

    async def test_a_bus_change_never_moves_historical_money(self) -> None:
        september = await self._bill(PARENT_B, "50.00", period="2026-09")
        await self._pay(september.id, "50.00", on=date(2026, 9, 12))

        self.transport.mapping[STUDENT_B1] = StudentTransportContext(vehicle_id=BUS_1)
        self.clock._now = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)
        october = await self._bill(PARENT_B, "50.00", period="2026-10")
        await self._pay(october.id, "50.00", on=date(2026, 10, 12))

        sept_rows = {
            r.vehicle_id: r
            for r in await self.school_finance.get_vehicle_financial_overview(
                start=SEPTEMBER[0], end=SEPTEMBER[1], uow=self.uow
            )
        }
        oct_rows = {
            r.vehicle_id: r
            for r in await self.school_finance.get_vehicle_financial_overview(
                start=OCTOBER[0], end=OCTOBER[1], uow=self.uow
            )
        }
        self.assertEqual(sept_rows[BUS_2].student_income, "50.00")
        self.assertNotIn(BUS_1, sept_rows)
        self.assertEqual(oct_rows[BUS_1].student_income, "50.00")
        self.assertNotIn(BUS_2, oct_rows)

    async def test_student_income_is_cash_basis_by_receipt_date(self) -> None:
        invoice = await self._bill(PARENT_B, "50.00", period="2026-09")
        await self._pay(invoice.id, "50.00", on=date(2026, 10, 3))

        september = await self.school_finance.get_profit_and_loss(
            start=SEPTEMBER[0], end=SEPTEMBER[1], uow=self.uow
        )
        october = await self.school_finance.get_profit_and_loss(
            start=OCTOBER[0], end=OCTOBER[1], uow=self.uow
        )
        self.assertEqual(september.student_revenue, "0.00")
        self.assertEqual(october.student_revenue, "50.00")

    async def test_the_vehicle_report_breaks_every_figure_down_and_filters_by_date(self) -> None:
        a = await self._bill(PARENT_A, "40.00")
        await self._pay(a.id, "60.00", on=date(2026, 9, 12))
        await self._income("25.00", on=date(2026, 9, 3), income_type="daily_vehicle", vehicle=BUS_1)
        await self._income("15.00", on=date(2026, 10, 3), income_type="daily_vehicle", vehicle=BUS_1)
        await self._income("100.00", on=date(2026, 9, 5), income_type="other", vehicle=BUS_1)
        await self._expense("45.00", on=date(2026, 9, 6), vehicle=BUS_1)
        await self._expense("9.00", on=date(2026, 9, 6), vehicle=BUS_2)

        report = await self.parent_finance.get_vehicle_finance_report(
            BUS_1, start=SEPTEMBER[0], end=SEPTEMBER[1],
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        self.assertEqual(
            (report.student_income, report.daily_income, report.other_income),
            ("60.00", "25.00", "100.00"),
        )
        self.assertEqual((report.total_income, report.total_expenses, report.net_amount), ("185.00", "45.00", "140.00"))
        self.assertEqual({s.full_name: s.amount for s in report.income_by_student}, {"Mohamed": "30.00", "Aisha": "30.00"})
        self.assertEqual([(p.full_name, p.amount) for p in report.income_by_parent], [("Ahmed Mohamed", "60.00")])
        self.assertEqual(len(report.daily_entries), 1)  # the October entry is outside the window
        self.assertEqual(len(report.other_entries), 1)
        self.assertEqual(report.expenses_by_category, {"": "45.00"})
        self.assertEqual((report.billed_amount, report.outstanding_amount), ("80.00", "20.00"))

    async def test_an_inverted_date_range_is_refused(self) -> None:
        with self.assertRaises(DomainError):
            await self.parent_finance.get_vehicle_finance_report(
                BUS_1, start=date(2026, 9, 30), end=date(2026, 9, 1),
                school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )


# ---- Parent self-service and scheduled generation -----------------------------------------


class MyInvoicesTests(_Base):
    async def test_a_parent_sees_only_their_own_family(self) -> None:
        a = await self._bill(PARENT_A, "40.00")
        await self._bill(PARENT_B, "50.00")
        await self._pay(a.id, "30.00", on=date(2026, 9, 12))

        mine = await self.parent_finance.get_my_invoices(
            Principal(user_id="user-parent-a", role=Role.PARENT, org_id=ORG),
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        self.assertEqual(mine.parent_id, PARENT_A)
        self.assertEqual([inv.parent_id for inv in mine.invoices], [PARENT_A])
        self.assertEqual((mine.total_due, mine.total_paid, mine.balance_due), ("80.00", "30.00", "50.00"))
        self.assertEqual(len(mine.payments), 1)

    async def test_a_non_parent_account_gets_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self.parent_finance.get_my_invoices(
                Principal(user_id="user-parent-a", role=Role.ORG_ADMIN, org_id=ORG),
                school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )
        with self.assertRaises(NotFoundError):
            await self.parent_finance.get_my_invoices(
                Principal(user_id="nobody", role=Role.PARENT, org_id=ORG),
                school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )


class ScheduledGenerationTests(_Base):
    async def test_every_organization_is_billed_once_per_period(self) -> None:
        for parent_id, org in ((PARENT_A, ORG), (PARENT_X, OTHER_ORG)):
            await self._price({child.student_id: "30.00" for child in self.children[parent_id]}, org)
            await self.parent_finance.create_or_update_billing_profile(
                CreateOrUpdateParentBillingProfileCommand(
                    organization_id=org, parent_id=parent_id,
                    currency="USD", billing_start_period="2026-09", due_day=10, actor=_admin(org),
                ),
                school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )
        first = await self.parent_finance.generate_parent_invoices_for_all_organizations(
            period="2026-09", actor=SYSTEM_PRINCIPAL, school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        second = await self.parent_finance.generate_parent_invoices_for_all_organizations(
            period="2026-09", actor=SYSTEM_PRINCIPAL, school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        self.assertEqual((first, second), (2, 0))
        organizations = {str(inv.organization_id) for inv in self.uow.parent_invoices.by_id.values()}
        self.assertEqual(organizations, {ORG, OTHER_ORG})

    async def test_the_unattended_run_warns_about_every_child_it_could_not_price(self) -> None:
        """Nobody watches a scheduled run, so an unpriced child must not go unbilled silently.
        The warning names students by id only."""
        await self._price({STUDENT_A1: "25.00"})
        await self.parent_finance.create_or_update_billing_profile(
            CreateOrUpdateParentBillingProfileCommand(
                organization_id=ORG, parent_id=PARENT_A, currency="USD",
                billing_start_period="2026-09", due_day=10, actor=_admin(),
            ),
            school_erp_uow=self.uow, transport_ops_uow=self.tuow,
        )
        with self.assertLogs("raad.modules.school_erp.application.services", "WARNING") as logs:
            issued = await self.parent_finance.generate_parent_invoices_for_all_organizations(
                period="2026-09", actor=SYSTEM_PRINCIPAL, school_erp_uow=self.uow, transport_ops_uow=self.tuow,
            )
        self.assertEqual(issued, 1)
        (record,) = logs.records
        self.assertEqual(record.getMessage(), "parent_invoice_students_not_billed")
        self.assertEqual((record.count, record.student_ids, record.reasons), (1, [STUDENT_A2], ["no_fee"]))
        (invoice,) = self.uow.parent_invoices.by_id.values()
        self.assertEqual(invoice.amount.amount, Decimal("25.00"))


if __name__ == "__main__":
    unittest.main()
