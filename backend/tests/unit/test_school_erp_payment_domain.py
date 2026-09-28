"""Domain tests for the ADR-0047 payment ledger (the allocation rule, and `ParentInvoice`'s
apply/reverse invariants) and ADR-0048 per-student pricing. Pure domain — no application
service, no fakes."""

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
    ParentBillingProfile,
    ParentPayment,
    PaymentAllocationInput,
    StudentBillingProfile,
    allocate_pro_rata,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    IncomeId,
    IncomeType,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
    ParentPaymentId,
    StudentBillingProfileId,
    StudentId,
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


def _invoice(fees: tuple[str, ...] = ("33.34", "33.33", "33.33")) -> ParentInvoice:
    return ParentInvoice.generate(
        id=ParentInvoiceId(_id("NV01")),
        organization_id=OrganizationId(_id("RG01")),
        parent_id=ParentId(_id("PR01")),
        period=BillingPeriod("2026-09"),
        currency="USD",
        due_date=date(2026, 9, 30),
        children=[
            BilledChild(
                line_id=_id(f"KN0{i}"),
                student_id=_id(f"ST0{i}"),
                amount=Decimal(fee),
                vehicle_id=_id("BS01"),
            )
            for i, fee in enumerate(fees, start=1)
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
        invoice = _invoice(("30.00", "30.00", "30.00"))
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
        invoice = _invoice(("30.00", "30.00", "30.00"))
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


class PerStudentPricingTests(unittest.TestCase):
    """ADR-0048: every line is its own student's fee; the family total is their sum."""

    def test_three_children_at_ten_twenty_thirty_make_a_sixty_invoice(self) -> None:
        invoice = _invoice(("10.00", "20.00", "30.00"))
        self.assertEqual([line.amount.amount for line in invoice.lines], [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")])
        self.assertEqual(invoice.amount.amount, Decimal("60.00"))
        self.assertEqual([line.balance_due for line in invoice.lines], [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")])
        self.assertEqual(invoice.pull_domain_events()[0].payload["amount"], "60.00")

    def test_a_thirty_dollar_payment_defaults_pro_rata_and_can_be_directed_instead(self) -> None:
        default = _invoice(("10.00", "20.00", "30.00"))
        self.assertEqual(
            [a.amount for a in default.default_allocation(Decimal("30.00"))],
            [Decimal("5.00"), Decimal("10.00"), Decimal("15.00")],
        )
        edited = _invoice(("10.00", "20.00", "30.00"))
        one, two, three = edited.lines
        edited.apply_payment(
            payment_id="p1",
            allocations=[LineAllocation(str(one.id), Decimal("10.00")), LineAllocation(str(two.id), Decimal("20.00"))],
            currency="USD",
            clock=CLOCK,
        )
        self.assertEqual([l.balance_due for l in edited.lines], [Decimal("0.00"), Decimal("0.00"), Decimal("30.00")])
        self.assertIs(edited.status, ParentInvoiceStatus.PARTIAL)
        self.assertEqual(edited.balance_due, Decimal("30.00"))

    def test_a_student_cannot_be_billed_twice_or_at_zero(self) -> None:
        def generate(children):
            return ParentInvoice.generate(
                id=ParentInvoiceId(_id("NV02")),
                organization_id=OrganizationId(_id("RG01")),
                parent_id=ParentId(_id("PR01")),
                period=BillingPeriod("2026-09"),
                currency="USD",
                due_date=date(2026, 9, 30),
                children=children,
                clock=CLOCK,
            )

        with self.assertRaises(DomainError):
            generate([
                BilledChild(line_id=_id("KN01"), student_id=_id("ST01"), amount=Decimal("10.00")),
                BilledChild(line_id=_id("KN02"), student_id=_id("ST01"), amount=Decimal("10.00")),
            ])
        with self.assertRaises(DomainError):
            generate([BilledChild(line_id=_id("KN01"), student_id=_id("ST01"), amount=Decimal("0.00"))])
        with self.assertRaises(DomainError):
            generate([])


class StudentBillingProfileTests(unittest.TestCase):
    def _open(self, fee: str = "10.00") -> StudentBillingProfile:
        return StudentBillingProfile.open(
            id=StudentBillingProfileId(_id("SB01")),
            organization_id=OrganizationId(_id("RG01")),
            student_id=StudentId(_id("ST01")),
            monthly_fee=Money(amount=Decimal(fee), currency="usd"),
            clock=CLOCK,
            actor_id="admin",
        )

    def test_a_fee_change_records_the_previous_figure_for_the_audit_trail(self) -> None:
        profile = self._open("10.00")
        created = profile.pull_domain_events()
        self.assertEqual(created[0].payload["previous_monthly_fee"], None)
        self.assertEqual(created[0].payload["monthly_fee"], "10.00")

        profile.change_fee(monthly_fee=Money(amount=Decimal("12.50"), currency="USD"), clock=CLOCK)
        (changed,) = profile.pull_domain_events()
        self.assertEqual(changed.event_type, "school_erp.StudentBillingFeeSet")
        self.assertEqual((changed.payload["previous_monthly_fee"], changed.payload["monthly_fee"]), ("10.00", "12.50"))

        profile.change_fee(monthly_fee=Money(amount=Decimal("12.50"), currency="USD"), clock=CLOCK)
        self.assertEqual(profile.pull_domain_events(), [], "an unchanged fee records nothing")

    def test_zero_means_free_and_a_negative_fee_is_refused(self) -> None:
        self.assertFalse(self._open("0.00").is_billable)
        self.assertTrue(self._open("0.01").is_billable)
        with self.assertRaises(DomainError):
            Money(amount=Decimal("-1.00"), currency="USD")


class ParentBillingProfileTermsTests(unittest.TestCase):
    def test_the_account_carries_terms_not_a_fee(self) -> None:
        profile = ParentBillingProfile.open(
            id=ParentBillingProfileId(_id("PB01")),
            organization_id=OrganizationId(_id("RG01")),
            parent_id=ParentId(_id("PR01")),
            currency="usd",
            billing_start_period=BillingPeriod("2026-09"),
            due_day=10,
            clock=CLOCK,
        )
        self.assertEqual(profile.currency, "USD")
        self.assertNotIn("monthly_fee", profile.pull_domain_events()[0].payload)
        profile.update_terms(currency="USD", billing_start_period=BillingPeriod("2026-10"), due_day=5, clock=CLOCK)
        self.assertEqual((str(profile.billing_start_period), profile.due_day), ("2026-10", 5))
        with self.assertRaises(DomainError):
            profile.update_terms(currency="DOLLARS", billing_start_period=BillingPeriod("2026-10"), due_day=5, clock=CLOCK)


if __name__ == "__main__":
    unittest.main()
