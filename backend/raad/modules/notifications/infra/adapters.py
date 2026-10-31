"""External adapters for `notifications` (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

Implements `PushNotificationSenderPort` via Firebase Cloud Messaging (`firebase-admin`)
for pushing proximity/geofence alerts (approaching stop, arrived at school) to parent devices.
"""

from __future__ import annotations

import asyncio
from typing import Any

from raad.core.logging.setup import get_logger
from raad.modules.notifications.application.ports import PushNotificationSenderPort

logger = get_logger("raad.notifications.infra.adapters")

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    _FIREBASE_AVAILABLE = True
except ImportError:
    firebase_admin = None
    messaging = None
    _FIREBASE_AVAILABLE = False


class NoopPushNotificationSender(PushNotificationSenderPort):
    """Fallback no-op push sender when Firebase is not configured or disabled."""

    async def send_to_tokens(
        self,
        *,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> list[str]:
        logger.debug(
            "push_notification_noop_skipped",
            extra={"token_count": len(tokens), "title": title},
        )
        return []


class FirebaseFcmPushSender(PushNotificationSenderPort):
    """Production FCM push sender using `firebase-admin`.

    Formats and sends high-priority multicast messages for bus proximity alerts.
    Identifies unregistered or invalid tokens so callers can soft-revoke them.
    """

    def __init__(
        self,
        *,
        credentials_path: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._initialized = False
        if not _FIREBASE_AVAILABLE:
            logger.warning(
                "firebase_admin_not_installed",
                extra={"hint": "Install firebase-admin to enable push notifications."},
            )
            return

        try:
            if not firebase_admin._apps:
                if credentials_path:
                    cred = credentials.Certificate(credentials_path)
                    firebase_admin.initialize_app(cred, {"projectId": project_id} if project_id else None)
                else:
                    firebase_admin.initialize_app(options={"projectId": project_id} if project_id else None)
            self._initialized = True
            logger.info("firebase_fcm_sender_initialized")
        except Exception as exc:
            logger.warning(
                "firebase_initialization_failed",
                extra={"error": str(exc)},
            )

    async def send_to_tokens(
        self,
        *,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> list[str]:
        if not tokens:
            return []

        if not self._initialized or not _FIREBASE_AVAILABLE or messaging is None:
            logger.debug(
                "fcm_push_skipped_not_initialized",
                extra={"token_count": len(tokens), "title": title},
            )
            return []

        clean_data = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
        dead_tokens: list[str] = []

        # FCM multicast accepts at most 500 tokens per batch
        chunk_size = 500
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i : i + chunk_size]
            multicast = messaging.MulticastMessage(
                tokens=chunk,
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=clean_data,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                        channel_id="raad_transport_alerts",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", badge=1)
                    )
                ),
            )

            try:
                # `send_each_for_multicast` is synchronous in firebase-admin; run in threadpool
                response = await asyncio.to_thread(
                    messaging.send_each_for_multicast, multicast
                )
                logger.info(
                    "fcm_multicast_dispatched",
                    extra={
                        "total": len(chunk),
                        "success": response.success_count,
                        "failure": response.failure_count,
                    },
                )

                if response.failure_count > 0:
                    for idx, resp in enumerate(response.responses):
                        if not resp.success and resp.exception:
                            err_str = str(resp.exception).lower()
                            if (
                                "unregistered" in err_str
                                or "not-registered" in err_str
                                or "invalid-registration-token" in err_str
                            ):
                                dead_tokens.append(chunk[idx])
            except Exception as exc:
                logger.error(
                    "fcm_multicast_send_error",
                    extra={"error": str(exc), "token_count": len(chunk)},
                )

        return dead_tokens
