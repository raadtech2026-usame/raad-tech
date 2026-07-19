"""Application-layer command validators for `billing` (Backend LLD §4.1's application table:
"Contextual pre-conditions of a use-case"). These check pre-conditions that need repository I/O
— exactly why they're an application concern and not a domain one, mirroring
`transport_ops.application.validators`'s identical reasoning and exact `ensure_*` naming.

**No `ensure_idempotency_key_available`-style function exists here — deliberately, not an
oversight.** Every other uniqueness check in this codebase (`ensure_plate_no_available`,
`ensure_route_name_available`, `ensure_email_available`) rejects a duplicate with
`ConflictError`. `payments.idempotency_key` is documented with the opposite semantics (API
Contracts §12: "a repeat with the same key returns the **original result**", not an error) — so
its "pre-condition check" is a find-or-return-existing lookup performed directly in
`BillingApplicationService.initiate_payment` (`get_by_idempotency_key`, `domain/
repositories.py`'s `PaymentRepository`), not a boolean gate that belongs in this file.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.domain.entities import Invoice, Plan, Subscription
from raad.modules.billing.domain.value_objects import InvoiceId, PlanId, SubscriptionId


async def ensure_plan_exists(uow: BillingUnitOfWork, plan_id: PlanId) -> Plan:
    plan = await uow.plans.get(plan_id)
    if plan is None:
        raise NotFoundError(f"Plan {plan_id} not found.")
    return plan


async def ensure_subscription_exists(
    uow: BillingUnitOfWork, subscription_id: SubscriptionId
) -> Subscription:
    subscription = await uow.subscriptions.get(subscription_id)
    if subscription is None:
        raise NotFoundError(f"Subscription {subscription_id} not found.")
    return subscription


async def ensure_invoice_exists(uow: BillingUnitOfWork, invoice_id: InvoiceId) -> Invoice:
    invoice = await uow.invoices.get(invoice_id)
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return invoice
