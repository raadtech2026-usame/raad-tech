"""Outbound ports the `notifications` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with
`notifications`' own two repositories, mirroring `billing.application.ports.BillingUnitOfWork`
exactly.

**No FCM/push-provider port is defined here.** The task's own Delivery scope explicitly forbids
Firebase Cloud Messaging/APNS/SMS/email/WhatsApp/push-SDK integration this phase — persistence
only. Unlike `billing.application.ports.PaymentProviderPort` (documented, LLD §4.2-named, just
unbound), no approved document names a push-provider port interface for this module at all, so
none is declared even as an unbound interface — inventing one would be scope creep beyond what
was asked.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.notifications.domain.repositories import (
    DeviceTokenRepository,
    NotificationRepository,
)


class NotificationsUnitOfWork(UnitOfWork):
    """Bundles this module's two repositories onto one transaction boundary, mirroring
    `TransportOpsUnitOfWork`/`BillingUnitOfWork`'s identical shape. The concrete implementation
    is `infra.repositories.SqlAlchemyNotificationsUnitOfWork`.
    """

    notifications: NotificationRepository
    device_tokens: DeviceTokenRepository
