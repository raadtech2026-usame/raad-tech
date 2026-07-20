"""Notification event subscribers (Backend LLD §11.2's "Notification Worker" row: "subscribe
to domain events... trip-lifecycle/geofence event -> notification service"; Database Design
§7.5's D1 notification catalog). `core.events.processor.EventProcessorRegistry`'s own module
docstring names this exact shape: "a future `TripStartedNotifier` is owned by
`modules/notifications` and registers itself" — this file is that registration.

**Architecture Resolution (Backend Stabilization phase, Medium finding #6 of the pre-production
review: "Notification/Report Workers are empty files").** Four `EventProcessor`s, one per D1
transport `NotificationType` with a clear, already-shipped, 1:1 source event
(`trip_started`<-`TripStarted`, `trip_completed`<-`TripEnded`, `approaching_stop`<-
`VehicleApproachingStop`, `arrived_org`<-`VehicleArrivedAtOrganization`). **`subscription`/
`system` notification types are deliberately not auto-triggered from any event this phase** — no
approved document names which billing/system event(s) should produce one (unlike the four
transport types, which the D1 catalog and the already-shipped `Trip`/`GeofenceCrossing` events
line up unambiguously); inventing a mapping would be a new, undocumented business rule. Both
types remain reachable via `NotificationApplicationService.create_notification` for direct/manual
use, unaffected by this file.

**Recipient resolution and CR-1 gating happen here, not in `domain/policies.py`** — exactly the
deferral that module's own docstring names: *"the withholding decision belongs to the not-yet-
built Notification Worker."* For a given `vehicle_id`, this resolves every `StudentAssignment`
currently `active` for that vehicle (`transport_ops.StudentAssignmentApplicationService.
list_student_assignments`, filtered client-side — no new `transport_ops` repository method is
added; `transport_ops` is a stable, already-shipped bounded context and this phase's own "prefer
minimal changes" constraint applies), then every parent linked to each such student
(`StudentParentApplicationService.list_parents_for_student` + `ParentApplicationService.
get_parent_by_id` for `user_id`), then evaluates `SubscriptionAccessPolicy` (CR-1) per parent
before calling `NotificationApplicationService.create_notification` — the same policy, same
`AssignmentState`/`BillingModel`/`SubscriptionState` inputs `interfaces/http/policy_guards.
resolve_cr1_decision` already uses for the HTTP-facing tracking/video routes, applied here in a
worker context instead. `assignment_state` is always `ACTIVE` by construction (the vehicle-scoped
assignment list is already filtered to `active`), so only `subscription_state` (for
`PARENT_PAYS` organizations) can still deny — **no `safety_override`**: D4's live-GPS exception
(ADR-0006) is specific to live position during an active trip, not notifications, so a lapsed
`PARENT_PAYS` parent's subscription-gated notifications are correctly withheld exactly like any
other CR-1-gated read, matching `flutter.md` #4's framing that only *live GPS* gets the safety
carve-out.

**`SYSTEM_PRINCIPAL` — a real, flagged gap, not a silent invention.** Every application command
in this codebase requires `actor: Principal` (including `CreateNotificationCommand`), but no
approved document defines a system/worker actor concept, and `core.tenancy.principal.Role` has
no `SYSTEM` value among its seven documented roles (Project Brief Ch. 4). Adding an eighth role
would touch the RBAC seed matrix (ADR-0004), `ScopeResolver` (ADR-0005), and every policy that
switches on `Role` — a far larger, riskier change than this phase's own "prefer minimal changes"
instruction allows for a single worker's actor field. `Principal(user_id="system", role=Role.
FOUNDER, org_id=None)` is used instead — Founder is the closest existing role conceptually
(unrestricted scope, matching what a background system process needs), not a claim that the
worker "is" a Founder user; `audit_entries.actor_user_id` will read `"system"` for these rows,
distinguishable from any real user id. Flagged here for a future ADR if a real `SYSTEM` role is
ever formally adopted.
"""

from __future__ import annotations

from typing import Any

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.processor import EventProcessor, EventProcessorRegistry
from raad.core.policies.subscription_access import (
    AssignmentState,
    BillingModel,
    SubscriptionAccessPolicy,
    SubscriptionState,
)
from raad.core.tenancy.principal import Principal, Role
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.notifications.application.commands import CreateNotificationCommand
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import GetOrganizationByIdQuery
from raad.modules.organization.application.services import OrganizationApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetParentByIdQuery,
    GetTripByIdQuery,
    ListParentsForStudentQuery,
    ListStudentAssignmentsQuery,
)
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)

SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)


class _NotificationFanOut:
    """Shared recipient-resolution + CR-1-gating + dispatch logic for every D1 transport
    `EventProcessor` below. Resolves every dependency fresh from the DI `Container` per call —
    the same pattern `interfaces/http/policy_guards.py` already establishes for orchestrating
    multiple modules' own application services without a cross-module DB read."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def notify_vehicle_watchers(
        self,
        *,
        vehicle_id: str,
        organization_id: str,
        type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None,
        trip_id: str | None,
    ) -> None:
        assignment_service = self._container.resolve(StudentAssignmentApplicationService)
        assignments = await assignment_service.list_student_assignments(
            ListStudentAssignmentsQuery(),
            uow=self._container.resolve(TransportOpsUnitOfWork),
        )
        active_student_ids = {
            a.student_id
            for a in assignments
            if a.status == "active" and a.vehicle_id == vehicle_id
        }
        if not active_student_ids:
            return

        billing_model = await self._resolve_billing_model(organization_id)

        student_parent_service = self._container.resolve(StudentParentApplicationService)
        parent_service = self._container.resolve(ParentApplicationService)
        notification_service = self._container.resolve(NotificationApplicationService)

        notified_user_ids: set[str] = set()
        for student_id in active_student_ids:
            links = await student_parent_service.list_parents_for_student(
                ListParentsForStudentQuery(student_id=student_id),
                uow=self._container.resolve(TransportOpsUnitOfWork),
            )
            for link in links:
                parent = await parent_service.get_parent_by_id(
                    GetParentByIdQuery(parent_id=link.parent_id),
                    uow=self._container.resolve(TransportOpsUnitOfWork),
                )
                if parent.user_id in notified_user_ids:
                    continue
                if not await self._is_cr1_granted(
                    parent_id=link.parent_id, billing_model=billing_model
                ):
                    continue
                notified_user_ids.add(parent.user_id)
                await notification_service.create_notification(
                    CreateNotificationCommand(
                        organization_id=organization_id,
                        recipient_user_id=parent.user_id,
                        type=type,
                        title=title,
                        body=body,
                        data=data,
                        trip_id=trip_id,
                        actor=SYSTEM_PRINCIPAL,
                    ),
                    uow=self._container.resolve(NotificationsUnitOfWork),
                )

    async def resolve_vehicle_id_for_trip(self, trip_id: str) -> str:
        trip_service = self._container.resolve(TripApplicationService)
        trip = await trip_service.get_trip_by_id(
            GetTripByIdQuery(trip_id=trip_id),
            uow=self._container.resolve(TransportOpsUnitOfWork),
        )
        return trip.vehicle_id

    async def _resolve_billing_model(self, organization_id: str) -> BillingModel:
        organization_service = self._container.resolve(OrganizationApplicationService)
        organization = await organization_service.get_organization_by_id(
            GetOrganizationByIdQuery(organization_id=organization_id),
            uow=self._container.resolve(OrganizationUnitOfWork),
        )
        return BillingModel(organization.billing_model)

    async def _is_cr1_granted(self, *, parent_id: str, billing_model: BillingModel) -> bool:
        if billing_model != BillingModel.PARENT_PAYS:
            return True
        billing_service = self._container.resolve(BillingApplicationService)
        subscription = await billing_service.get_active_subscription_for_subscriber(
            "parent", parent_id, uow=self._container.resolve(BillingUnitOfWork)
        )
        subscription_state = (
            SubscriptionState(subscription.status) if subscription is not None else None
        )
        decision = SubscriptionAccessPolicy().evaluate(
            assignment_state=AssignmentState.ACTIVE,
            billing_model=billing_model,
            subscription_state=subscription_state,
        )
        return decision.allowed


class TripStartedNotifier(EventProcessor):
    event_type = "TripStarted"

    def __init__(self, fan_out: _NotificationFanOut) -> None:
        self._fan_out = fan_out

    async def process(self, event: DomainEvent) -> None:
        vehicle_id = event.payload["vehicle_id"]
        await self._fan_out.notify_vehicle_watchers(
            vehicle_id=vehicle_id,
            organization_id=event.org_id,
            type="trip_started",
            title="Trip started",
            body="Your child's bus trip has started.",
            data={"trip_id": event.aggregate_id, "vehicle_id": vehicle_id},
            trip_id=event.aggregate_id,
        )


class TripEndedNotifier(EventProcessor):
    event_type = "TripEnded"

    def __init__(self, fan_out: _NotificationFanOut) -> None:
        self._fan_out = fan_out

    async def process(self, event: DomainEvent) -> None:
        vehicle_id = event.payload["vehicle_id"]
        await self._fan_out.notify_vehicle_watchers(
            vehicle_id=vehicle_id,
            organization_id=event.org_id,
            type="trip_completed",
            title="Trip completed",
            body="Your child's bus trip has ended.",
            data={"trip_id": event.aggregate_id, "vehicle_id": vehicle_id},
            trip_id=event.aggregate_id,
        )


class VehicleApproachingStopNotifier(EventProcessor):
    event_type = "VehicleApproachingStop"

    def __init__(self, fan_out: _NotificationFanOut) -> None:
        self._fan_out = fan_out

    async def process(self, event: DomainEvent) -> None:
        trip_id = event.payload["trip_id"]
        vehicle_id = await self._fan_out.resolve_vehicle_id_for_trip(trip_id)
        await self._fan_out.notify_vehicle_watchers(
            vehicle_id=vehicle_id,
            organization_id=event.org_id,
            type="approaching_stop",
            title="Approaching stop",
            body="Your child's bus is approaching the stop.",
            data={"trip_id": trip_id, "stop_id": event.payload["stop_id"]},
            trip_id=trip_id,
        )


class VehicleArrivedAtOrganizationNotifier(EventProcessor):
    event_type = "VehicleArrivedAtOrganization"

    def __init__(self, fan_out: _NotificationFanOut) -> None:
        self._fan_out = fan_out

    async def process(self, event: DomainEvent) -> None:
        trip_id = event.payload["trip_id"]
        vehicle_id = await self._fan_out.resolve_vehicle_id_for_trip(trip_id)
        await self._fan_out.notify_vehicle_watchers(
            vehicle_id=vehicle_id,
            organization_id=event.org_id,
            type="arrived_org",
            title="Arrived",
            body="Your child's bus has arrived.",
            data={"trip_id": trip_id},
            trip_id=trip_id,
        )


def register_notification_processors(
    registry: EventProcessorRegistry, container: Container
) -> None:
    """Called once from `interfaces/workers/bootstrap.py` when wiring the Notification Worker.
    Kept as a plain function (not a class) since registration is a one-time, order-independent
    side effect — no state of its own beyond what `EventProcessorRegistry` already holds."""
    fan_out = _NotificationFanOut(container)
    registry.register(TripStartedNotifier(fan_out))
    registry.register(TripEndedNotifier(fan_out))
    registry.register(VehicleApproachingStopNotifier(fan_out))
    registry.register(VehicleArrivedAtOrganizationNotifier(fan_out))
