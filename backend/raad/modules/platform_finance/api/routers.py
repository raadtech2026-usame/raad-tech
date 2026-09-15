"""HTTP routes for `platform_finance` (ADR-0040 §1), mounted at `/api/v1/platform-finance`.

**RBAC is the only gate on this data.** These tables carry no `organization_id`, so there is no
tenant scope to fall back on — `founder` and `finance_staff` are the only roles granted anything
in the `platform_finance.*` namespace, and no `org_admin` grant exists at all (ADR-0040 §7).
That is deliberate: this is RAAD's own P&L, and an organization must never be able to read it.

None of these routes appears in API Contracts §4.7 — added under ADR-0040 and cited here rather
than silently, the same posture every post-Phase-3.3 route in this codebase carries.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import (
    get_container,
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.core.di.container import Container
from raad.modules.platform_finance.application.ports import PlatformFinanceUnitOfWork
from raad.modules.platform_finance.application.services import (
    PlatformFinanceApplicationService,
    _expense_dto,
    _income_dto,
)

platform_finance_router = APIRouter()


def get_platform_finance_uow(
    container: Container = Depends(get_container),
) -> PlatformFinanceUnitOfWork:
    """No `Depends(get_scope)` — unlike every tenant-owned module's UoW dependency.

    These tables have no `organization_id`, so a `TenantRegionScope` would be inert
    (`SqlAlchemyRepositoryBase._apply_scope` guards on `hasattr`). Resolving one anyway would
    imply a tenant filter that does not exist; leaving it out states plainly that RBAC is the
    control here.
    """
    return container.resolve(PlatformFinanceUnitOfWork)


def get_platform_finance_service(
    container: Container = Depends(get_container),
) -> PlatformFinanceApplicationService:
    return container.resolve(PlatformFinanceApplicationService)


# ---- Schemas -------------------------------------------------------------------------------


class CreatePlatformCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern="^(income|expense)$")
    description: str | None = Field(default=None, max_length=500)


class PlatformCategoryResponse(BaseModel):
    id: str
    name: str
    kind: str
    description: str | None
    status: str


class RecordPlatformExpenseRequest(BaseModel):
    kind: str = Field(
        pattern=(
            "^(salaries|rent|electricity|water|internet|equipment|maintenance|fuel|marketing|"
            "travel|software|professional_fees|taxes|other)$"
        )
    )
    category_id: str | None = None
    amount: str = Field(examples=["1200.00"])
    currency: str = Field(min_length=3, max_length=3)
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)
    vendor: str | None = Field(default=None, max_length=160)
    reference: str | None = Field(default=None, max_length=120)


class RecordPlatformIncomeRequest(BaseModel):
    kind: str = Field(
        pattern="^(hardware_sale|installation|support_contract|grant|other)$",
        description=(
            "`subscription` is deliberately not accepted — subscription revenue is owned by the "
            "billing module and is read from there, so recording it here would double-count it."
        ),
    )
    category_id: str | None = None
    amount: str = Field(examples=["450.00"])
    currency: str = Field(min_length=3, max_length=3)
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=160)
    reference: str | None = Field(default=None, max_length=120)


class VoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class PlatformExpenseResponse(BaseModel):
    id: str
    kind: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    vendor: str | None
    reference: str | None
    attachment_url: str | None
    is_voided: bool


class PlatformIncomeResponse(BaseModel):
    id: str
    kind: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    source: str | None
    reference: str | None
    is_voided: bool


class PlatformPnlResponse(BaseModel):
    start: date
    end: date
    subscription_revenue: str
    #: Amount billed to organizations in this window, regardless of whether paid yet.
    subscription_invoiced: str
    #: Amount still owed as of `end` — a point-in-time balance, not a period sum.
    subscription_receivables: str
    other_income: str
    total_revenue: str
    total_expenses: str
    net_profit: str
    expenses_by_kind: dict[str, str]
    income_by_kind: dict[str, str]
    currency: str


# ---- Routes --------------------------------------------------------------------------------


@platform_finance_router.get(
    "/categories",
    response_model=list[PlatformCategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List platform financial categories",
)
async def list_categories(
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.categories.list"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> list[PlatformCategoryResponse]:
    dtos = await service.list_categories(uow=uow)
    return [PlatformCategoryResponse(**dto.__dict__) for dto in dtos]


@platform_finance_router.post(
    "/categories",
    response_model=PlatformCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a platform financial category",
)
async def create_category(
    body: CreatePlatformCategoryRequest,
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.categories.manage"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformCategoryResponse:
    dto = await service.create_category(
        name=body.name,
        kind=body.kind,
        description=body.description,
        actor=principal,
        uow=uow,
    )
    return PlatformCategoryResponse(**dto.__dict__)


@platform_finance_router.get(
    "/expenses",
    response_model=OffsetPageResponse[PlatformExpenseResponse],
    status_code=status.HTTP_200_OK,
    summary="List RAAD operating expenses",
)
async def list_expenses(
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.expenses.list"))
    ),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[PlatformExpenseResponse]:
    async with uow:
        page = await uow.expenses.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    return to_offset_page_response(
        page, lambda e: PlatformExpenseResponse(**_expense_dto(e).__dict__)
    )


@platform_finance_router.post(
    "/expenses",
    response_model=PlatformExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a RAAD operating expense",
)
async def record_expense(
    body: RecordPlatformExpenseRequest,
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.expenses.manage"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformExpenseResponse:
    dto = await service.record_expense(
        kind=body.kind,
        category_id=body.category_id,
        amount=body.amount,
        currency=body.currency,
        occurred_on=body.occurred_on,
        description=body.description,
        vendor=body.vendor,
        reference=body.reference,
        actor=principal,
        uow=uow,
    )
    return PlatformExpenseResponse(**dto.__dict__)


@platform_finance_router.post(
    "/expenses/{expense_id}/void",
    response_model=PlatformExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Void a platform expense",
)
async def void_expense(
    expense_id: str,
    body: VoidRequest,
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.expenses.manage"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformExpenseResponse:
    dto = await service.void_expense(
        expense_id=expense_id, reason=body.reason, actor=principal, uow=uow
    )
    return PlatformExpenseResponse(**dto.__dict__)


@platform_finance_router.get(
    "/income",
    response_model=OffsetPageResponse[PlatformIncomeResponse],
    status_code=status.HTTP_200_OK,
    summary="List non-subscription platform income",
)
async def list_income(
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.income.list"))
    ),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[PlatformIncomeResponse]:
    async with uow:
        page = await uow.income.list_page(
            page_request, filters=filters, sort=sort, search=search
        )
    return to_offset_page_response(
        page, lambda i: PlatformIncomeResponse(**_income_dto(i).__dict__)
    )


@platform_finance_router.post(
    "/income",
    response_model=PlatformIncomeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record non-subscription platform income",
)
async def record_income(
    body: RecordPlatformIncomeRequest,
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.income.manage"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformIncomeResponse:
    dto = await service.record_income(
        kind=body.kind,
        category_id=body.category_id,
        amount=body.amount,
        currency=body.currency,
        occurred_on=body.occurred_on,
        description=body.description,
        source=body.source,
        reference=body.reference,
        actor=principal,
        uow=uow,
    )
    return PlatformIncomeResponse(**dto.__dict__)


@platform_finance_router.post(
    "/income/{income_id}/void",
    response_model=PlatformIncomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Void a platform income record",
)
async def void_income(
    income_id: str,
    body: VoidRequest,
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.income.manage"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformIncomeResponse:
    dto = await service.void_income(
        income_id=income_id, reason=body.reason, actor=principal, uow=uow
    )
    return PlatformIncomeResponse(**dto.__dict__)


@platform_finance_router.get(
    "/profit-and-loss",
    response_model=PlatformPnlResponse,
    status_code=status.HTTP_200_OK,
    summary="RAAD platform profit & loss",
    description=(
        "Subscription revenue is read from the billing module (collected payments in the "
        "window) and reported as its own line beside non-subscription income — never merged, so "
        "the same payment can never be counted twice."
    ),
)
async def get_platform_pnl(
    start: date = Query(...),
    end: date = Query(...),
    principal: Principal = Depends(
        require_permission(Permission("platform_finance.reports.read"))
    ),
    service: PlatformFinanceApplicationService = Depends(get_platform_finance_service),
    uow: PlatformFinanceUnitOfWork = Depends(get_platform_finance_uow),
) -> PlatformPnlResponse:
    dto = await service.get_platform_pnl(start=start, end=end, uow=uow)
    return PlatformPnlResponse(**dto.__dict__)
