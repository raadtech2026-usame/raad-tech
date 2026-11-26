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
        credentials_json: str | None = None,
        credentials_base64: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._initialized = False
        if not _FIREBASE_AVAILABLE:
            logger.warning(
                "firebase_admin_not_installed",
                extra={"hint": "Install firebase-admin to enable push notifications."},
            )
            return

        import os
        credentials_path = credentials_path or os.getenv("FIREBASE_CREDENTIALS_PATH") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        credentials_json = credentials_json or os.getenv("RAAD_FIREBASE__CREDENTIALS_JSON") or os.getenv("FIREBASE_CREDENTIALS_JSON")
        credentials_base64 = credentials_base64 or os.getenv("RAAD_FIREBASE__CREDENTIALS_BASE64") or os.getenv("FIREBASE_CREDENTIALS_BASE64")
        project_id = project_id or os.getenv("RAAD_FIREBASE__PROJECT_ID") or os.getenv("FIREBASE_PROJECT_ID")

        try:
            if not firebase_admin._apps:
                import base64
                import json
                cert_data = None
                if credentials_base64 and credentials_base64.strip():
                    raw = base64.b64decode(credentials_base64.strip()).decode("utf-8")
                    cert_data = json.loads(raw)
                elif credentials_json:
                    if isinstance(credentials_json, str):
                        raw_str = credentials_json.strip()
                        if "require(" in raw_str or "import " in raw_str or "admin.initializeApp" in raw_str:
                            logger.error(
                                "firebase_invalid_credentials_code_snippet",
                                extra={
                                    "hint": (
                                        "Code snippet from Firebase console was passed instead of the Service Account "
                                        "JSON private key. In Firebase Console, go to Project Settings -> Service Accounts, "
                                        "and click 'Generate new private key' to download the JSON file."
                                    )
                                },
                            )
                            return
                        try:
                            cert_data = json.loads(raw_str)
                        except json.JSONDecodeError:
                            try:
                                decoded = base64.b64decode(raw_str).decode("utf-8")
                                cert_data = json.loads(decoded)
                            except Exception:
                                logger.error("firebase_credentials_json_parse_failed")
                                return
                    else:
                        cert_data = credentials_json

                if cert_data:
                    if "client" in cert_data and "private_key" not in cert_data:
                        logger.error(
                            "firebase_invalid_credentials_client_file",
                            extra={
                                "hint": (
                                    "google-services.json (mobile client file) was passed instead of Firebase Admin "
                                    "Service Account private key. In Firebase Console, go to Project Settings -> "
                                    "Service Accounts, and click 'Generate new private key' to download the server key."
                                )
                            },
                        )
                        return
                    cred = credentials.Certificate(cert_data)
                    firebase_admin.initialize_app(cred, {"projectId": project_id} if project_id else None)
                elif credentials_path:
                    if not os.path.exists(credentials_path):
                        logger.error(
                            "firebase_credentials_file_not_found",
                            extra={"path": credentials_path},
                        )
                        return
                    cred = credentials.Certificate(credentials_path)
                    firebase_admin.initialize_app(cred, {"projectId": project_id} if project_id else None)
                else:
                    firebase_admin.initialize_app(options={"projectId": project_id} if project_id else None)
            self._initialized = True
            logger.info("firebase_fcm_sender_initialized", extra={"project_id": project_id})
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
            logger.warning(
                "fcm_push_skipped_not_initialized",
                extra={"token_count": len(tokens), "title": title},
            )
            return []

        clean_data = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
        clean_data.setdefault("title", title)
        clean_data.setdefault("body", body)
        dead_tokens: list[str] = []

        kind = clean_data.get("kind") or clean_data.get("type", "")
        is_safety = kind in (
            "safety_alert",
            "sos",
            "collision",
            "rollover",
            "forward_collision",
            "pedestrian_collision",
        )
        is_message = kind in (
            "incident_notice",
            "staff_unavailable",
            "cover_assigned",
            "trip_cancelled",
            "student_absence",
        )

        channel_id = (
            "raad_safety_alerts"
            if is_safety
            else ("raad_messages_alerts" if is_message else "raad_transport_alerts")
        )
        android_priority = "max" if is_safety else "high"
        apns_interruption = (
            "critical"
            if is_safety
            else ("active" if is_message else "time-sensitive")
        )

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
                        channel_id=channel_id,
                        priority=android_priority,
                        default_sound=True,
                        default_vibrate_timings=True,
                    ),
                ),
                apns=messaging.APNSConfig(
                    headers={"apns-priority": "10"},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound="default",
                            badge=1,
                            content_available=True,
                            interruption_level=apns_interruption,
                        )
                    ),
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
                            logger.warning(
                                "fcm_multicast_token_failure",
                                extra={
                                    "token_prefix": chunk[idx][:16],
                                    "error": str(resp.exception),
                                },
                            )
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
