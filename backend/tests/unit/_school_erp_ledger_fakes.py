"""Shared in-memory fakes for the ADR-0047 payment ledger, used by every `school_erp` unit test
that needs a `SchoolErpUnitOfWork` — one fake, so the tests cannot drift into two different
ideas of what a payment query returns.

Mirrors `SqlAlchemyParentPaymentRepository`'s semantics: voided payments never count, the window
is on `received_on`, and student income is keyed by each allocation's own `vehicle_id`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from raad.modules.school_erp.domain.entities import (
    ParentInvoice,
    ParentPayment,
    PaymentAllocationInput,
)
from raad.modules.school_erp.domain.repositories import (
    ParentPaymentRepository,
    StudentIncomeRow,
    VehicleBillingSummary,
)
from raad.modules.school_erp.domain.value_objects import (
    Money,
    ParentInvoiceId,
    ParentInvoiceStatus,
    ParentPaymentId,
    StudentPaymentMethod,
)

_ZERO = Decimal("0.00")


class InMemoryParentPaymentRepository(ParentPaymentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, ParentPayment] = {}

    async def get(self, payment_id):
        return self.by_id.get(str(payment_id))

    def add(self, payment: ParentPayment) -> None:
        self.by_id[str(payment.id)] = payment

    async def get_by_idempotency_key(self, key: str):
        return next((p for p in self.by_id.values() if p.idempotency_key == key), None)

    def _sorted(self, payments):
        return sorted(payments, key=lambda p: (p.received_on, str(p.id)), reverse=True)

    async def list_for_invoice(self, invoice_id):
        return self._sorted(p for p in self.by_id.values() if str(p.invoice_id) == str(invoice_id))

    async def list_for_parent(self, parent_id):
        return self._sorted(p for p in self.by_id.values() if str(p.parent_id) == str(parent_id))

    async def list_for_student(self, student_id):
        return self._sorted(
            p
            for p in self.by_id.values()
            if any(str(a.student_id) == str(student_id) for a in p.allocations)
        )

    def _live_allocations(self, start: date, end: date):
        for payment in self.by_id.values():
            if payment.is_voided or not (start <= payment.received_on <= end):
                continue
            for allocation in payment.allocations:
                yield payment, allocation

    async def sum_student_income_between(self, *, start: date, end: date) -> Decimal:
        return sum((a.amount.amount for _, a in self._live_allocations(start, end)), _ZERO)

    async def student_income_by_vehicle_between(self, *, start: date, end: date):
        totals: dict[str | None, Decimal] = {}
        for _, allocation in self._live_allocations(start, end):
            key = str(allocation.vehicle_id) if allocation.vehicle_id else None
            totals[key] = totals.get(key, _ZERO) + allocation.amount.amount
        return totals

    async def student_income_rows_between(self, *, vehicle_id, start: date, end: date):
        wanted = str(vehicle_id) if vehicle_id else None
        totals: dict[tuple[str, str], Decimal] = {}
        for payment, allocation in self._live_allocations(start, end):
            key_vehicle = str(allocation.vehicle_id) if allocation.vehicle_id else None
            if key_vehicle != wanted:
                continue
            key = (str(allocation.student_id), str(payment.parent_id))
            totals[key] = totals.get(key, _ZERO) + allocation.amount.amount
        return [
            StudentIncomeRow(student_id=student, parent_id=parent, amount=amount)
            for (student, parent), amount in totals.items()
        ]

    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        return {payment.amount.currency for payment, _ in self._live_allocations(start, end)}


def invoices_for_student(invoices, student_id) -> list[ParentInvoice]:
    return sorted(
        (
            invoice
            for invoice in invoices
            if any(str(line.student_id) == str(student_id) for line in invoice.lines)
        ),
        key=lambda invoice: str(invoice.period),
        reverse=True,
    )


def summarise_lines_by_vehicle(invoices, *, start: date, end: date) -> list[VehicleBillingSummary]:
    buckets: dict[str | None, list] = {}
    for invoice in invoices:
        if invoice.status is ParentInvoiceStatus.CANCELLED:
            continue
        if not (start <= invoice.invoice_date <= end):
            continue
        for line in invoice.lines:
            key = str(line.vehicle_id) if line.vehicle_id else None
            buckets.setdefault(key, []).append(line)
    return [
        VehicleBillingSummary(
            vehicle_id=vehicle_id,
            student_count=len({str(line.student_id) for line in lines}),
            billed_amount=sum((line.amount.amount for line in lines), _ZERO),
            outstanding_amount=sum((line.balance_due for line in lines), _ZERO),
        )
        for vehicle_id, lines in buckets.items()
    ]


def pay_invoice(
    uow,
    invoice: ParentInvoice,
    amount: str,
    *,
    ids,
    clock,
    received_on: date = date(2026, 9, 10),
    method: str = "cash",
) -> ParentPayment:
    """Records a real payment against a seeded invoice exactly as the service does: default
    pro-rata allocation, applied to the invoice, stored on the fake UoW."""
    total = Decimal(amount)
    allocations = invoice.default_allocation(total)
    payment_id = ids.new_id()
    invoice.apply_payment(
        payment_id=payment_id,
        allocations=allocations,
        currency=invoice.amount.currency,
        clock=clock,
    )
    payment = ParentPayment.record(
        id=ParentPaymentId(payment_id),
        organization_id=invoice.organization_id,
        parent_id=invoice.parent_id,
        invoice_id=ParentInvoiceId(str(invoice.id)),
        amount=Money(amount=total, currency=invoice.amount.currency),
        method=StudentPaymentMethod(method),
        received_on=received_on,
        allocations=[
            PaymentAllocationInput(
                allocation_id=ids.new_id(),
                line_id=allocation.line_id,
                student_id=str(invoice.line_for(allocation.line_id).student_id),
                vehicle_id=(
                    str(invoice.line_for(allocation.line_id).vehicle_id)
                    if invoice.line_for(allocation.line_id).vehicle_id
                    else None
                ),
                amount=allocation.amount,
            )
            for allocation in allocations
        ],
        clock=clock,
    )
    uow.parent_payments.add(payment)
    return payment
