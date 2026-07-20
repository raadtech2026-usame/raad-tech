"""Domain-only tests for `notifications`'s two aggregates (Phase 16). Stdlib `unittest` — no
`pytest` (not an approved dependency), mirroring `test_billing_domain.py`'s established
one-file-per-phase precedent (both aggregates landed in one phase).

Covers: value-object validation (ULID id types, opaque cross-module VOs, `FcmToken`), the
derived `NotificationStatus` computation, construction, every documented lifecycle method per
aggregate (idempotent same-state no-ops), domain-event emission, and repository-interface shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.repositories import (
    DeviceTokenRepository,
    NotificationRepository,
)
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    FcmToken,
    NotificationId,
    NotificationStatus,
    NotificationType,
    OrganizationId,
    Platform,
    TripId,
    UserId,
)

VALID_NOTIFICATION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3NT"
VALID_DEVICE_TOKEN_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3DT"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_RECIPIENT_REF = "some-opaque-recipient-ref"
VALID_TRIP_REF = "some-opaque-trip-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


# --- Value objects -----------------------------------------------------------------------


class UlidValueObjectValidationTests(unittest.TestCase):
    def test_notification_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(
            str(NotificationId(VALID_NOTIFICATION_ULID)), VALID_NOTIFICATION_ULID
        )

    def test_notification_id_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            NotificationId("TOOSHORT")

    def test_notification_id_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            NotificationId(VALID_NOTIFICATION_ULID.lower())

    def test_device_token_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(
            str(DeviceTokenId(VALID_DEVICE_TOKEN_ULID)), VALID_DEVICE_TOKEN_ULID
        )

    def test_device_token_id_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DeviceTokenId("TOOSHORT")


class OpaqueCrossModuleValueObjectTests(unittest.TestCase):
    def test_organization_id_non_empty_constructs(self) -> None:
        self.assertEqual(str(OrganizationId(VALID_ORG_ULID)), VALID_ORG_ULID)

    def test_organization_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("")

    def test_user_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(UserId(VALID_RECIPIENT_REF)), VALID_RECIPIENT_REF)

    def test_user_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            UserId("")

    def test_trip_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(TripId(VALID_TRIP_REF)), VALID_TRIP_REF)

    def test_trip_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            TripId("")


class FcmTokenValidationTests(unittest.TestCase):
    def test_non_empty_token_constructs(self) -> None:
        self.assertEqual(str(FcmToken("some-token-value")), "some-token-value")

    def test_empty_token_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            FcmToken("")


# --- Notification ----------------------------------------------------------------------------


class NotificationTests(unittest.TestCase):
    def _make_notification(self, **overrides) -> Notification:
        defaults = dict(
            id=NotificationId(VALID_NOTIFICATION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            recipient_user_id=UserId(VALID_RECIPIENT_REF),
            type=NotificationType.TRIP_STARTED,
            title="Morning trip started",
            body="Your child's bus has started its morning trip.",
            trip_id=TripId(VALID_TRIP_REF),
            clock=CLOCK,
        )
        defaults.update(overrides)
        return Notification.create(**defaults)

    def test_create_starts_unread(self) -> None:
        notification = self._make_notification()
        self.assertIsNone(notification.read_at)
        self.assertEqual(notification.status, NotificationStatus.UNREAD)

    def test_create_records_notification_created_event(self) -> None:
        notification = self._make_notification()
        events = notification.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "NotificationCreated")
        self.assertEqual(events[0].aggregate_type, "Notification")
        self.assertEqual(events[0].org_id, VALID_ORG_ULID)

    def test_create_with_empty_title_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            self._make_notification(title="")

    def test_create_with_title_too_long_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            self._make_notification(title="x" * 161)

    def test_create_with_empty_body_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            self._make_notification(body="")

    def test_create_with_body_too_long_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            self._make_notification(body="x" * 501)

    def test_create_with_no_trip_id_is_accepted(self) -> None:
        notification = self._make_notification(
            trip_id=None, type=NotificationType.SUBSCRIPTION
        )
        self.assertIsNone(notification.trip_id)

    def test_create_with_data_payload_is_accepted(self) -> None:
        notification = self._make_notification(data={"deep_link": "raad://trip/01J..."})
        self.assertEqual(notification.data, {"deep_link": "raad://trip/01J..."})

    def test_mark_read_sets_read_at_and_status(self) -> None:
        notification = self._make_notification()
        notification.pull_domain_events()
        notification.mark_read(clock=CLOCK)
        self.assertEqual(notification.read_at, CLOCK.now())
        self.assertEqual(notification.status, NotificationStatus.READ)
        events = notification.pull_domain_events()
        self.assertEqual(events[0].event_type, "NotificationRead")

    def test_mark_read_when_already_read_is_idempotent_no_op(self) -> None:
        notification = self._make_notification()
        notification.mark_read(clock=CLOCK)
        notification.pull_domain_events()
        notification.mark_read(clock=CLOCK)
        self.assertEqual(notification.pull_domain_events(), [])

    def test_notification_type_enum_matches_documented_catalogue(self) -> None:
        expected = {
            "trip_started",
            "approaching_stop",
            "arrived_org",
            "trip_completed",
            "subscription",
            "system",
        }
        self.assertEqual({t.value for t in NotificationType}, expected)


# --- DeviceToken ------------------------------------------------------------------------------


class DeviceTokenTests(unittest.TestCase):
    def _make_device_token(self, **overrides) -> DeviceToken:
        defaults = dict(
            id=DeviceTokenId(VALID_DEVICE_TOKEN_ULID),
            user_id=UserId(VALID_RECIPIENT_REF),
            fcm_token=FcmToken("fcm-token-abc123"),
            platform=Platform.ANDROID,
            clock=CLOCK,
        )
        defaults.update(overrides)
        return DeviceToken.register(**defaults)

    def test_register_starts_active(self) -> None:
        token = self._make_device_token()
        self.assertIsNone(token.revoked_at)
        self.assertTrue(token.is_active)

    def test_register_records_device_token_registered_event(self) -> None:
        token = self._make_device_token()
        events = token.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "DeviceTokenRegistered")
        self.assertEqual(events[0].aggregate_type, "DeviceToken")
        self.assertIsNone(events[0].org_id)

    def test_revoke_sets_revoked_at(self) -> None:
        token = self._make_device_token()
        token.pull_domain_events()
        token.revoke(clock=CLOCK)
        self.assertEqual(token.revoked_at, CLOCK.now())
        self.assertFalse(token.is_active)
        events = token.pull_domain_events()
        self.assertEqual(events[0].event_type, "DeviceTokenRevoked")

    def test_revoke_when_already_revoked_is_idempotent_no_op(self) -> None:
        token = self._make_device_token()
        token.revoke(clock=CLOCK)
        token.pull_domain_events()
        token.revoke(clock=CLOCK)
        self.assertEqual(token.pull_domain_events(), [])

    def test_platform_enum_matches_documented_values(self) -> None:
        self.assertEqual({p.value for p in Platform}, {"android", "ios"})


# --- Repository interface shape -----------------------------------------------------------


class RepositoryInterfaceShapeTests(unittest.TestCase):
    def test_notification_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            NotificationRepository()  # type: ignore[abstract]

    def test_notification_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all", "list_for_recipient"):
            self.assertTrue(hasattr(NotificationRepository, method))

    def test_device_token_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all", "get_by_token"):
            self.assertTrue(hasattr(DeviceTokenRepository, method))


if __name__ == "__main__":
    unittest.main()
