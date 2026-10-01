"""`/me/*` self-service routes for the mobile app (ADR-0061).

Self-scoped like ADR-0023's `/me` routes: `Depends(get_current_user)` only, no permission, and
no parameter that names a parent, driver, staff member or student. The one path id a route
takes (`trip_id`, an unavailability id) is checked for ownership in the service and answers
404 when it is someone else's.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from raad.core.di.container import Container
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import get_container, get_current_user
from raad.modules.transport_ops.api.deps import get_transport_ops_uow
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.self_service import SelfServiceApplicationService

me_transport_router = APIRouter()


def get_self_service(container: Container = Depends(get_container)) -> SelfServiceApplicationService:
    return container.resolve(SelfServiceApplicationService)


# ---- wire shapes ------------------------------------------------------------------------------


class MyVehicleResponse(BaseModel):
    id: str
    plate_no: str
    label: str | None = None


class MyTripStudentResponse(BaseModel):
    student_id: str
    full_name: str


class MyTripResponse(BaseModel):
    id: str
    trip_type: str
    status: str
    scheduled_date: date
    planned_departure: time | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    cancelled_reason: str | None = None
    route_id: str
    route_name: str | None = None
    vehicle: MyVehicleResponse | None = None
    is_cover: bool = False
    students: list[MyTripStudentResponse] = Field(default_factory=list)


class MyStopResponse(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    sequence_no: int


class MyCrewMemberResponse(BaseModel):
    full_name: str
    role_name: str | None = None
    is_me: bool
    is_substitute: bool


class MyPassengerResponse(BaseModel):
    student_id: str
    full_name: str
    pickup_stop_name: str | None = None
    dropoff_stop_name: str | None = None


class MyTripDetailResponse(BaseModel):
    trip: MyTripResponse
    stops: list[MyStopResponse]
    crew: list[MyCrewMemberResponse]
    passengers: list[MyPassengerResponse]


class MyCrewResponse(BaseModel):
    vehicle: MyVehicleResponse
    members: list[MyCrewMemberResponse]


class MyDocumentResponse(BaseModel):
    id: str
    type_name: str
    number: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    status: str
    days_left: int | None = None


class MyComplianceGapResponse(BaseModel):
    type_name: str
    reason: str
    expired_on: date | None = None
    blocks: bool


class MyComplianceExpiringResponse(BaseModel):
    type_name: str
    expires_on: date


class MyComplianceResponse(BaseModel):
    status: str
    is_blocked: bool
    gaps: list[MyComplianceGapResponse]
    expiring: list[MyComplianceExpiringResponse]


class MyDocumentsResponse(BaseModel):
    documents: list[MyDocumentResponse]
    compliance: MyComplianceResponse | None = None


class MyUnavailabilityResponse(BaseModel):
    id: str
    starts_on: date
    ends_on: date
    reason: str
    note: str | None = None
    is_withdrawn: bool
    is_covered: bool


class ReportUnavailabilityRequest(BaseModel):
    starts_on: date
    ends_on: date
    reason: Literal["sick", "personal", "training", "other"]
    note: str | None = Field(default=None, max_length=500)


class MyIncidentResponse(BaseModel):
    id: str
    category: str
    severity: str
    status: str
    occurred_at: datetime
    title: str
    description: str | None = None
    trip_id: str | None = None
    created_at: datetime
    closed_at: datetime | None = None


class ReportIncidentRequest(BaseModel):
    category: Literal[
        "accident",
        "breakdown",
        "medical",
        "behaviour",
        "near_miss",
        "delay",
        "student_left_behind",
        "other",
    ]
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    occurred_at: datetime | None = None
    trip_id: str | None = None


# ---- trips ------------------------------------------------------------------------------------


@me_transport_router.get(
    "/trips",
    response_model=list[MyTripResponse],
    summary="The caller's own trips (driver) or their children's trips (parent)",
    description=(
        "ADR-0061. Driver: trips they drive, default today to 7 days ahead. Parent: trips on "
        "each child's assigned bus and route, default 30 days back to 7 days ahead, each with "
        "the caller's own children who ride it. 404 for any other role."
    ),
)
async def list_my_trips(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[MyTripResponse]:
    trips = await service.my_trips(principal, start=from_, end=to, uow=uow)
    return [MyTripResponse.model_validate(asdict(t)) for t in trips]


@me_transport_router.get(
    "/trips/{trip_id}",
    response_model=MyTripDetailResponse,
    summary="One of the calling driver's own trips: stops, crew and passengers",
    description="ADR-0061. 404 when the trip is not the caller's own.",
)
async def get_my_trip(
    trip_id: str,
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> MyTripDetailResponse:
    detail = await service.my_trip_detail(principal, trip_id, uow=uow)
    return MyTripDetailResponse.model_validate(asdict(detail))


# ---- crew, documents --------------------------------------------------------------------------


@me_transport_router.get(
    "/crew",
    response_model=list[MyCrewResponse],
    summary="Who works on the calling driver's buses on a day",
)
async def list_my_crew(
    day: date | None = Query(default=None, alias="date"),
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[MyCrewResponse]:
    crews = await service.my_crew(principal, day=day, uow=uow)
    return [MyCrewResponse.model_validate(asdict(c)) for c in crews]


@me_transport_router.get(
    "/documents",
    response_model=MyDocumentsResponse,
    summary="The calling driver's own documents and compliance status",
)
async def get_my_documents(
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> MyDocumentsResponse:
    result = await service.my_documents(principal, uow=uow)
    return MyDocumentsResponse.model_validate(asdict(result))


# ---- unavailability ---------------------------------------------------------------------------


@me_transport_router.get(
    "/unavailability",
    response_model=list[MyUnavailabilityResponse],
    summary="The calling driver's own recorded unavailability",
)
async def list_my_unavailability(
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[MyUnavailabilityResponse]:
    items = await service.my_unavailability(principal, uow=uow)
    return [MyUnavailabilityResponse.model_validate(asdict(i)) for i in items]


@me_transport_router.post(
    "/unavailability",
    response_model=MyUnavailabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report the calling driver's own unavailability",
    description=(
        "ADR-0061/ADR-0053: a stated fact, not a request. Nothing is reassigned; the daily "
        "board shows the gap and the office is told."
    ),
)
async def report_my_unavailability(
    body: ReportUnavailabilityRequest,
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> MyUnavailabilityResponse:
    item = await service.report_unavailability(
        principal,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        reason=body.reason,
        note=body.note,
        uow=uow,
    )
    return MyUnavailabilityResponse.model_validate(asdict(item))


@me_transport_router.delete(
    "/unavailability/{unavailability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw the calling driver's own unavailability",
    description="409 once a substitute has been arranged. 404 when it is not the caller's own.",
)
async def withdraw_my_unavailability(
    unavailability_id: str,
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> Response:
    await service.withdraw_my_unavailability(principal, unavailability_id, uow=uow)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- incidents --------------------------------------------------------------------------------


@me_transport_router.get(
    "/incidents",
    response_model=list[MyIncidentResponse],
    summary="The incidents the calling driver reported, and their status",
)
async def list_my_incidents(
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[MyIncidentResponse]:
    incidents = await service.my_incidents(principal, uow=uow)
    return [MyIncidentResponse.model_validate(asdict(i)) for i in incidents]


@me_transport_router.post(
    "/incidents",
    response_model=MyIncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report an incident as the calling driver",
    description="ADR-0061. A named trip must be the caller's own (404 otherwise).",
)
async def report_my_incident(
    body: ReportIncidentRequest,
    principal: Principal = Depends(get_current_user),
    service: SelfServiceApplicationService = Depends(get_self_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> MyIncidentResponse:
    incident = await service.report_incident(
        principal,
        category=body.category,
        severity=body.severity,
        occurred_at=body.occurred_at,
        title=body.title,
        description=body.description,
        trip_id=body.trip_id,
        uow=uow,
    )
    return MyIncidentResponse.model_validate(asdict(incident))


__all__ = ["me_transport_router"]
