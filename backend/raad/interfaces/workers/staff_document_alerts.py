"""Staff document expiry alerts (ADR-0051 §3).

Composes three modules' application services, which is why it lives in the interfaces layer and
not in any one of them: `transport_ops` says which alerts are due, `iam` says who the
organization's active Org Admins are, and `notifications` writes one in-app notification per
admin per alert.

**Each threshold is sent once.** A document is marked only after its notifications were
written, in a separate transaction; a crash between the two re-sends that alert on the next run
rather than losing it. An organization with no active Org Admin has nobody to tell, so its
alerts stay unmarked and are sent once an admin exists; the dashboard card shows them
meanwhile.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Callable

from raad.core.logging.setup import get_logger
from raad.core.pagination import MAX_PAGE_SIZE, FilterCondition, OffsetPageRequest
from raad.core.tenancy.principal import SYSTEM_PRINCIPAL
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import ListUsersQuery
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.notifications.application.commands import CreateNotificationCommand
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import DueExpiryAlertDTO
from raad.modules.transport_ops.application.staff_services import (
    TransportStaffApplicationService,
)

logger = get_logger("raad.workers.staff_document_alerts")

#: `system` is an existing `NotificationType`; no enum change was needed (ADR-0051 §3).
NOTIFICATION_TYPE = "system"
NOTIFICATION_KIND = "staff_document_expiry"


def alert_text(alert: DueExpiryAlertDTO, today: date) -> tuple[str, str]:
    """Title and body. Worded from the actual days left, not the threshold, so a document
    found late reads "has expired", not "expires in 30 days"."""
    days_left = (alert.expires_on - today).days
    if days_left < 0:
        when = "has expired"
    elif days_left == 0:
        when = "expires today"
    elif days_left == 1:
        when = "expires tomorrow"
    else:
        when = f"expires in {days_left} days"
    title = f"{alert.type_name} {when}"
    body = (
        f"{alert.staff_name}'s {alert.type_name} {when} "
        f"({alert.expires_on.isoformat()}). Record the renewal on their staff profile."
    )
    return title, body


async def _active_org_admin_ids(
    organization_id: str,
    *,
    user_service: UserApplicationService,
    iam_uow: Callable[[], IamUnitOfWork],
) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        result = await user_service.list_users(
            ListUsersQuery(
                page_request=OffsetPageRequest(page=page, page_size=MAX_PAGE_SIZE),
                filters=[
                    FilterCondition(field="organization_id", op="eq", value=organization_id),
                    FilterCondition(field="role", op="eq", value="org_admin"),
                    FilterCondition(field="status", op="eq", value="active"),
                ],
            ),
            uow=iam_uow(),
        )
        ids.extend(user.id for user in result.data)
        if page * MAX_PAGE_SIZE >= result.total:
            return ids
        page += 1


async def notify_expiring_staff_documents(
    *,
    today: date,
    staff_service: TransportStaffApplicationService,
    user_service: UserApplicationService,
    notification_service: NotificationApplicationService,
    transport_ops_uow: Callable[[], TransportOpsUnitOfWork],
    iam_uow: Callable[[], IamUnitOfWork],
    notifications_uow: Callable[[], NotificationsUnitOfWork],
) -> int:
    """Sends every alert due today; returns how many documents were alerted."""
    alerts = await staff_service.collect_due_expiry_alerts(uow=transport_ops_uow())
    by_organization: dict[str, list[DueExpiryAlertDTO]] = defaultdict(list)
    for alert in alerts:
        by_organization[alert.organization_id].append(alert)

    sent = 0
    for organization_id, organization_alerts in by_organization.items():
        admins = await _active_org_admin_ids(
            organization_id, user_service=user_service, iam_uow=iam_uow
        )
        if not admins:
            logger.info(
                "staff_document_alerts_no_recipient",
                extra={"organization_id": organization_id, "count": len(organization_alerts)},
            )
            continue
        for alert in organization_alerts:
            title, body = alert_text(alert, today)
            for admin_id in admins:
                await notification_service.create_notification(
                    CreateNotificationCommand(
                        organization_id=organization_id,
                        recipient_user_id=admin_id,
                        type=NOTIFICATION_TYPE,
                        title=title,
                        body=body,
                        data={
                            "kind": NOTIFICATION_KIND,
                            "staff_id": alert.staff_id,
                            "document_id": alert.document_id,
                            "expires_on": alert.expires_on.isoformat(),
                            "threshold_days": alert.threshold_days,
                        },
                        trip_id=None,
                        actor=SYSTEM_PRINCIPAL,
                    ),
                    uow=notifications_uow(),
                )
            await staff_service.mark_expiry_alerted(
                alert.document_id, alert.threshold_days, uow=transport_ops_uow()
            )
            sent += 1
    return sent
