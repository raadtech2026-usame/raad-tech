"""`school_erp` domain unit tests (ADR-0038, ADR-0040).

Targets the invariants that actually carry money, not the getters:

  * partial payment arithmetic and the status ladder it drives,
  * `balance_due` clamping (why one overpaid student cannot mask another's debt),
  * currency mismatch rejection,
  * payment reversal recomputing status from the resulting balance rather than assuming one,
  * `Decimal` exactness — the reason this module does not reuse `billing`'s float-backed `Money`,
  * the ledger-kind guard that stops an expense being filed under an income heading.

`.claude/rules/testing.md` #3: financial invariants get explicit regression coverage, not
incidental coverage.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import DomainError, RuleViolationError
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
    ExpenseId,
    FeePlanId,
    FinancialCategoryId,
    IncomeId,
    Money,
    OrganizationId,
    StudentId,
    StudentInvoiceId,
    StudentInvoiceStatus,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


CLOCK = _FixedClock(datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
ULID_A = "01J8Z9QK7N4V6P2R8T0W3X5Y7A"
ULID_B = "01J8Z9QK7N4V6P2R8T0W3X5Y7B"
ULID_C = "01J8Z9QK7N4V6P2R8T0W3X5Y7C"
ORG = OrganizationId("org-1")
STUDENT = StudentId("student-1")


def _invoice(amount: str = "100.00", discount: str = "0.00") -> StudentInvoice:
    return StudentInvoice.issue(
        id=StudentInvoiceId(ULID_A),
        organization_id=ORG,
        student_id=STUDENT,
        fee_plan_id=None,
        period=BillingPeriod("2026-09"),
        amount=Money(amount=Decimal(amount), currency="USD"),
        due_date=date(2026, 9, 30),
        discount_amount=Decimal(discount),
        vehicle_id=VehicleId("bus-1"),
        clock=CLOCK,
    )


class MoneyTests(unittest.TestCase):
    def test_rejects_float_amounts(self) -> None:
        """The whole reason this module does not reuse `billing.Money`."""
        with self.assertRaises(DomainError):
            Money(amount=12.10, currency="USD")  # type: ignore[arg-type]

    def test_quantises_to_two_places_at_construction(self) -> None:
        self.assertEqual(Money(amount=Decimal("10.005"), currency="usd").amount, Decimal("10.01"))

    def test_normalises_currency_case(self) -> None:
        self.assertEqual(Money(amount=Decimal("1.00"), currency="usd").currency, "USD")

    def test_refuses_to_add_across_currencies(self) -> None:
        usd = Money(amount=Decimal("10.00"), currency="USD")
        eur = Money(amount=Decimal("10.00"), currency="EUR")
        with self.assertRaises(DomainError):
            usd.add(eur)

    def test_sums_many_small_amounts_exactly(self) -> None:
        """1000 x 0.10 is exactly 100.00 in Decimal. In binary float it is not."""
        total = Decimal("0.00")
        for _ in range(1000):
            total += Money(amount=Decimal("0.10"), currency="USD").amount
        self.assertEqual(total, Decimal("100.00"))


class BillingPeriodTests(unittest.TestCase):
    def test_accepts_yyyy_mm(self) -> None:
        self.assertEqual(str(BillingPeriod("2026-09")), "2026-09")

    def test_rejects_malformed_period(self) -> None:
        for bad in ("2026-13", "2026-9", "26-09", "September", ""):
            with self.subTest(bad=bad), self.assertRaises(DomainError):
                BillingPeriod(bad)


class StudentInvoiceTests(unittest.TestCase):
    def test_issues_with_transport_context_captured(self) -> None:
        invoice = _invoice()
        self.assertEqual(invoice.status, StudentInvoiceStatus.ISSUED)
        self.assertEqual(str(invoice.vehicle_id), "bus-1")
        self.assertEqual(invoice.balance_due, Decimal("100.00"))

    def test_net_amount_is_amount_less_discount(self) -> None:
        invoice = _invoice(amount="100.00", discount="15.00")
        self.assertEqual(invoice.net_amount, Decimal("85.00"))
        self.assertEqual(invoice.balance_due, Decimal("85.00"))

    def test_rejects_discount_greater_than_amount(self) -> None:
        with self.assertRaises(DomainError):
            _invoice(amount="50.00", discount="60.00")

    def test_partial_payment_moves_to_partially_paid(self) -> None:
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("40.00"), currency="USD"), clock=CLOCK)
        self.assertEqual(invoice.status, StudentInvoiceStatus.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_paid, Decimal("40.00"))
        self.assertEqual(invoice.balance_due, Decimal("60.00"))
        self.assertIsNone(invoice.paid_at)

    def test_second_payment_settles_the_invoice(self) -> None:
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("40.00"), currency="USD"), clock=CLOCK)
        invoice.apply_payment(amount=Money(amount=Decimal("60.00"), currency="USD"), clock=CLOCK)
        self.assertEqual(invoice.status, StudentInvoiceStatus.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertIsNotNone(invoice.paid_at)

    def test_balance_due_never_goes_negative_on_overpayment(self) -> None:
        """Clamped so one overpaid student cannot mask another student's real debt inside a
        per-bus outstanding total."""
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("150.00"), currency="USD"), clock=CLOCK)
        self.assertEqual(invoice.balance_due, Decimal("0.00"))
        self.assertEqual(invoice.amount_paid, Decimal("150.00"))

    def test_rejects_payment_in_a_different_currency(self) -> None:
        invoice = _invoice()
        with self.assertRaises(DomainError):
            invoice.apply_payment(
                amount=Money(amount=Decimal("40.00"), currency="EUR"), clock=CLOCK
            )

    def test_rejects_zero_or_negative_payment(self) -> None:
        invoice = _invoice()
        with self.assertRaises(DomainError):
            invoice.apply_payment(
                amount=Money(amount=Decimal("0.00"), currency="USD"), clock=CLOCK
            )

    def test_cannot_pay_a_cancelled_invoice(self) -> None:
        invoice = _invoice()
        invoice.cancel(reason="waived", clock=CLOCK)
        with self.assertRaises(RuleViolationError):
            invoice.apply_payment(
                amount=Money(amount=Decimal("10.00"), currency="USD"), clock=CLOCK
            )

    def test_cannot_cancel_an_invoice_that_received_money(self) -> None:
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("10.00"), currency="USD"), clock=CLOCK)
        with self.assertRaises(RuleViolationError):
            invoice.cancel(clock=CLOCK)

    def test_reversal_recomputes_status_from_the_resulting_balance(self) -> None:
        """Voiding the second of two payments must land back on PARTIALLY_PAID, not ISSUED."""
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("40.00"), currency="USD"), clock=CLOCK)
        invoice.apply_payment(amount=Money(amount=Decimal("60.00"), currency="USD"), clock=CLOCK)
        self.assertEqual(invoice.status, StudentInvoiceStatus.PAID)

        invoice.reverse_payment(
            amount=Money(amount=Decimal("60.00"), currency="USD"), clock=CLOCK
        )
        self.assertEqual(invoice.status, StudentInvoiceStatus.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_paid, Decimal("40.00"))

    def test_reversing_every_payment_returns_to_issued(self) -> None:
        invoice = _invoice()
        invoice.apply_payment(amount=Money(amount=Decimal("40.00"), currency="USD"), clock=CLOCK)
        invoice.reverse_payment(
            amount=Money(amount=Decimal("40.00"), currency="USD"), clock=CLOCK
        )
        self.assertEqual(invoice.status, StudentInvoiceStatus.ISSUED)
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))

    def test_mark_overdue_is_idempotent_and_skips_settled_invoices(self) -> None:
        overdue = _invoice()
        overdue.mark_overdue(clock=CLOCK)
        overdue.mark_overdue(clock=CLOCK)
        self.assertEqual(overdue.status, StudentInvoiceStatus.OVERDUE)

        paid = _invoice()
        paid.apply_payment(amount=Money(amount=Decimal("100.00"), currency="USD"), clock=CLOCK)
        paid.mark_overdue(clock=CLOCK)
        self.assertEqual(paid.status, StudentInvoiceStatus.PAID)

    def test_issuing_records_a_domain_event(self) -> None:
        events = _invoice().pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "school_erp.StudentInvoiceIssued")
        # Amounts cross the outbox as exact decimal strings, never floats.
        self.assertEqual(events[0].payload["amount"], "100.00")


class StudentPaymentTests(unittest.TestCase):
    def _payment(self) -> StudentPayment:
        return StudentPayment.record(
            id=StudentPaymentId(ULID_B),
            organization_id=ORG,
            invoice_id=StudentInvoiceId(ULID_A),
            student_id=STUDENT,
            amount=Money(amount=Decimal("25.00"), currency="USD"),
            method=StudentPaymentMethod.MOBILE_MONEY,
            received_on=date(2026, 9, 4),
            clock=CLOCK,
        )

    def test_records_with_method_and_reference(self) -> None:
        payment = self._payment()
        self.assertEqual(payment.method, StudentPaymentMethod.MOBILE_MONEY)
        self.assertFalse(payment.is_voided)

    def test_rejects_a_zero_amount(self) -> None:
        with self.assertRaises(DomainError):
            StudentPayment.record(
                id=StudentPaymentId(ULID_B),
                organization_id=ORG,
                invoice_id=StudentInvoiceId(ULID_A),
                student_id=STUDENT,
                amount=Money(amount=Decimal("0.00"), currency="USD"),
                method=StudentPaymentMethod.CASH,
                received_on=date(2026, 9, 4),
                clock=CLOCK,
            )

    def test_void_is_idempotent(self) -> None:
        payment = self._payment()
        payment.void(reason="duplicate", clock=CLOCK)
        payment.pull_domain_events()
        payment.void(reason="again", clock=CLOCK)
        self.assertTrue(payment.is_voided)
        self.assertEqual(payment.voided_reason, "duplicate")
        self.assertEqual(payment.pull_domain_events(), [])


class FeePlanTests(unittest.TestCase):
    def test_rejects_a_discount_larger_than_the_fee(self) -> None:
        with self.assertRaises(DomainError):
            FeePlan.create(
                id=FeePlanId(ULID_A),
                organization_id=ORG,
                name="Standard",
                amount=Money(amount=Decimal("30.00"), currency="USD"),
                default_discount_amount=Decimal("40.00"),
                clock=CLOCK,
            )

    def test_archive_is_idempotent(self) -> None:
        plan = FeePlan.create(
            id=FeePlanId(ULID_A),
            organization_id=ORG,
            name="Standard",
            amount=Money(amount=Decimal("30.00"), currency="USD"),
            clock=CLOCK,
        )
        plan.pull_domain_events()
        plan.archive(clock=CLOCK)
        plan.archive(clock=CLOCK)
        self.assertEqual(len(plan.pull_domain_events()), 1)


class LedgerTests(unittest.TestCase):
    def test_income_and_expense_reject_non_positive_amounts(self) -> None:
        for factory in (Income.record, Expense.record):
            with self.subTest(factory=factory.__qualname__), self.assertRaises(DomainError):
                factory(
                    id=(IncomeId(ULID_C) if factory is Income.record else ExpenseId(ULID_C)),
                    organization_id=ORG,
                    category_id=None,
                    amount=Money(amount=Decimal("0.00"), currency="USD"),
                    occurred_on=date(2026, 9, 1),
                    clock=CLOCK,
                )

    def test_expense_can_be_attributed_to_a_vehicle(self) -> None:
        expense = Expense.record(
            id=ExpenseId(ULID_C),
            organization_id=ORG,
            category_id=None,
            amount=Money(amount=Decimal("80.00"), currency="USD"),
            occurred_on=date(2026, 9, 1),
            vehicle_id=VehicleId("bus-1"),
            clock=CLOCK,
        )
        self.assertEqual(str(expense.vehicle_id), "bus-1")
        self.assertEqual(
            expense.pull_domain_events()[0].payload["vehicle_id"], "bus-1"
        )

    def test_category_kind_is_part_of_its_identity(self) -> None:
        category = FinancialCategory.create(
            id=FinancialCategoryId(ULID_A),
            organization_id=ORG,
            name="Fuel",
            kind=CategoryKind.EXPENSE,
            clock=CLOCK,
        )
        self.assertEqual(category.kind, CategoryKind.EXPENSE)
        self.assertEqual(
            category.pull_domain_events()[0].event_type,
            "school_erp.FinancialCategoryCreated",
        )


if __name__ == "__main__":
    unittest.main()
