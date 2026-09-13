"""HTTP routes for `school_erp` (ADR-0038, ADR-0040), mounted at `/api/v1/school-finance`.

**Prefix choice.** `.claude/rules/api.md` #2 maps one resource router per bounded context and
`.claude/rules/naming.md` requires kebab-case paths. `/school-finance` rather than `/finance`
because `/billing` already carries the RAAD -> Organization money flow and a bare `/finance`
would read as its sibling; the prefix names which of the three financial domains this is.

**None of these routes appears in API Contracts §4.7**, which predates the ERP charter entirely.
They are added under ADR-0038/ADR-0040 and cited here rather than silently — the same posture
`/drivers` and every other post-Phase-3.3 route in this codebase carries.

**`organization_id` is resolved, never trusted.** Every write body accepts an optional
`organization_id`; `_resolve_organization_id` below fills it from the caller's own principal for
an Org Admin and *rejects* a mismatched one. Platform staff must state it explicitly, because
they legitimately act across organizations and there is nothing on their principal to default to.
The application service re-checks it anyway (`_enforce_own_organization`) — two layers, because
this is the write-side IDOR class ADR-0021 documented as not covered by repository scoping.

**Permissions** live under the new `school_erp.*` namespace (ADR-0040 §7). `parent` holds none of
them in this phase: ADR-0038's closing constraint requires parent access to school invoices to be
per-student-ownership scoped, and a role-wide grant here would repeat exactly the stale-grant
exposure ADR-0039 §7 had to clean up.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status

from raad.core.errors.exceptions import AuthorizationError
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import (
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.school_erp.api.deps import (
    get_parent_finance_service,
    get_school_erp_service,
    get_school_erp_uow,
)
from raad.modules.school_erp.api.schemas import (
    CancelParentInvoiceRequest,
    CancelStudentInvoiceRequest,
    CreateFeePlanRequest,
    CreateFinancialCategoryRequest,
    CreateOrUpdateParentBillingProfileRequest,
    ExpenseResponse,
    FeePlanResponse,
    FinanceSummaryResponse,
    FinancialCategoryResponse,
    GenerateParentInvoicesRequest,
    GenerateStudentInvoicesRequest,
    IncomeResponse,
    IssueStudentInvoiceRequest,
    ParentBillingProfileResponse,
    ParentChildFinancialResponse,
    ParentFinancialSummaryResponse,
    ParentInvoiceDetailResponse,
    ParentInvoiceLineResponse,
    ParentInvoiceSummaryResponse,
    ProfitAndLossResponse,
    RecordExpenseRequest,
    RecordIncomeRequest,
    RecordStudentPaymentRequest,
    SetParentBillingProfileStatusRequest,
    SetParentInvoicePaymentStatusRequest,
    StudentInvoiceResponse,
    StudentPaymentResponse,
    UpdateFeePlanRequest,
    UpdateFinancialCategoryRequest,
    VehicleFinanceResponse,
    VoidLedgerEntryRequest,
    VoidStudentPaymentRequest,
)
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
    RecordStudentPaymentCommand,
    SetParentBillingProfileStatusCommand,
    SetParentInvoicePaymentStatusCommand,
    UpdateFeePlanCommand,
    UpdateFinancialCategoryCommand,
    VoidExpenseCommand,
    VoidIncomeCommand,
    VoidStudentPaymentCommand,
)
from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
from raad.modules.school_erp.application.queries import (
    ExpenseDTO,
    FeePlanDTO,
    FinancialCategoryDTO,
    IncomeDTO,
    ParentBillingProfileDTO,
    ParentFinancialSummaryDTO,
    ParentInvoiceDetailDTO,
    ParentInvoiceSummaryDTO,
    StudentInvoiceDTO,
    StudentPaymentDTO,
)
from raad.modules.school_erp.application.services import (
    ParentFinanceApplicationService,
    SchoolErpApplicationService,
)
from raad.modules.transport_ops.api.deps import get_transport_ops_uow
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork

school_finance_router = APIRouter()

_PLATFORM_ROLES = (
    Role.FOUNDER,
    Role.REGIONAL_MANAGER,
    Role.SUPPORT_STAFF,
    Role.FINANCE_STAFF,
)


def _resolve_organization_id(principal: Principal, supplied: str | None) -> str:
    """The organization a write applies to.

    An Org Admin's own organization is used when the body omits it, and a *mismatched* one is
    rejected outright rather than silently overridden — silently correcting it would hide a
    client bug (or an attempt) that the caller should see.

    Platform staff must state it explicitly: they act across organizations legitimately, so there
    is nothing on their principal to default to, and guessing would be worse than asking.
    """
    if principal.role is Role.ORG_ADMIN:
        own = principal.org_id
        if own is None:
            raise AuthorizationError("Org Admin principal carries no organization")
        if supplied is not None and supplied != own:
            raise AuthorizationError(
                "org_admin may only manage school finance within their own organization."
            )
        return own
    if supplied is None:
        raise AuthorizationError(
            "organization_id is required for platform roles — it cannot be inferred."
        )
    return supplied


# ---- Response mappers ----------------------------------------------------------------------


def _category_response(dto: FinancialCategoryDTO) -> FinancialCategoryResponse:
    return FinancialCategoryResponse(**dto.__dict__)


def _fee_plan_response(dto: FeePlanDTO) -> FeePlanResponse:
    return FeePlanResponse(**dto.__dict__)


def _invoice_response(dto: StudentInvoiceDTO) -> StudentInvoiceResponse:
    return StudentInvoiceResponse(**dto.__dict__)


def _payment_response(dto: StudentPaymentDTO) -> StudentPaymentResponse:
    return StudentPaymentResponse(**dto.__dict__)


def _income_response(dto: IncomeDTO) -> IncomeResponse:
    return IncomeResponse(**dto.__dict__)


def _expense_response(dto: ExpenseDTO) -> ExpenseResponse:
    return ExpenseResponse(**dto.__dict__)


def _parent_financial_summary_response(
    dto: ParentFinancialSummaryDTO,
) -> ParentFinancialSummaryResponse:
    """`dto.children` is a list of `ParentChildFinancialDTO` dataclass instances — unlike every
    other `_xxx_response` helper above, a bare `**dto.__dict__` unpack does not work here:
    Pydantic v2 does not coerce an arbitrary dataclass into a *different* model class on its own,
    so passing one straight through as a `list[ParentChildFinancialResponse]` field raises
    `ValidationError` (`type=model_type`) — the identical "a renderer must coerce what a builder
    hands it" lesson CLAUDE.md's Permanent Engineering Lessons already names for report builders.
    Each row is converted explicitly instead."""
    return ParentFinancialSummaryResponse(
        **{
            **dto.__dict__,
            "children": [ParentChildFinancialResponse(**child.__dict__) for child in dto.children],
        }
    )


# ============================================================================================
# Financial categories
# ============================================================================================


@school_finance_router.get(
    "/categories",
    response_model=OffsetPageResponse[FinancialCategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List financial categories",
)
async def list_categories(
    principal: Principal = Depends(
        require_permission(Permission("school_erp.categories.list"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[FinancialCategoryResponse]:
    async with uow:
        page = await uow.financial_categories.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import financial_category_to_dto

    return to_offset_page_response(
        page, lambda c: _category_response(financial_category_to_dto(c))
    )


@school_finance_router.post(
    "/categories",
    response_model=FinancialCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a financial category",
)
async def create_category(
    body: CreateFinancialCategoryRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.categories.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FinancialCategoryResponse:
    dto = await service.create_financial_category(
        CreateFinancialCategoryCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            kind=body.kind,
            parent_category_id=body.parent_category_id,
            description=body.description,
            actor=principal,
        ),
        uow=uow,
    )
    return _category_response(dto)


@school_finance_router.patch(
    "/categories/{category_id}",
    response_model=FinancialCategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename a financial category",
)
async def update_category(
    category_id: str,
    body: UpdateFinancialCategoryRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.categories.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FinancialCategoryResponse:
    dto = await service.update_financial_category(
        UpdateFinancialCategoryCommand(
            category_id=category_id,
            name=body.name,
            description=body.description,
            actor=principal,
        ),
        uow=uow,
    )
    return _category_response(dto)


@school_finance_router.post(
    "/categories/{category_id}/archive",
    response_model=FinancialCategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a financial category",
    description=(
        "Archived, never deleted — historical income and expense rows keep pointing at it, and a "
        "hard delete would orphan them."
    ),
)
async def archive_category(
    category_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.categories.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FinancialCategoryResponse:
    dto = await service.archive_financial_category(
        ArchiveFinancialCategoryCommand(category_id=category_id, actor=principal), uow=uow
    )
    return _category_response(dto)


# ============================================================================================
# Fee plans
# ============================================================================================


@school_finance_router.get(
    "/fee-plans",
    response_model=OffsetPageResponse[FeePlanResponse],
    status_code=status.HTTP_200_OK,
    summary="List fee plans",
)
async def list_fee_plans(
    principal: Principal = Depends(
        require_permission(Permission("school_erp.fee_plans.list"))
    ),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[FeePlanResponse]:
    async with uow:
        page = await uow.fee_plans.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import fee_plan_to_dto

    return to_offset_page_response(page, lambda f: _fee_plan_response(fee_plan_to_dto(f)))


@school_finance_router.post(
    "/fee-plans",
    response_model=FeePlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fee plan",
)
async def create_fee_plan(
    body: CreateFeePlanRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.fee_plans.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FeePlanResponse:
    dto = await service.create_fee_plan(
        CreateFeePlanCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            amount=body.amount,
            currency=body.currency,
            default_discount_amount=body.default_discount_amount,
            description=body.description,
            actor=principal,
        ),
        uow=uow,
    )
    return _fee_plan_response(dto)


@school_finance_router.patch(
    "/fee-plans/{fee_plan_id}",
    response_model=FeePlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a fee plan",
    description=(
        "Changing a fee plan never retro-changes an already-issued invoice — a `StudentInvoice` "
        "captures its own amount at issue time."
    ),
)
async def update_fee_plan(
    fee_plan_id: str,
    body: UpdateFeePlanRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.fee_plans.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FeePlanResponse:
    dto = await service.update_fee_plan(
        UpdateFeePlanCommand(
            fee_plan_id=fee_plan_id,
            name=body.name,
            amount=body.amount,
            currency=body.currency,
            default_discount_amount=body.default_discount_amount,
            description=body.description,
            actor=principal,
        ),
        uow=uow,
    )
    return _fee_plan_response(dto)


@school_finance_router.post(
    "/fee-plans/{fee_plan_id}/archive",
    response_model=FeePlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a fee plan",
)
async def archive_fee_plan(
    fee_plan_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.fee_plans.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FeePlanResponse:
    dto = await service.archive_fee_plan(
        ArchiveFeePlanCommand(fee_plan_id=fee_plan_id, actor=principal), uow=uow
    )
    return _fee_plan_response(dto)


# ============================================================================================
# Student invoices
# ============================================================================================


@school_finance_router.get(
    "/student-invoices",
    response_model=OffsetPageResponse[StudentInvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="List student invoices",
    description=(
        "Filterable by `status`, `period`, `student_id`, `vehicle_id`, `route_id`, `fee_plan_id` "
        "per §7/§8 — which is what backs both the 'who has not paid' view and the per-bus roster."
    ),
)
async def list_student_invoices(
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_invoices.list"))
    ),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[StudentInvoiceResponse]:
    async with uow:
        page = await uow.student_invoices.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import student_invoice_to_dto

    return to_offset_page_response(
        page, lambda i: _invoice_response(student_invoice_to_dto(i))
    )


@school_finance_router.post(
    "/student-invoices",
    response_model=StudentInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a student invoice",
    description=(
        "Captures the student's current route/vehicle/driver at issue time, so the bill stays a "
        "historical record of the transport it was for. Conflicts (409) if the student already "
        "has an invoice for the period."
    ),
)
async def issue_student_invoice(
    body: IssueStudentInvoiceRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_invoices.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> StudentInvoiceResponse:
    dto = await service.issue_student_invoice(
        IssueStudentInvoiceCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            student_id=body.student_id,
            period=body.period,
            due_date=body.due_date,
            fee_plan_id=body.fee_plan_id,
            amount=body.amount,
            currency=body.currency,
            discount_amount=body.discount_amount,
            notes=body.notes,
            actor=principal,
        ),
        uow=uow,
    )
    return _invoice_response(dto)


@school_finance_router.post(
    "/student-invoices/generate",
    response_model=list[StudentInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate student invoices for a period (monthly billing run)",
    description=(
        "Idempotent: students who already have an invoice for the period are skipped rather than "
        "double-charged, so a partially-failed batch can simply be re-run. Returns only the "
        "invoices actually created."
    ),
)
async def generate_student_invoices(
    body: GenerateStudentInvoicesRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_invoices.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> list[StudentInvoiceResponse]:
    dtos = await service.generate_student_invoices(
        GenerateStudentInvoicesCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            period=body.period,
            due_date=body.due_date,
            fee_plan_id=body.fee_plan_id,
            student_ids=body.student_ids,
            actor=principal,
        ),
        uow=uow,
    )
    return [_invoice_response(dto) for dto in dtos]


@school_finance_router.post(
    "/student-invoices/{invoice_id}/cancel",
    response_model=StudentInvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel (or waive) a student invoice",
)
async def cancel_student_invoice(
    invoice_id: str,
    body: CancelStudentInvoiceRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_invoices.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> StudentInvoiceResponse:
    dto = await service.cancel_student_invoice(
        CancelStudentInvoiceCommand(
            invoice_id=invoice_id, reason=body.reason, actor=principal
        ),
        uow=uow,
    )
    return _invoice_response(dto)


@school_finance_router.get(
    "/student-invoices/{invoice_id}/payments",
    response_model=list[StudentPaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Payments received against one invoice",
)
async def list_invoice_payments(
    invoice_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_payments.list"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> list[StudentPaymentResponse]:
    dtos = await service.list_payments_for_invoice(invoice_id=invoice_id, uow=uow)
    return [_payment_response(dto) for dto in dtos]


@school_finance_router.post(
    "/student-invoices/{invoice_id}/payments",
    response_model=StudentPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment against a student invoice",
    description=(
        "Creates the payment and advances the invoice in one transaction. Partial payments are "
        "supported: paying less than the balance leaves the invoice `partially_paid`."
    ),
)
async def record_student_payment(
    invoice_id: str,
    body: RecordStudentPaymentRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_payments.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> StudentPaymentResponse:
    dto = await service.record_student_payment(
        RecordStudentPaymentCommand(
            invoice_id=invoice_id,
            amount=body.amount,
            currency=body.currency,
            method=body.method,
            received_on=body.received_on,
            reference=body.reference,
            notes=body.notes,
            actor=principal,
        ),
        uow=uow,
    )
    return _payment_response(dto)


@school_finance_router.post(
    "/student-payments/{payment_id}/void",
    response_model=StudentPaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Void a student payment",
    description=(
        "Reverses the payment's effect on its invoice in the same transaction. The payment row "
        "is retained as voided — financial rows are never hard-deleted."
    ),
)
async def void_student_payment(
    payment_id: str,
    body: VoidStudentPaymentRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_payments.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> StudentPaymentResponse:
    dto = await service.void_student_payment(
        VoidStudentPaymentCommand(payment_id=payment_id, reason=body.reason, actor=principal),
        uow=uow,
    )
    return _payment_response(dto)


@school_finance_router.get(
    "/student-payments",
    response_model=OffsetPageResponse[StudentPaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="List student payments",
)
async def list_student_payments(
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_payments.list"))
    ),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[StudentPaymentResponse]:
    async with uow:
        page = await uow.student_payments.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import student_payment_to_dto

    return to_offset_page_response(
        page, lambda p: _payment_response(student_payment_to_dto(p))
    )


# ============================================================================================
# Income / Expense
# ============================================================================================


@school_finance_router.get(
    "/income",
    response_model=OffsetPageResponse[IncomeResponse],
    status_code=status.HTTP_200_OK,
    summary="List organization income",
)
async def list_income(
    principal: Principal = Depends(require_permission(Permission("school_erp.income.list"))),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[IncomeResponse]:
    async with uow:
        page = await uow.income.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import income_to_dto

    return to_offset_page_response(page, lambda i: _income_response(income_to_dto(i)))


@school_finance_router.post(
    "/income",
    response_model=IncomeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record organization income",
    description=(
        "For income that is *not* a student fee — student fees reach the ledger through student "
        "invoices and payments, and recording one here as well would double-count it."
    ),
)
async def record_income(
    body: RecordIncomeRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.income.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> IncomeResponse:
    dto = await service.record_income(
        RecordIncomeCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            category_id=body.category_id,
            amount=body.amount,
            currency=body.currency,
            occurred_on=body.occurred_on,
            description=body.description,
            reference=body.reference,
            actor=principal,
        ),
        uow=uow,
    )
    return _income_response(dto)


@school_finance_router.post(
    "/income/{income_id}/void",
    response_model=IncomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Void an income record",
)
async def void_income(
    income_id: str,
    body: VoidLedgerEntryRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.income.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> IncomeResponse:
    dto = await service.void_income(
        VoidIncomeCommand(income_id=income_id, reason=body.reason, actor=principal), uow=uow
    )
    return _income_response(dto)


@school_finance_router.get(
    "/expenses",
    response_model=OffsetPageResponse[ExpenseResponse],
    status_code=status.HTTP_200_OK,
    summary="List organization expenses",
)
async def list_expenses(
    principal: Principal = Depends(
        require_permission(Permission("school_erp.expenses.list"))
    ),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[ExpenseResponse]:
    async with uow:
        page = await uow.expenses.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    from raad.modules.school_erp.application.queries import expense_to_dto

    return to_offset_page_response(page, lambda e: _expense_response(expense_to_dto(e)))


@school_finance_router.post(
    "/expenses",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an organization expense",
    description=(
        "Optionally attributed to one vehicle (`vehicle_id`), which is what makes per-bus cost "
        "reporting possible alongside per-bus revenue."
    ),
)
async def record_expense(
    body: RecordExpenseRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.expenses.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> ExpenseResponse:
    dto = await service.record_expense(
        RecordExpenseCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            category_id=body.category_id,
            amount=body.amount,
            currency=body.currency,
            occurred_on=body.occurred_on,
            description=body.description,
            reference=body.reference,
            vehicle_id=body.vehicle_id,
            actor=principal,
        ),
        uow=uow,
    )
    return _expense_response(dto)


@school_finance_router.post(
    "/expenses/{expense_id}/void",
    response_model=ExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Void an expense record",
)
async def void_expense(
    expense_id: str,
    body: VoidLedgerEntryRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.expenses.manage"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> ExpenseResponse:
    dto = await service.void_expense(
        VoidExpenseCommand(expense_id=expense_id, reason=body.reason, actor=principal),
        uow=uow,
    )
    return _expense_response(dto)


# ============================================================================================
# Read models / dashboards
# ============================================================================================


@school_finance_router.get(
    "/summary",
    response_model=FinanceSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Organization finance KPI summary",
    description=(
        "Billed, collected and outstanding across student invoices. Omit `period` for all-time "
        "(what an outstanding-balance view needs); supply `YYYY-MM` for one month."
    ),
)
async def get_finance_summary(
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    principal: Principal = Depends(
        require_permission(Permission("school_erp.reports.read"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> FinanceSummaryResponse:
    dto = await service.get_finance_summary(period=period, uow=uow)
    return FinanceSummaryResponse(**dto.__dict__)


@school_finance_router.get(
    "/vehicles",
    response_model=list[VehicleFinanceResponse],
    status_code=status.HTTP_200_OK,
    summary="Vehicle financial overview",
    description=(
        "Students, revenue, collections, outstanding balance and attributed cost per bus — one "
        "grouped query, not one per vehicle. A `vehicle_id` of `null` groups invoices issued "
        "before the student was assigned to a bus."
    ),
)
async def get_vehicle_financial_overview(
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    principal: Principal = Depends(
        require_permission(Permission("school_erp.reports.read"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> list[VehicleFinanceResponse]:
    dtos = await service.get_vehicle_financial_overview(period=period, uow=uow)
    return [VehicleFinanceResponse(**dto.__dict__) for dto in dtos]


@school_finance_router.get(
    "/vehicles/{vehicle_id}/invoices",
    response_model=list[StudentInvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="Student invoices for one bus (backs the printable bus report)",
)
async def list_vehicle_invoices(
    vehicle_id: str,
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    principal: Principal = Depends(
        require_permission(Permission("school_erp.reports.read"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> list[StudentInvoiceResponse]:
    dtos = await service.list_invoices_for_vehicle(
        vehicle_id=vehicle_id, period=period, uow=uow
    )
    return [_invoice_response(dto) for dto in dtos]


@school_finance_router.get(
    "/students/{student_id}/invoices",
    response_model=list[StudentInvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="One student's invoice history",
)
async def list_student_invoice_history(
    student_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.student_invoices.list"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> list[StudentInvoiceResponse]:
    dtos = await service.list_invoices_for_student(student_id=student_id, uow=uow)
    return [_invoice_response(dto) for dto in dtos]


@school_finance_router.get(
    "/profit-and-loss",
    response_model=ProfitAndLossResponse,
    status_code=status.HTTP_200_OK,
    summary="Profit & loss for a date range",
    description=(
        "Derived from actual recorded transactions only. Student revenue (collected payments) "
        "and other income are reported as separate lines so transport revenue stays "
        "distinguishable, and so a fee mistakenly recorded twice is visible rather than hidden."
    ),
)
async def get_profit_and_loss(
    start: date = Query(...),
    end: date = Query(...),
    principal: Principal = Depends(
        require_permission(Permission("school_erp.reports.read"))
    ),
    service: SchoolErpApplicationService = Depends(get_school_erp_service),
    uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> ProfitAndLossResponse:
    dto = await service.get_profit_and_loss(start=start, end=end, uow=uow)
    return ProfitAndLossResponse(**dto.__dict__)


# ==============================================================================================
# ParentBillingProfile / ParentInvoice — real aggregates (ADR-0042, 2026-09-11, supersedes
# ADR-0041 §1's grouped-read-model routes)
# ==============================================================================================
#
# New permission namespace (`school_erp.parent_billing_profiles.*`/`.parent_invoices.*`,
# `a9c73e5f0b8d`): `org_admin` gets list+manage (it is their school's own billing), RAAD staff get
# list-only, `parent` gets neither — the identical role split every other `school_erp.*`
# permission pair already uses. Both Units of Work are resolved explicitly on every route that
# needs a display name — `SchoolErpUnitOfWork` for this module's own aggregates,
# `TransportOpsUnitOfWork` (via `transport_ops.api.deps.get_transport_ops_uow`) purely to resolve
# parent/student names, mirroring every route in this file that predates ADR-0042.


def _parent_financial_summary_response(
    dto: ParentFinancialSummaryDTO,
) -> ParentFinancialSummaryResponse:
    # `dto.children` is a list of `ParentChildFinancialDTO` dataclass instances, not
    # `ParentChildFinancialResponse` — a renderer must coerce what a builder hands it (this
    # codebase's own Permanent Engineering Lesson), so each child is rebuilt explicitly rather
    # than trusting `**dto.__dict__` to already be the right shape one level down.
    return ParentFinancialSummaryResponse(
        **{
            **dto.__dict__,
            "children": [
                ParentChildFinancialResponse(**child.__dict__) for child in dto.children
            ],
        }
    )


@school_finance_router.get(
    "/parents/{parent_id}/summary",
    response_model=ParentFinancialSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="A parent's family-level financial summary across all their children",
)
async def get_parent_financial_summary(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.list"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentFinancialSummaryResponse:
    dto = await service.get_parent_financial_summary(
        parent_id, school_erp_uow=school_erp_uow, transport_ops_uow=transport_ops_uow
    )
    return _parent_financial_summary_response(dto)


# ---- ParentBillingProfile --------------------------------------------------------------------


def _billing_profile_response(dto: ParentBillingProfileDTO) -> ParentBillingProfileResponse:
    return ParentBillingProfileResponse(**dto.__dict__)


@school_finance_router.get(
    "/parents/{parent_id}/billing-profile",
    response_model=ParentBillingProfileResponse | None,
    status_code=status.HTTP_200_OK,
    summary="A parent's Billing Profile (the actual recurring transportation charge), if any",
)
async def get_parent_billing_profile(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_billing_profiles.list"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentBillingProfileResponse | None:
    dto = await service.get_billing_profile(
        parent_id, school_erp_uow=school_erp_uow, transport_ops_uow=transport_ops_uow
    )
    return _billing_profile_response(dto) if dto else None


@school_finance_router.put(
    "/parents/{parent_id}/billing-profile",
    response_model=ParentBillingProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update a parent's Billing Profile",
    description=(
        "The directive's Part 5 — the school types the family's actual monthly charge directly, "
        "no Fee Plan required. Creates the profile if the parent has none yet, otherwise edits "
        "the existing one in place; editing never rewrites an already-generated Parent Invoice, "
        "which froze its own amount at generation time."
    ),
)
async def put_parent_billing_profile(
    parent_id: str,
    body: CreateOrUpdateParentBillingProfileRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_billing_profiles.manage"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentBillingProfileResponse:
    organization_id = _resolve_organization_id(principal, body.organization_id)
    dto = await service.create_or_update_billing_profile(
        CreateOrUpdateParentBillingProfileCommand(
            organization_id=organization_id,
            parent_id=parent_id,
            monthly_fee=body.monthly_fee,
            currency=body.currency,
            billing_start_period=body.billing_start_period,
            due_day=body.due_day,
            actor=principal,
        ),
        school_erp_uow=school_erp_uow,
        transport_ops_uow=transport_ops_uow,
    )
    return _billing_profile_response(dto)


@school_finance_router.patch(
    "/parent-billing-profiles/{billing_profile_id}/status",
    response_model=ParentBillingProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate or deactivate a Billing Profile",
    description=(
        "Deactivating stops future monthly generation from picking this family up, without "
        "deleting the profile's own history of what it used to charge — the withdrawn-child/"
        "fee-waiver case."
    ),
)
async def set_parent_billing_profile_status(
    billing_profile_id: str,
    body: SetParentBillingProfileStatusRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_billing_profiles.manage"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
) -> ParentBillingProfileResponse:
    dto = await service.set_billing_profile_status(
        SetParentBillingProfileStatusCommand(
            billing_profile_id=billing_profile_id,
            is_active=body.is_active,
            actor=principal,
        ),
        school_erp_uow=school_erp_uow,
    )
    return _billing_profile_response(dto)


# ---- ParentInvoice -----------------------------------------------------------------------------


def _parent_invoice_summary_response(
    dto: ParentInvoiceSummaryDTO,
) -> ParentInvoiceSummaryResponse:
    return ParentInvoiceSummaryResponse(**dto.__dict__)


def _parent_invoice_detail_response(dto: ParentInvoiceDetailDTO) -> ParentInvoiceDetailResponse:
    return ParentInvoiceDetailResponse(
        **{
            **dto.__dict__,
            "lines": [ParentInvoiceLineResponse(**line.__dict__) for line in dto.lines],
        }
    )


@school_finance_router.post(
    "/parent-invoices/generate",
    response_model=list[ParentInvoiceDetailResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate this period's Parent Invoices for every active Billing Profile",
    description=(
        "The monthly billing run (the directive's Part 18). Idempotent: a parent already "
        "invoiced for the period is skipped, not double-charged, so re-running a partially-"
        "failed batch is safe."
    ),
)
async def generate_parent_invoices(
    body: GenerateParentInvoicesRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.manage"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[ParentInvoiceDetailResponse]:
    organization_id = _resolve_organization_id(principal, body.organization_id)
    dtos = await service.generate_parent_invoices(
        GenerateParentInvoicesCommand(
            organization_id=organization_id, period=body.period, actor=principal
        ),
        school_erp_uow=school_erp_uow,
        transport_ops_uow=transport_ops_uow,
    )
    return [_parent_invoice_detail_response(dto) for dto in dtos]


@school_finance_router.get(
    "/parent-invoices",
    response_model=OffsetPageResponse[ParentInvoiceSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="Every Parent Invoice in scope — the primary Finance page listing",
)
async def list_parent_invoices(
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(unpaid|partial|paid|cancelled)$"
    ),
    parent_id: str | None = Query(default=None),
    vehicle_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.list"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
) -> OffsetPageResponse[ParentInvoiceSummaryResponse]:
    page = await service.list_parent_invoices(
        page=page_request.page,
        page_size=page_request.page_size,
        period=period,
        status=status_filter,
        parent_id=parent_id,
        vehicle_id=vehicle_id,
        date_from=date_from,
        date_to=date_to,
        school_erp_uow=school_erp_uow,
        transport_ops_uow=transport_ops_uow,
    )
    return to_offset_page_response(page, _parent_invoice_summary_response)


@school_finance_router.get(
    "/parent-invoices/{invoice_id}",
    response_model=ParentInvoiceDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="One Parent Invoice's own child line items",
)
async def get_parent_invoice_detail(
    invoice_id: str,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.list"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentInvoiceDetailResponse:
    dto = await service.get_parent_invoice_detail(
        invoice_id, school_erp_uow=school_erp_uow, transport_ops_uow=transport_ops_uow
    )
    return _parent_invoice_detail_response(dto)


@school_finance_router.patch(
    "/parent-invoices/{invoice_id}/payment-status",
    response_model=ParentInvoiceSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Set a Parent Invoice's payment status: Unpaid / Partial / Paid",
    description=(
        "The entire user-facing payment workflow (the directive's Part 9) — no separate payment "
        "record, no payment method/reference/history. Recalculates amount paid, balance, "
        "Receivables and Collected on save; there is nothing further to reconcile."
    ),
)
async def set_parent_invoice_payment_status(
    invoice_id: str,
    body: SetParentInvoicePaymentStatusRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.manage"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentInvoiceSummaryResponse:
    dto = await service.set_parent_invoice_payment_status(
        SetParentInvoicePaymentStatusCommand(
            invoice_id=invoice_id,
            status=body.status,
            amount_paid=body.amount_paid,
            actor=principal,
        ),
        school_erp_uow=school_erp_uow,
        transport_ops_uow=transport_ops_uow,
    )
    return _parent_invoice_summary_response(dto)


@school_finance_router.post(
    "/parent-invoices/{invoice_id}/cancel",
    response_model=ParentInvoiceSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a Parent Invoice (e.g. issued in error)",
    description="Cannot cancel an invoice that has received payment — set it back to unpaid first.",
)
async def cancel_parent_invoice(
    invoice_id: str,
    body: CancelParentInvoiceRequest,
    principal: Principal = Depends(
        require_permission(Permission("school_erp.parent_invoices.manage"))
    ),
    service: ParentFinanceApplicationService = Depends(get_parent_finance_service),
    school_erp_uow: SchoolErpUnitOfWork = Depends(get_school_erp_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentInvoiceSummaryResponse:
    dto = await service.cancel_parent_invoice(
        CancelParentInvoiceCommand(
            invoice_id=invoice_id, reason=body.reason, actor=principal
        ),
        school_erp_uow=school_erp_uow,
        transport_ops_uow=transport_ops_uow,
    )
    return _parent_invoice_summary_response(dto)
