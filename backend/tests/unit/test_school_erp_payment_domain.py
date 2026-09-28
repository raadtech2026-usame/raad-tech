"""Domain tests for the ADR-0047 payment ledger: the allocation rule, and `ParentInvoice`'s
apply/reverse invariants. Pure domain — no application service, no fakes."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import ConflictError, DomainError, RuleViolationError
from raad.core.time.clock import Clock
from raad.modules.school_erp.domain.entities import (
    BilledChild,
    Income,
    LineAllocation,
    ParentInvoice,
    ParentPayment,
    PaymentAllocationInput,
    allocate_pro_rata,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    IncomeId,
    IncomeType,
    Money,
    OrganizationId,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
    ParentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)


class _Clock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 9, 5, tzinfo=timezone.utc)


CLOCK = _Clock()
_PREFIX = "01J8Z3K9G6X8YV5T4N2R7Q"


def _id(suffix: str) -> str:
    return f"{_PREFIX}{suffix}"


def _invoice(total: str = "100.00", children: int = 3) -> ParentInvoice:
    return ParentInvoice.generate(
        id=ParentInvoiceId(_id("NV01")),
        organization_id=OrganizationId(_id("RG01")),
        parent_id=ParentId(_id("PR01")),
        period=BillingPeriod("2026-09"),
        amount=Money(amount=Decimal(total), currency="USD"),
        due_date=date(2026, 9, 30),
        children=[
            BilledChild(line_id=_id(f"KN0{i}"), student_id=_id(f"ST0{i}"), vehicle_id=_id("BS01"))
            for i in range(1, children + 1)
        ],
        clock=CLOCK,
    )


class AllocateProRataTests(unittest.TestCase):
    def test_sums_exactly_and_never_exceeds_a_balance(self) -> None:
        balances = [("a", Decimal("33.34")), ("b", Decimal("33.33")), ("c", Decimal("33.33"))]
        for total in ("0.01", "1.00", "10.00", "50.00", "99.99", "100.00"):
            with self.subTest(total=total):
                result = allocate_pro_rata(Decimal(total), balances)
                self.assertEqual(sum(a.amount for a in result), Decimal(total))
                capacity = dict(balances)
                for allocation in result:
                    self.assertLessEqual(allocation.amount, capacity[allocation.line_id])

    def test_lines_with_nothing_owed_receive_nothing(self) -> None:
        result = allocate_pro_rata(Decimal("10.00"), [("a", Decimal("0.00")), ("b", Decimal("40.00"))])
        self.assertEqual(result, [LineAllocation(line_id="b", amount=Decimal("10.00"))])

    def test_overpayment_and_non_positive_amounts_are_refused(self) -> None:
        with self.assertRaises(DomainError):
            allocate_pro_rata(Decimal("40.01"), [("a", Decimal("40.00"))])
        with self.assertRaises(DomainError):
            allocate_pro_rata(Decimal("0.00"), [("a", Decimal("40.00"))])


class ParentInvoicePaymentTests(unittest.TestCase):
    def test_status_is_derived_from_the_lines(self) -> None:
        invoice = _invoice("90.00")
        line = invoice.lines[0]
        invoice.apply_payment(
            payment_id="p1", allocations=[LineAllocation(str(line.id), Decimal("30.00"))],
            currency="usd", clock=CLOCK,
        )
        self.assertIs(invoice.status, ParentInvoiceStatus.PARTIAL)
        self.assertEqual(invoice.amount_paid, Decimal("30.00"))
        self.assertEqual(line.balance_due, Decimal("0.00"))

        invoice.apply_payment(
            payment_id="p2", allocations=invoice.default_allocation(Decimal("60.00")),
            currency="USD", clock=CLOCK,
        )
        self.assertIs(invoice.status, ParentInvoiceStatus.PAID)
        self.assertEqual(sum(l.amount_paid for l in invoice.lines), invoice.amount.amount)

        invoice.reverse_payment(
            payment_id="p1", allocations=[LineAllocation(str(line.id), Decimal("30.00"))], clock=CLOCK
        )
        self.assertIs(invoice.status, ParentInvoiceStatus.PARTIAL)
        self.assertEqual(invoice.amount_paid, Decimal("60.00"))

    def test_guards(self) -> None:
        invoice = _invoice("90.00")
        line_id = str(invoice.lines[0].id)
        with self.assertRaises(DomainError):
            invoice.apply_payment(payment_id="p", allocations=[LineAllocation(line_id, Decimal("30.01"))], currency="USD", clock=CLOCK)
        with self.assertRaises(DomainError):
            invoice.apply_payment(payment_id="p", allocations=[LineAllocation(line_id, Decimal("1.00"))], currency="SOS", clock=CLOCK)
        with self.assertRaises(DomainError):
            invoice.apply_payment(payment_id="p", allocations=[LineAllocation(line_id, Decimal("1.00")), LineAllocation(line_id, Decimal("1.00"))], currency="USD", clock=CLOCK)
        with self.assertRaises(DomainError):
            invoice.apply_payment(payment_id="p", allocations=[LineAllocation("not-a-line", Decimal("1.00"))], currency="USD", clock=CLOCK)
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))

        invoice.apply_payment(payment_id="p", allocations=invoice.default_allocation(Decimal("90.00")), currency="USD", clock=CLOCK)
        with self.assertRaises(ConflictError):
            invoice.ensure_accepts_payment("USD")
        with self.assertRaises(RuleViolationError):
            invoice.cancel(reason="x", clock=CLOCK)

    def test_a_cancelled_invoice_refuses_payment(self) -> None:
        invoice = _invoice()
        invoice.cancel(reason="Issued in error", clock=CLOCK)
        with self.assertRaises(RuleViolationError):
            invoice.ensure_accepts_payment("USD")


class ParentPaymentTests(unittest.TestCase):
    def _record(self, allocations, amount="30.00"):
        return ParentPayment.record(
            id=ParentPaymentId(_id("PY01")),
            organization_id=OrganizationId(_id("RG01")),
            parent_id=ParentId(_id("PR01")),
            invoice_id=ParentInvoiceId(_id("NV01")),
            amount=Money(amount=Decimal(amount), currency="USD"),
            method=StudentPaymentMethod.CASH,
            received_on=date(2026, 9, 12),
            allocations=allocations,
            clock=CLOCK,
        )

    def test_allocations_must_add_up_to_the_payment(self) -> None:
        with self.assertRaises(DomainError):
            self._record(
                [PaymentAllocationInput(_id("AX01"), _id("KN01"), _id("ST01"), None, Decimal("20.00"))]
            )

    def test_void_needs_a_reason_and_is_idempotent(self) -> None:
        payment = self._record(
            [PaymentAllocationInput(_id("AX01"), _id("KN01"), _id("ST01"), _id("BS01"), Decimal("30.00"))]
        )
        with self.assertRaises(DomainError):
            payment.void(reason=" ", clock=CLOCK)
        self.assertTrue(payment.void(reason="Recorded twice", clock=CLOCK))
        self.assertFalse(payment.void(reason="Again", clock=CLOCK))
        self.assertEqual(payment.voided_reason, "Recorded twice")
        self.assertEqual(str(payment.allocations[0].vehicle_id), _id("BS01"))


class IncomeTypeTests(unittest.TestCase):
    def test_daily_vehicle_income_requires_a_vehicle_and_other_does_not(self) -> None:
        common = dict(
            organization_id=OrganizationId(_id("RG01")),
            category_id=None,
            amount=Money(amount=Decimal("20.00"), currency="USD"),
            occurred_on=date(2026, 9, 3),
            clock=CLOCK,
        )
        with self.assertRaises(DomainError):
            Income.record(id=IncomeId(_id("NC01")), income_type=IncomeType.DAILY_VEHICLE, **common)
        daily = Income.record(
            id=IncomeId(_id("NC02")), income_type=IncomeType.DAILY_VEHICLE,
            vehicle_id=VehicleId(_id("BS01")), **common,
        )
        other = Income.record(id=IncomeId(_id("NC03")), **common)
        self.assertIs(daily.income_type, IncomeType.DAILY_VEHICLE)
        self.assertIs(other.income_type, IncomeType.OTHER)
        self.assertIsNone(other.vehicle_id)
        event = daily.pull_domain_events()[0]
        self.assertEqual(event.payload["income_type"], "daily_vehicle")


if __name__ == "__main__":
    unittest.main()
