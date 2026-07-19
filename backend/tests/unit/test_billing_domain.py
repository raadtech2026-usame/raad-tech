"""Domain-only tests for `billing`'s five aggregates (Phase 15). Stdlib `unittest` — no `pytest`
(not an approved dependency), mirroring `test_transport_ops_trip_domain.py`'s established
precedent. One file covering all five aggregates, mirroring `application/queries.py`'s own
"one phase, one file" consolidation for the same task scope ("all five documented aggregates in
one phase").

Covers: value-object validation (ULID id types, `Money`), construction, every documented
lifecycle method per aggregate (idempotent same-state no-ops where the source flags one),
domain-event emission (type/aggregate_type/payload spot checks), and repository-interface shape.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
    TransportFeeRepository,
)
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    InvoiceStatus,
    Money,
    OrganizationId,
    PaymentId,
    PaymentStatus,
    PlanId,
    PlanStatus,
    StudentId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    SubscriptionStatus,
    TransportFeeId,
    TransportFeeStatus,
)

VALID_PLAN_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3PN"
VALID_SUBSCRIPTION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3SB"
VALID_INVOICE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3JV"
VALID_PAYMENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3PY"
VALID_TRANSPORT_FEE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3TF"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_SUBSCRIBER_REF = "some-opaque-subscriber-ref"
VALID_STUDENT_REF = "some-opaque-student-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


# --- Value objects -----------------------------------------------------------------------


class UlidValueObjectValidationTests(unittest.TestCase):
    def test_plan_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(PlanId(VALID_PLAN_ULID)), VALID_PLAN_ULID)

    def test_plan_id_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PlanId("TOOSHORT")

    def test_plan_id_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            PlanId(VALID_PLAN_ULID.lower())

    def test_subscription_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(SubscriptionId(VALID_SUBSCRIPTION_ULID)), VALID_SUBSCRIPTION_ULID)

    def test_invoice_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(InvoiceId(VALID_INVOICE_ULID)), VALID_INVOICE_ULID)

    def test_payment_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(PaymentId(VALID_PAYMENT_ULID)), VALID_PAYMENT_ULID)

    def test_transport_fee_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(
            str(TransportFeeId(VALID_TRANSPORT_FEE_ULID)), VALID_TRANSPORT_FEE_ULID
        )


class OpaqueCrossModuleValueObjectTests(unittest.TestCase):
    def test_organization_id_non_empty_constructs(self) -> None:
        self.assertEqual(str(OrganizationId(VALID_ORG_ULID)), VALID_ORG_ULID)

    def test_organization_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("")

    def test_subscriber_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(SubscriberId(VALID_SUBSCRIBER_REF)), VALID_SUBSCRIBER_REF)

    def test_subscriber_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            SubscriberId("")

    def test_student_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(StudentId(VALID_STUDENT_REF)), VALID_STUDENT_REF)

    def test_student_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentId("")


class MoneyValidationTests(unittest.TestCase):
    def test_valid_money_constructs(self) -> None:
        money = Money(10.00, "USD")
        self.assertEqual(money.amount, 10.00)
        self.assertEqual(money.currency, "USD")

    def test_negative_amount_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Money(-1.00, "USD")

    def test_zero_amount_is_accepted(self) -> None:
        Money(0.00, "USD")

    def test_wrong_length_currency_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Money(10.00, "US")


# --- Plan ----------------------------------------------------------------------------------


class PlanTests(unittest.TestCase):
    def _make_plan(self) -> Plan:
        return Plan.create(
            id=PlanId(VALID_PLAN_ULID),
            name="Standard",
            billing_scope=BillingScope.ORGANIZATION,
            price=Money(50.00, "USD"),
            billing_cycle=BillingCycle.MONTHLY,
            vehicle_limit=10,
            clock=CLOCK,
        )

    def test_create_starts_active(self) -> None:
        plan = self._make_plan()
        self.assertEqual(plan.status, PlanStatus.ACTIVE)

    def test_create_records_plan_created_event(self) -> None:
        plan = self._make_plan()
        events = plan.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "PlanCreated")
        self.assertEqual(events[0].aggregate_type, "Plan")
        self.assertIsNone(events[0].org_id)

    def test_create_with_empty_name_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Plan.create(
                id=PlanId(VALID_PLAN_ULID),
                name="",
                billing_scope=BillingScope.ORGANIZATION,
                price=Money(50.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=CLOCK,
            )

    def test_disable_then_activate_round_trips(self) -> None:
        plan = self._make_plan()
        plan.pull_domain_events()
        plan.disable(clock=CLOCK)
        self.assertEqual(plan.status, PlanStatus.INACTIVE)
        events = plan.pull_domain_events()
        self.assertEqual(events[0].event_type, "PlanDisabled")

        plan.activate(clock=CLOCK)
        self.assertEqual(plan.status, PlanStatus.ACTIVE)
        events = plan.pull_domain_events()
        self.assertEqual(events[0].event_type, "PlanActivated")

    def test_activate_when_already_active_is_idempotent_no_op(self) -> None:
        plan = self._make_plan()
        plan.pull_domain_events()
        plan.activate(clock=CLOCK)
        self.assertEqual(plan.pull_domain_events(), [])

    def test_disable_when_already_inactive_is_idempotent_no_op(self) -> None:
        plan = self._make_plan()
        plan.pull_domain_events()
        plan.disable(clock=CLOCK)
        plan.pull_domain_events()
        plan.disable(clock=CLOCK)
        self.assertEqual(plan.pull_domain_events(), [])


# --- Subscription ----------------------------------------------------------------------------


class SubscriptionTests(unittest.TestCase):
    def _make_subscription(self) -> Subscription:
        return Subscription.open(
            id=SubscriptionId(VALID_SUBSCRIPTION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            subscriber_type=SubscriberType.PARENT,
            subscriber_id=SubscriberId(VALID_SUBSCRIBER_REF),
            plan_id=PlanId(VALID_PLAN_ULID),
            clock=CLOCK,
        )

    def test_open_starts_trial(self) -> None:
        subscription = self._make_subscription()
        self.assertEqual(subscription.status, SubscriptionStatus.TRIAL)
        self.assertIsNone(subscription.current_period_start)
        self.assertIsNone(subscription.current_period_end)

    def test_open_records_subscription_opened_event(self) -> None:
        subscription = self._make_subscription()
        events = subscription.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "SubscriptionOpened")
        self.assertEqual(events[0].org_id, VALID_ORG_ULID)

    def test_renew_transitions_to_active_and_sets_period(self) -> None:
        subscription = self._make_subscription()
        subscription.pull_domain_events()
        start = datetime(2026, 7, 20, tzinfo=timezone.utc)
        end = datetime(2026, 8, 19, tzinfo=timezone.utc)
        subscription.renew(period_start=start, period_end=end, clock=CLOCK)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(subscription.current_period_start, start)
        self.assertEqual(subscription.current_period_end, end)
        events = subscription.pull_domain_events()
        self.assertEqual(events[0].event_type, "SubscriptionRenewed")

    def test_renew_from_expired_still_succeeds_no_restriction_documented(self) -> None:
        subscription = self._make_subscription()
        subscription.expire(clock=CLOCK)
        subscription.pull_domain_events()
        start = datetime(2026, 7, 20, tzinfo=timezone.utc)
        end = datetime(2026, 8, 19, tzinfo=timezone.utc)
        subscription.renew(period_start=start, period_end=end, clock=CLOCK)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)

    def test_expire_records_subscription_expired_event(self) -> None:
        subscription = self._make_subscription()
        subscription.pull_domain_events()
        subscription.expire(clock=CLOCK)
        self.assertEqual(subscription.status, SubscriptionStatus.EXPIRED)
        events = subscription.pull_domain_events()
        self.assertEqual(events[0].event_type, "SubscriptionExpired")

    def test_expire_when_already_expired_is_idempotent_no_op(self) -> None:
        subscription = self._make_subscription()
        subscription.expire(clock=CLOCK)
        subscription.pull_domain_events()
        subscription.expire(clock=CLOCK)
        self.assertEqual(subscription.pull_domain_events(), [])

    def test_suspend_and_cancel_transitions(self) -> None:
        subscription = self._make_subscription()
        subscription.pull_domain_events()
        subscription.suspend(clock=CLOCK)
        self.assertEqual(subscription.status, SubscriptionStatus.SUSPENDED)
        events = subscription.pull_domain_events()
        self.assertEqual(events[0].event_type, "SubscriptionSuspended")

        subscription.cancel(clock=CLOCK)
        self.assertEqual(subscription.status, SubscriptionStatus.CANCELLED)
        events = subscription.pull_domain_events()
        self.assertEqual(events[0].event_type, "SubscriptionCancelled")


# --- Invoice ---------------------------------------------------------------------------------


class InvoiceTests(unittest.TestCase):
    def _make_invoice(self) -> Invoice:
        return Invoice.issue(
            id=InvoiceId(VALID_INVOICE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            subscription_id=SubscriptionId(VALID_SUBSCRIPTION_ULID),
            amount=Money(50.00, "USD"),
            period_start=date(2026, 7, 20),
            period_end=date(2026, 8, 19),
            due_at=None,
            clock=CLOCK,
        )

    def test_issue_starts_issued_not_draft(self) -> None:
        invoice = self._make_invoice()
        self.assertEqual(invoice.status, InvoiceStatus.ISSUED)
        self.assertIsNotNone(invoice.issued_at)
        self.assertIsNone(invoice.paid_at)

    def test_issue_sets_number_to_own_id(self) -> None:
        invoice = self._make_invoice()
        self.assertEqual(invoice.number, str(invoice.id))

    def test_issue_records_invoice_issued_event(self) -> None:
        invoice = self._make_invoice()
        events = invoice.pull_domain_events()
        self.assertEqual(events[0].event_type, "InvoiceIssued")

    def test_mark_paid_sets_status_and_paid_at(self) -> None:
        invoice = self._make_invoice()
        invoice.pull_domain_events()
        invoice.mark_paid(clock=CLOCK)
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertEqual(invoice.paid_at, CLOCK.now())
        events = invoice.pull_domain_events()
        self.assertEqual(events[0].event_type, "InvoicePaid")

    def test_mark_paid_when_already_paid_is_idempotent_no_op(self) -> None:
        invoice = self._make_invoice()
        invoice.mark_paid(clock=CLOCK)
        invoice.pull_domain_events()
        invoice.mark_paid(clock=CLOCK)
        self.assertEqual(invoice.pull_domain_events(), [])

    def test_void_sets_status(self) -> None:
        invoice = self._make_invoice()
        invoice.pull_domain_events()
        invoice.void(clock=CLOCK)
        self.assertEqual(invoice.status, InvoiceStatus.VOID)
        events = invoice.pull_domain_events()
        self.assertEqual(events[0].event_type, "InvoiceVoided")

    def test_invoice_status_enum_has_no_failed_value(self) -> None:
        self.assertNotIn("failed", [status.value for status in InvoiceStatus])


# --- Payment ---------------------------------------------------------------------------------


class PaymentTests(unittest.TestCase):
    def _make_payment(self) -> Payment:
        return Payment.initiate(
            id=PaymentId(VALID_PAYMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            invoice_id=InvoiceId(VALID_INVOICE_ULID),
            provider="evcplus",
            msisdn_masked="+2526••••••",
            amount=Money(50.00, "USD"),
            idempotency_key="idem-key-001",
            clock=CLOCK,
        )

    def test_initiate_starts_pending(self) -> None:
        payment = self._make_payment()
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertIsNone(payment.provider_ref)
        self.assertIsNone(payment.confirmed_at)

    def test_initiate_with_empty_idempotency_key_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Payment.initiate(
                id=PaymentId(VALID_PAYMENT_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                invoice_id=InvoiceId(VALID_INVOICE_ULID),
                provider="evcplus",
                msisdn_masked=None,
                amount=Money(50.00, "USD"),
                idempotency_key="",
                clock=CLOCK,
            )

    def test_initiate_with_empty_provider_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Payment.initiate(
                id=PaymentId(VALID_PAYMENT_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                invoice_id=InvoiceId(VALID_INVOICE_ULID),
                provider="",
                msisdn_masked=None,
                amount=Money(50.00, "USD"),
                idempotency_key="idem-key-002",
                clock=CLOCK,
            )

    def test_mark_processing_transitions(self) -> None:
        payment = self._make_payment()
        payment.pull_domain_events()
        payment.mark_processing(clock=CLOCK)
        self.assertEqual(payment.status, PaymentStatus.PROCESSING)
        events = payment.pull_domain_events()
        self.assertEqual(events[0].event_type, "PaymentProcessing")

    def test_mark_paid_sets_provider_ref_and_confirmed_at(self) -> None:
        payment = self._make_payment()
        payment.pull_domain_events()
        payment.mark_paid(provider_ref="EVC-REF-123", clock=CLOCK)
        self.assertEqual(payment.status, PaymentStatus.PAID)
        self.assertEqual(payment.provider_ref, "EVC-REF-123")
        self.assertEqual(payment.confirmed_at, CLOCK.now())
        events = payment.pull_domain_events()
        self.assertEqual(events[0].event_type, "PaymentConfirmed")

    def test_mark_failed_sets_status(self) -> None:
        payment = self._make_payment()
        payment.pull_domain_events()
        payment.mark_failed(clock=CLOCK)
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        events = payment.pull_domain_events()
        self.assertEqual(events[0].event_type, "PaymentFailed")

    def test_mark_expired_when_already_expired_is_idempotent_no_op(self) -> None:
        payment = self._make_payment()
        payment.mark_expired(clock=CLOCK)
        payment.pull_domain_events()
        payment.mark_expired(clock=CLOCK)
        self.assertEqual(payment.pull_domain_events(), [])

    def test_payment_has_no_retry_method(self) -> None:
        """See `entities.py`'s module docstring: retry is a brand-new `Payment.initiate(...)`
        call with a fresh idempotency key, never a mutation of the failed row."""
        payment = self._make_payment()
        self.assertFalse(hasattr(payment, "retry"))


# --- TransportFee ----------------------------------------------------------------------------


class TransportFeeTests(unittest.TestCase):
    def _make_fee(self) -> TransportFee:
        return TransportFee.create(
            id=TransportFeeId(VALID_TRANSPORT_FEE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            student_id=StudentId(VALID_STUDENT_REF),
            period="2026-07",
            amount=Money(20.00, "USD"),
            clock=CLOCK,
        )

    def test_create_starts_due(self) -> None:
        fee = self._make_fee()
        self.assertEqual(fee.status, TransportFeeStatus.DUE)

    def test_create_with_empty_period_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            TransportFee.create(
                id=TransportFeeId(VALID_TRANSPORT_FEE_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                student_id=StudentId(VALID_STUDENT_REF),
                period="",
                amount=Money(20.00, "USD"),
                clock=CLOCK,
            )

    def test_mark_paid_records_event(self) -> None:
        fee = self._make_fee()
        fee.pull_domain_events()
        fee.mark_paid(clock=CLOCK)
        self.assertEqual(fee.status, TransportFeeStatus.PAID)
        events = fee.pull_domain_events()
        self.assertEqual(events[0].event_type, "TransportFeePaid")

    def test_mark_overdue_records_event(self) -> None:
        fee = self._make_fee()
        fee.pull_domain_events()
        fee.mark_overdue(clock=CLOCK)
        self.assertEqual(fee.status, TransportFeeStatus.OVERDUE)
        events = fee.pull_domain_events()
        self.assertEqual(events[0].event_type, "TransportFeeOverdue")

    def test_waive_records_event(self) -> None:
        fee = self._make_fee()
        fee.pull_domain_events()
        fee.waive(clock=CLOCK)
        self.assertEqual(fee.status, TransportFeeStatus.WAIVED)
        events = fee.pull_domain_events()
        self.assertEqual(events[0].event_type, "TransportFeeWaived")

    def test_waive_when_already_waived_is_idempotent_no_op(self) -> None:
        fee = self._make_fee()
        fee.waive(clock=CLOCK)
        fee.pull_domain_events()
        fee.waive(clock=CLOCK)
        self.assertEqual(fee.pull_domain_events(), [])


# --- Repository interface shape -----------------------------------------------------------


class RepositoryInterfaceShapeTests(unittest.TestCase):
    def test_plan_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            PlanRepository()  # type: ignore[abstract]

    def test_subscription_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all", "get_active_by_subscriber"):
            self.assertTrue(hasattr(SubscriptionRepository, method))

    def test_invoice_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all"):
            self.assertTrue(hasattr(InvoiceRepository, method))

    def test_payment_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all", "get_by_idempotency_key"):
            self.assertTrue(hasattr(PaymentRepository, method))

    def test_transport_fee_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all"):
            self.assertTrue(hasattr(TransportFeeRepository, method))


if __name__ == "__main__":
    unittest.main()
