"""Scheduled jobs for daily transport operations (ADR-0052 §4, ADR-0053 §5).

Both compose several modules' application services, so they live in the interfaces layer:
`transport_ops` decides what is due, `iam` names the active Org Admins, and `notifications`
writes the in-app messages.

* `generate_trips_for_all_organizations` runs the same generation plan as the manual button, on
  an unscoped Unit of Work, so every organization's timetable is covered.
* `notify_uncovered_trips` announces each uncovered trip once per cause, and at the configured
  hour sends each affected organization one summary for the day. A trip is marked only after its
  notifications were written, so a crash in between re-sends rather than loses an alert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import SYSTEM_PRINCIPAL
from raad.interfaces.workers.staff_document_alerts import active_org_admin_ids
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.notifications.application.commands import CreateNotificationCommand
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.transport_ops.application.commands import GenerateTripsCommand
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GenerationResultDTO,
    UncoveredTripAlertDTO,
)

logger = get_logger("raad.workers.daily_operations")

NOTIFICATION_TYPE = "system"

_REASON_TEXT = {
    "driver_unavailable": "its driver is unavailable",
    "driver_inactive": "its driver's access is inactive",
    "driver_not_active": "its driver is no longer active staff",
}


async def generate_trips_for_all_organizations(
    *,
    days: int,
    service: DailyOperationsApplicationService,
    uow: TransportOpsUnitOfWork,
) -> GenerationResultDTO:
    result = await service.generate_trips(
        GenerateTripsCommand(actor=SYSTEM_PRINCIPAL, days=days), uow=uow
    )
    if result.skipped:
        logger.warning(
            "trip_generation_skipped_entries",
            extra={
                "count": len(result.skipped),
                "reasons": sorted({s.reason for s in result.skipped}),
            },
        )
    return result


def uncovered_alert_text(alert: UncoveredTripAlertDTO) -> tuple[str, str]:
    period = "Morning" if alert.trip_type == "morning" else "Afternoon"
    title = f"{period} trip on {alert.scheduled_date.isoformat()} is uncovered"
    route = f" on {alert.route_name}" if alert.route_name else ""
    driver = f" ({alert.driver_name})" if alert.driver_name else ""
    reason = _REASON_TEXT.get(alert.reason, alert.reason)
    body = (
        f"The {period.lower()} trip{route} on {alert.scheduled_date.isoformat()} has no driver "
        f"who can drive it: {reason}{driver}. Name a substitute on the Daily Operations board."
    )
    return title, body


async def notify_uncovered_trips(
    *,
    now: datetime,
    summary_hour_utc: int,
    service: DailyOperationsApplicationService,
    user_service: UserApplicationService,
    notification_service: NotificationApplicationService,
    transport_ops_uow: Callable[[], TransportOpsUnitOfWork],
    iam_uow: Callable[[], IamUnitOfWork],
    notifications_uow: Callable[[], NotificationsUnitOfWork],
) -> int:
    """Returns how many trips were announced (the summary is not counted)."""
    admins_by_org: dict[str, list[str]] = {}

    async def admins(organization_id: str) -> list[str]:
        if organization_id not in admins_by_org:
            admins_by_org[organization_id] = await active_org_admin_ids(
                organization_id, user_service=user_service, iam_uow=iam_uow
            )
        return admins_by_org[organization_id]

    async def send(organization_id: str, title: str, body: str, data: dict, trip_id: str | None) -> bool:
        recipients = await admins(organization_id)
        for user_id in recipients:
            await notification_service.create_notification(
                CreateNotificationCommand(
                    organization_id=organization_id,
                    recipient_user_id=user_id,
                    type=NOTIFICATION_TYPE,
                    title=title,
                    body=body,
                    data=data,
                    trip_id=trip_id,
                    actor=SYSTEM_PRINCIPAL,
                ),
                uow=notifications_uow(),
            )
        return bool(recipients)

    alerts = await service.collect_uncovered_alerts(uow=transport_ops_uow())
    announced = 0
    for alert in alerts:
        title, body = uncovered_alert_text(alert)
        data = {
            "kind": "trip_uncovered",
            "trip_id": alert.trip_id,
            "scheduled_date": alert.scheduled_date.isoformat(),
            "trip_type": alert.trip_type,
            "vehicle_id": alert.vehicle_id,
            "reason": alert.reason,
        }
        if await send(alert.organization_id, title, body, data, alert.trip_id):
            await service.mark_uncovered_alerted(alert.trip_id, alert.key, uow=transport_ops_uow())
            announced += 1
        else:
            logger.info(
                "uncovered_trip_alert_no_recipient",
                extra={"organization_id": alert.organization_id, "trip_id": alert.trip_id},
            )

    if now.hour == summary_hour_utc:
        counts = await service.uncovered_today(uow=transport_ops_uow())
        for organization_id, count in sorted(counts.items()):
            await send(
                organization_id,
                f"{count} trip{'s' if count != 1 else ''} uncovered today",
                f"{count} of today's trips {'have' if count != 1 else 'has'} no driver who can "
                "drive. Open the Daily Operations board to name substitutes.",
                {"kind": "trips_uncovered_summary", "date": now.date().isoformat(), "count": count},
                None,
            )
    return announced


__all__ = [
    "generate_trips_for_all_organizations",
    "notify_uncovered_trips",
    "uncovered_alert_text",
]
