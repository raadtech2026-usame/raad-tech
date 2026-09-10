"""HTTP surface of the `billing` module (C8). Mounted at `/api/v1/billing` (+ subscriptions,
invoices, payments per Backend LLD §16.1). Thin controllers only (Backend LLD §16.2): parse the
request DTO, call exactly one `BillingApplicationService` method, return the response DTO. No
business logic, no repository/SQLAlchemy access — every error already maps to the standard
`ErrorEnvelope` via the global exception handlers. Mirrors `transport_ops.api.routers`'s shape.

**Five routes, matching API Contracts §4.7's table exactly (lines 170-174) — no more, no
less.** The task scope for this phase explicitly forbids `POST/PATCH/DELETE /billing/plans` and
`POST/PATCH /billing/subscriptions`: neither has a documented write route anywhere in §4.7 (the
only way either aggregate is created is `OpenOrganizationSubscriptionCommand`'s internal,
HTTP-less orchestration — `application/services.py`'s own module docstring), so none is built here, the
same "routes are contract-driven, not capability-driven" restraint `transport_ops.api.routers`
already applies to `Route.remove_stop`/`move_stop`/`Trip.interrupt`/`resume`.

- `GET /billing/plans` — list (§4.7 line 170, "in-scope" — no role restriction documented).
  **Paginated/filterable/sortable per §7/§8** (Pagination/Filtering/Sorting phase): `?page&
  page_size`, `?filter[field]=value`, `?sort=field`, `?q=` — mirrors `organization`/`iam`'s
  identical `list_page`-backed shape.
- `GET /billing/subscriptions` — list (line 171, "Org Admin/Finance"). **Tenant-scoped for real
  since ADR-0021** — this docstring previously read "Not filtered to the caller's own
  subscriptions... unscoped by tenant/ownership", which stopped being true when ADR-0021 moved
  scope enforcement into `SqlAlchemyRepositoryBase._apply_scope`: `list_page` routes through it,
  and `subscriptions` carries `organization_id`, so an Org Admin sees only their own
  organization's rows. Corrected here rather than left as a false claim about a security
  property (found during ADR-0039's own audit).
  **The "Parent(own)" half of §4.7's role column no longer applies at all** — ADR-0039 §7 revoked
  `billing.subscriptions.list` from `parent`, since RAAD SaaS subscriptions are billed to the
  Organization (ADR-0016) and a parent has no legitimate view of them. Parent-facing *school*
  finance is `school_erp`'s concern (ADR-0038), not this module's.
- `GET /billing/invoices` — list (line 172). Identically tenant-scoped since ADR-0021 (`invoices`
  carries `organization_id`), and identically no longer parent-reachable since ADR-0039 §7 —
  `billing.invoices.list` was the specific stale grant that let a parent enumerate RAAD's own
  SaaS invoices to their school. Same pagination/filtering/sorting as `/plans` above.
- `POST /billing/payments` — initiate (line 173, "Org Admin/Finance; Parent(own, allowed even
  when access-denied)"). Requires the `Idempotency-Key` header (API rule #6, API Contracts
  §12) — read directly here via `Header(...)`, not a body field; a missing header is a
  transport-level 422 (`RequestValidationError`), not a hand-rolled check. With no
  `PaymentProviderPort` bound this phase (`core/di/bootstrap.py`), calling this **persists the
  `Payment` as `PENDING` and then raises `NotImplementedError`** (500) at the charge step — see
  `BillingApplicationService.initiate_payment`'s own docstring; this is the documented,
  intentional "fail loudly, don't fake a charge" behavior, not a bug.

**`POST /billing/payments/callback` is deliberately NOT wired to
`BillingApplicationService.handle_payment_callback` this phase — a real, flagged gap, not an
oversight.** Two independent blockers, both confirmed by re-reading the source documents in
full, not assumed:

1. **No signature/secret verification scheme is documented anywhere.** Phase-2 §20.4 and API
   Contracts §12 both *mandate* verification ("signature/secret verified... unverified callbacks
   rejected and audited") but neither names an algorithm, header, or secret/config source.
   `.claude/rules/security.md` #10 makes this a firm platform invariant — accepting a callback
   without real verification would be a live security hole, not a permissible simplification.
2. **The caller has no `Principal` to authenticate with, structurally.** Every other route in
   this codebase enforces authorization via `Depends(require_permission(...))`, which resolves a
   `Principal` from a bearer JWT (`interfaces/http/deps.get_principal`). §4.7's own role column
   for this one row is `provider (signed)` — an external system, not one of the seven roles
   `core.tenancy.principal.Role` defines. `PaymentCallbackCommand.actor: Principal` (
   `application/commands.py`) has no documented value for this caller type either.

Rather than inventing a signature scheme or fabricating a placeholder `Principal` to force this
through the existing `require_permission` shape — both would be undocumented behavior — the route
below exists (so the documented path itself isn't silently missing from the API surface) but
immediately raises `NotImplementedError`, mirroring `interfaces/http/deps.get_scope`'s identical
"fail loudly rather than fake a pass" treatment for its own pending dependency.

**ADR-0022 wires `POST /billing/payments/callback` for real.** No `Depends(require_permission
(...))`/`Depends(get_principal)` at all — a payment provider has no `Principal`, and the
signature check below *is* this route's authentication (matching how Stripe's, and every
mainstream provider's, own webhook documentation describes this exact model). The two blockers
this docstring used to describe are resolved: the signature scheme is the bound
`PaymentProviderPort`'s own `verify_webhook_signature` (Stripe's documented HMAC-SHA256 scheme,
`infra/adapters.py`), and the actor is `SYSTEM_PRINCIPAL` (`core/tenancy/principal.py`) — the
same "least-bad available role" constant `notifications`' own Notification Worker already uses
for an identical gap, not a new RBAC concept. A missing/invalid signature is a `401`
(`AuthenticationError`), logged (not a domain-event audit row — there is no aggregate mutation
to attach one to for a *rejected* request, `.claude/rules/security.md` #8's own audit-logging
requirement satisfied via structured logging here instead, the same posture the login-rate-
limiter's own "log once, don't cascade-fail" precedent already established for a comparable
no-aggregate-to-write-to situation). If no `PaymentProviderPort` is bound at all (no provider
configured this deployment), the route still raises `NotImplementedError` exactly as before.

**ADR-0022 also adds `GET /billing/payments`** — no list route existed for `Payment` at all
before this; see `PaymentListItemResponse`'s own docstring (`api/schemas.py`) for why it's a
fuller shape than `PaymentResponse`. Gated by a new `billing.payments.list` permission.

**Not exposed this phase** (uniform-CRUD `GET/PATCH/DELETE` beyond what's listed above): no row
in §4.7 documents a per-id `GET` for `Plan`/`Subscription`/`Invoice`, and no
HTTP route at all (confirmed absent from §4.7's table; `domain/entities.py`'s own docstring
already flags this).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Request, Response, status

from raad.core.di.container import Container
from raad.core.errors.exceptions import AuthenticationError, NotFoundError
from raad.core.pagination import (
    FilterCondition,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import SYSTEM_PRINCIPAL, Principal
from raad.interfaces.http.deps import (
    get_container,
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.billing.api.deps import (
    get_billing_service,
    get_billing_uow,
    get_billing_uow_unscoped,
)
from raad.modules.billing.api.schemas import (
    CreatePlanRequest,
    UpdatePlanRequest,
    InitiatePaymentRequest,
    InvoiceResponse,
    PaymentListItemResponse,
    PaymentResponse,
    PlanResponse,
    ExtendGracePeriodRequest,
    SubscriptionResponse,
)
from raad.modules.billing.application.commands import (
    ActivatePlanCommand,
    CreatePlanCommand,
    DisablePlanCommand,
    # ADR-0039's three platform-admin lifecycle actions. Absent from this import list until
    # 2026-09-09, so `POST /billing/subscriptions/{id}/suspend`, `/reactivate` and
    # `/extend-grace` every one raised `NameError` at request time and answered 500 — the whole
    # admin half of the subscription lifecycle was unreachable. Nothing caught it: the contract
    # suite checks route *existence* through `app.openapi()` without issuing a request, and the
    # unit tests call `BillingApplicationService` directly, so no test ever executed this module.
    ExtendGracePeriodCommand,
    InitiatePaymentCommand,
    ReactivateSubscriptionCommand,
    SuspendSubscriptionCommand,
    UpdatePlanCommand,
)
from raad.modules.billing.application.ports import (
    BillingUnitOfWork,
    PaymentProviderPort,
    UnhandledWebhookEventError,
)
from raad.modules.billing.application.queries import (
    GetSubscriptionByIdQuery,
    InvoiceDTO,
    ListInvoicesQuery,
    ListPaymentsQuery,
    ListPlansQuery,
    ListSubscriptionsQuery,
    PaymentDTO,
    PlanDTO,
    SubscriptionDTO,
)
from raad.modules.billing.application.services import BillingApplicationService

logger = logging.getLogger(__name__)

billing_router = APIRouter()


def _plan_dto_to_response(plan: PlanDTO) -> PlanResponse:
    return PlanResponse(
        id=plan.id,
        name=plan.name,
        billing_scope=plan.billing_scope,
        amount=plan.amount,
        currency=plan.currency,
        billing_cycle=plan.billing_cycle,
        vehicle_limit=plan.vehicle_limit,
        device_limit=plan.device_limit,
        user_limit=plan.user_limit,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _subscription_dto_to_response(
    subscription: SubscriptionDTO,
) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        organization_id=subscription.organization_id,
        plan_id=subscription.plan_id,
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        auto_renew=subscription.auto_renew,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        past_due_since=subscription.past_due_since,
        grace_period_ends_at=subscription.grace_period_ends_at,
        suspended_at=subscription.suspended_at,
        cancelled_at=subscription.cancelled_at,
        expired_at=subscription.expired_at,
    )


def _invoice_dto_to_response(invoice: InvoiceDTO) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        organization_id=invoice.organization_id,
        subscription_id=invoice.subscription_id,
        number=invoice.number,
        amount=invoice.amount,
        currency=invoice.currency,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        status=invoice.status,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        paid_at=invoice.paid_at,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def _payment_dto_to_response(payment: PaymentDTO) -> PaymentResponse:
    return PaymentResponse(payment_id=payment.id, status=payment.status)


def _payment_dto_to_list_item_response(payment: PaymentDTO) -> PaymentListItemResponse:
    return PaymentListItemResponse(
        id=payment.id,
        organization_id=payment.organization_id,
        invoice_id=payment.invoice_id,
        provider=payment.provider,
        provider_ref=payment.provider_ref,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        failure_reason=payment.failure_reason,
        created_at=payment.created_at,
        confirmed_at=payment.confirmed_at,
    )


@billing_router.get(
    "/plans",
    response_model=OffsetPageResponse[PlanResponse],
    status_code=status.HTTP_200_OK,
    summary="List billing plans",
    description=(
        "In-scope, no documented role restriction (API Contracts §4.7 line 170). "
        "Paginated/filterable/sortable per §7/§8: `?page&page_size`, `?filter[field]=value`, "
        "`?sort=field`, `?q=`. Authorization resolves against the real seeded RBAC permission "
        "matrix (ADR-0004)."
    ),
)
async def list_plans(
    principal: Principal = Depends(require_permission(Permission("billing.plans.list"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[PlanResponse]:
    page = await billing_service.list_plans(
        ListPlansQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _plan_dto_to_response)


@billing_router.get(
    "/subscriptions",
    response_model=OffsetPageResponse[SubscriptionResponse],
    status_code=status.HTTP_200_OK,
    summary="List subscriptions",
    description=(
        "Org Admin/Finance; Parent(own) (API Contracts §4.7 line 171). Not yet filtered to the "
        "caller's own subscriptions — see this file's module docstring for the inherited, "
        "system-wide `ScopeResolver` gap. Paginated/filterable/sortable per §7/§8: `?page&"
        "page_size`, `?filter[field]=value`, `?sort=field`. Authorization resolves against the "
        "real seeded RBAC permission matrix."
    ),
)
async def list_subscriptions(
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.list"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[SubscriptionResponse]:
    page = await billing_service.list_subscriptions(
        ListSubscriptionsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _subscription_dto_to_response)


# --- ADR-0039: organization subscription lifecycle ------------------------------------------
#
# Four routes, none of them in API Contracts §4.7 (which documents five billing routes and no
# subscription-write surface at all) — added under ADR-0039, cited here rather than silently,
# the same posture `/drivers` and every other post-Phase-3.3 route in this codebase carries.
#
# `/subscriptions/current` is deliberately **before** any `/subscriptions/{id}`-shaped path
# would be: FastAPI matches in declaration order, so a literal segment must be declared first or
# `current` would be captured as an id. The uniform-CRUD `GET /subscriptions/{subscription_id}`
# added below (2026-09-10, Subscription Details) is declared *after* this whole block for the
# identical reason — it must come after `current`, not before it.


@billing_router.get(
    "/subscriptions/current",
    response_model=SubscriptionResponse | None,
    status_code=status.HTTP_200_OK,
    summary="The caller's own organization's current subscription",
    description=(
        "ADR-0039. Self-scoped: resolves from `principal.organization_id` alone and takes no "
        "path/query identifier, so there is nothing for a caller to override — the same "
        "structural IDOR-immunity ADR-0023's `/me` routes established. Returns `null` when the "
        "organization has no subscription at all. Backs the Org Admin billing/suspension UI."
    ),
)
async def get_current_subscription(
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.list"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> SubscriptionResponse | None:
    if principal.org_id is None:
        # A platform-staff caller has no own-organization to report. 404 rather than an empty
        # 200, so "you have no subscription" and "this question doesn't apply to you" stay
        # distinguishable.
        raise NotFoundError("This caller has no organization of its own.")
    subscription = await billing_service.get_current_subscription_for_organization(
        principal.org_id, uow=uow
    )
    return (
        _subscription_dto_to_response(subscription)
        if subscription is not None
        else None
    )


@billing_router.post(
    "/subscriptions/{subscription_id}/suspend",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Suspend an organization's subscription (platform admin)",
    description=(
        "ADR-0039 §5. Blocks **every** user of that organization on their next request "
        "(`interfaces/http/subscription_guard`), not just its admin — the organization is the "
        "tenant. Requires `billing.subscriptions.manage`, held only by `founder`/"
        "`finance_staff`: deliberately not `org_admin`, so a tenant can never lift or apply "
        "its own suspension."
    ),
)
async def suspend_subscription(
    subscription_id: str,
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.manage"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow_unscoped),
) -> SubscriptionResponse:
    dto = await billing_service.suspend_subscription(
        SuspendSubscriptionCommand(subscription_id=subscription_id, actor=principal),
        uow=uow,
    )
    return _subscription_dto_to_response(dto)


@billing_router.post(
    "/subscriptions/{subscription_id}/reactivate",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate an organization's subscription (platform admin)",
    description=(
        "ADR-0039 §5. Returns the organization to `ACTIVE` **without** moving the billing "
        "period — that is what distinguishes reactivation from renewal. Refuses terminal "
        "(`cancelled`/`expired`) subscriptions with a `DomainError`: those must come back "
        "through a real new subscription or an explicit renewal with a fresh period, never a "
        "status flip that would leave `current_period_end` in the past and have the next "
        "lifecycle tick immediately re-suspend them."
    ),
)
async def reactivate_subscription(
    subscription_id: str,
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.manage"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow_unscoped),
) -> SubscriptionResponse:
    dto = await billing_service.reactivate_subscription(
        ReactivateSubscriptionCommand(
            subscription_id=subscription_id, actor=principal
        ),
        uow=uow,
    )
    return _subscription_dto_to_response(dto)


@billing_router.post(
    "/subscriptions/{subscription_id}/extend-grace",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extend a delinquent organization's grace period (platform admin)",
    description=(
        "ADR-0039 §1 / requirement 39G. Moves the subscription to `grace_period`, which grants "
        "access exactly like `past_due` but records that a human deliberately chose it — making "
        "the extension an auditable state transition rather than a silent date edit."
    ),
)
async def extend_grace_period(
    subscription_id: str,
    payload: ExtendGracePeriodRequest,
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.manage"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow_unscoped),
) -> SubscriptionResponse:
    dto = await billing_service.extend_grace_period(
        ExtendGracePeriodCommand(
            subscription_id=subscription_id,
            grace_period_ends_at=payload.grace_period_ends_at,
            actor=principal,
        ),
        uow=uow,
    )
    return _subscription_dto_to_response(dto)


@billing_router.get(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a subscription by id",
    description=(
        "Uniform-CRUD addition, not in API Contracts §4.7 (which documents `GET "
        "/subscriptions` — list only — cited here rather than silently, the same posture "
        "`/drivers` and every other post-Phase-3.3 route in this codebase carries). Backs the "
        "Founder's Subscription Details troubleshooting page. Not new business logic: "
        "`BillingApplicationService.get_subscription_by_id`/`GetSubscriptionByIdQuery` already "
        "existed, built and unit-tested, with no route wired to them — the same "
        "\"use-case-exists-no-approved-endpoint-yet\" gap this codebase names for "
        "`Route.remove_stop`/`Trip.interrupt`, now closed for this one specifically because the "
        "Founder needs a stable, shareable link to one subscription rather than paging through "
        "the list and matching an id by eye. **Declared after every `/subscriptions/...` route "
        "above**, `current` included — FastAPI matches path templates in declaration order, and "
        "a `{subscription_id}` segment declared first would swallow every literal sibling path "
        "(`current`, and each action verb) as if it were an id."
    ),
)
async def get_subscription_by_id(
    subscription_id: str,
    principal: Principal = Depends(
        require_permission(Permission("billing.subscriptions.list"))
    ),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> SubscriptionResponse:
    subscription = await billing_service.get_subscription_by_id(
        GetSubscriptionByIdQuery(subscription_id=subscription_id), uow=uow
    )
    return _subscription_dto_to_response(subscription)


@billing_router.get(
    "/invoices",
    response_model=OffsetPageResponse[InvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="List invoices",
    description=(
        "Org Admin/Finance; Parent(own) (API Contracts §4.7 line 172). Same inherited "
        "unscoped-list caveat as `list_subscriptions`. Paginated/filterable/sortable per §7/§8: "
        "`?page&page_size`, `?filter[field]=value`, `?sort=field`, `?q=`. Authorization "
        "resolves against the real seeded RBAC permission matrix."
    ),
)
async def list_invoices(
    principal: Principal = Depends(require_permission(Permission("billing.invoices.list"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[InvoiceResponse]:
    page = await billing_service.list_invoices(
        ListInvoicesQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _invoice_dto_to_response)


@billing_router.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate a payment",
    description=(
        "Org Admin/Finance; Parent(own, allowed even when access-denied) (API Contracts §4.7 "
        "line 173). Requires the `Idempotency-Key` header (API rule #6, §12) — a repeat with "
        "the same key returns the original result, never a double charge. With no "
        "`PaymentProviderPort` bound this phase, persists the `Payment` as `PENDING` and then "
        "raises `NotImplementedError` (500) at the charge step — see this file's module "
        "docstring and `BillingApplicationService.initiate_payment`'s own docstring. "
        "Authorization (distinct from the payment-provider gap above) resolves against the "
        "real seeded RBAC permission matrix."
    ),
)
async def initiate_payment(
    body: InitiatePaymentRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission(Permission("billing.payments.create"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PaymentResponse:
    command = InitiatePaymentCommand(
        invoice_id=body.invoice_id,
        method=body.method,
        amount=body.amount,
        currency=body.currency,
        idempotency_key=idempotency_key,
        actor=principal,
        msisdn=body.msisdn,
        payment_method_token=body.payment_method_token,
    )
    payment = await billing_service.initiate_payment(command, uow=uow)
    return _payment_dto_to_response(payment)


@billing_router.get(
    "/payments",
    response_model=OffsetPageResponse[PaymentListItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List payments (payment history)",
    description=(
        "ADR-0022 — no list route existed for `Payment` at all before this. Founder/Finance "
        "Staff/Org Admin (mirrors `.subscriptions.list`'s existing grant set — not Regional "
        "Manager/Support Staff, who hold only `billing.plans.list`). Paginated/filterable/"
        "sortable per §7/§8: `?page&page_size`, `?filter[field]=value`, `?sort=field`."
    ),
)
async def list_payments(
    principal: Principal = Depends(require_permission(Permission("billing.payments.list"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
) -> OffsetPageResponse[PaymentListItemResponse]:
    page = await billing_service.list_payments(
        ListPaymentsQuery(page_request=page_request, sort=sort, filters=filters),
        uow=uow,
    )
    return to_offset_page_response(page, _payment_dto_to_list_item_response)


@billing_router.post(
    "/payments/callback",
    status_code=status.HTTP_200_OK,
    summary="Payment provider webhook",
    description=(
        "API Contracts §4.7 line 174 — provider (signed) webhook (ADR-0022). No "
        "`Depends(require_permission(...))` — the signature check below is this route's own "
        "authentication, matching how mainstream payment providers document this exact model. "
        "See this file's module docstring for the full design."
    ),
)
async def payment_callback(
    request: Request,
    container: Container = Depends(get_container),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow_unscoped),
) -> Response:
    provider = container.try_resolve(PaymentProviderPort)
    if provider is None:
        raise NotImplementedError(
            "POST /billing/payments/callback is not implemented: no PaymentProviderPort is "
            "bound this deployment (RAAD_PAYMENT__PROVIDER is unset or missing credentials). "
            "See routers.py's module docstring and core/di/bootstrap.py."
        )

    raw_body = await request.body()
    # Header name is Stripe's own — the only currently-bound, real provider (ADR-0022). Becomes
    # provider-aware (a header-name lookup per active provider) once EVC Plus/Zaad are ever
    # real; not attempted now for two stub adapters that cannot receive a webhook at all.
    signature_header = request.headers.get("Stripe-Signature", "")

    if not signature_header or not provider.verify_webhook_signature(
        payload=raw_body, signature_header=signature_header
    ):
        # `.claude/rules/security.md` #10: unverified callbacks are rejected and audited. No
        # aggregate mutation happens for a rejected request, so there is nothing to attach an
        # `audit_entries` row to (that table is written transactionally from a real domain
        # event) — logged instead, the same "log loudly, don't cascade-fail" posture the login
        # rate limiter's own Redis-unreachable path already established for a comparable
        # no-aggregate-to-write-to situation.
        logger.warning(
            "payment_webhook_signature_rejected",
            extra={"has_signature_header": bool(signature_header)},
        )
        raise AuthenticationError("Invalid or missing webhook signature.")

    try:
        event = provider.parse_webhook_event(payload=raw_body)
    except UnhandledWebhookEventError:
        # Stripe's own documentation: acknowledge (200) any event type this adapter doesn't
        # act on, rather than erroring — a non-2xx response makes Stripe retry indefinitely.
        return Response(status_code=status.HTTP_200_OK)

    try:
        await billing_service.handle_webhook_event(
            event, provider="stripe", uow=uow, actor=SYSTEM_PRINCIPAL
        )
    except NotFoundError:
        # A verified, well-formed event for a payment this system has no record of (e.g. a
        # test-mode event replayed against a payment that was since deleted in a sandbox) —
        # acknowledged rather than retried forever, the identical reasoning as the unhandled-
        # event-type branch above.
        logger.warning("payment_webhook_unknown_payment", extra={"provider": "stripe"})
        return Response(status_code=status.HTTP_200_OK)

    return Response(status_code=status.HTTP_200_OK)


# --- ADR-0040 §4: plan catalogue management -------------------------------------------------
#
# `Plan` had no write route at all before this — the catalogue could only be seeded. All four
# routes are Founder-only via a new `billing.plans.manage` permission, deliberately distinct from
# the read-only `billing.plans.list` five roles already hold: changing what RAAD charges is
# materially more sensitive than reading the price list (`.claude/rules/security.md` #1).


@billing_router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subscription plan",
)
async def create_plan(
    body: CreatePlanRequest,
    principal: Principal = Depends(require_permission(Permission("billing.plans.manage"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PlanResponse:
    plan = await billing_service.create_plan(
        CreatePlanCommand(
            name=body.name,
            billing_scope=body.billing_scope,
            amount=body.amount,
            currency=body.currency,
            billing_cycle=body.billing_cycle,
            vehicle_limit=body.vehicle_limit,
            device_limit=body.device_limit,
            user_limit=body.user_limit,
            actor=principal,
        ),
        uow=uow,
    )
    return _plan_dto_to_response(plan)


@billing_router.patch(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a subscription plan",
    description=(
        "Repricing applies from the next billing period onward — an already-issued invoice keeps "
        "the amount it was issued at."
    ),
)
async def update_plan(
    plan_id: str,
    body: UpdatePlanRequest,
    principal: Principal = Depends(require_permission(Permission("billing.plans.manage"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PlanResponse:
    plan = await billing_service.update_plan(
        UpdatePlanCommand(
            plan_id=plan_id,
            name=body.name,
            amount=body.amount,
            currency=body.currency,
            vehicle_limit=body.vehicle_limit,
            device_limit=body.device_limit,
            user_limit=body.user_limit,
            actor=principal,
        ),
        uow=uow,
    )
    return _plan_dto_to_response(plan)


@billing_router.post(
    "/plans/{plan_id}/activate",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate a plan (make it sellable)",
)
async def activate_plan(
    plan_id: str,
    principal: Principal = Depends(require_permission(Permission("billing.plans.manage"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PlanResponse:
    plan = await billing_service.activate_plan(
        ActivatePlanCommand(plan_id=plan_id, actor=principal), uow=uow
    )
    return _plan_dto_to_response(plan)


@billing_router.post(
    "/plans/{plan_id}/disable",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Disable a plan (stop offering it)",
    description=(
        "Existing subscriptions on a disabled plan are unaffected — this withdraws the plan from "
        "the catalogue, it does not cancel anyone's service."
    ),
)
async def disable_plan(
    plan_id: str,
    principal: Principal = Depends(require_permission(Permission("billing.plans.manage"))),
    billing_service: BillingApplicationService = Depends(get_billing_service),
    uow: BillingUnitOfWork = Depends(get_billing_uow),
) -> PlanResponse:
    plan = await billing_service.disable_plan(
        DisablePlanCommand(plan_id=plan_id, actor=principal), uow=uow
    )
    return _plan_dto_to_response(plan)
