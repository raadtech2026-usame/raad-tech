"""Domain-only tests for `platform_audit`'s `SystemSetting` aggregate and `AuditEntry`
read-model (Backend Stabilization phase). Stdlib `unittest` — no `pytest` (not an approved
dependency), mirroring `test_billing_domain.py`'s established precedent.

Covers: `SystemSettingKey`'s 26-char cap (the outbox/audit_entries `CHAR(26)` constraint —
`domain/value_objects.py`'s own docstring), `SystemSetting.set`/`update_value` (including the
idempotent same-value no-op), domain-event emission, and `AuditEntry`'s plain read-model shape
(equality-by-id, no behavior methods).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.platform_audit.domain.entities import AuditEntry, SystemSetting
from raad.modules.platform_audit.domain.repositories import (
    AuditEntryRepository,
    SystemSettingRepository,
)
from raad.modules.platform_audit.domain.value_objects import (
    AuditEntryId,
    OrganizationId,
    SystemSettingKey,
    UserId,
)

VALID_ENTRY_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3AE"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_USER_REF = "some-opaque-user-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc))


class AuditEntryIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(AuditEntryId(VALID_ENTRY_ULID)), VALID_ENTRY_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            AuditEntryId("TOOSHORT")


class SystemSettingKeyValidationTests(unittest.TestCase):
    def test_valid_key_constructs(self) -> None:
        self.assertEqual(str(SystemSettingKey("maps.provider")), "maps.provider")

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            SystemSettingKey("")

    def test_over_26_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            SystemSettingKey("a" * 27)

    def test_exactly_26_chars_constructs(self) -> None:
        key = "a" * 26
        self.assertEqual(str(SystemSettingKey(key)), key)


class SystemSettingLifecycleTests(unittest.TestCase):
    def test_set_starts_with_given_value_and_scope(self) -> None:
        setting = SystemSetting.set(
            key=SystemSettingKey("maps.provider"),
            value={"provider": "google"},
            scope="platform",
            clock=CLOCK,
        )
        self.assertEqual(setting.value, {"provider": "google"})
        self.assertEqual(setting.scope, "platform")

    def test_set_records_system_setting_set_event(self) -> None:
        setting = SystemSetting.set(
            key=SystemSettingKey("maps.provider"),
            value={"provider": "google"},
            scope="platform",
            clock=CLOCK,
            actor_id="admin-1",
        )
        events = setting.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "SystemSettingSet")
        self.assertEqual(events[0].aggregate_type, "SystemSetting")
        self.assertEqual(events[0].aggregate_id, "maps.provider")
        self.assertEqual(events[0].payload["actor_id"], "admin-1")

    def test_empty_scope_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            SystemSetting.set(
                key=SystemSettingKey("maps.provider"),
                value={},
                scope="",
                clock=CLOCK,
            )

    def test_update_value_changes_value_and_records_event(self) -> None:
        setting = SystemSetting.set(
            key=SystemSettingKey("maps.provider"),
            value={"provider": "google"},
            scope="platform",
            clock=CLOCK,
        )
        setting.pull_domain_events()
        setting.update_value({"provider": "mapbox"}, clock=CLOCK)
        self.assertEqual(setting.value, {"provider": "mapbox"})
        events = setting.pull_domain_events()
        self.assertEqual(events[0].event_type, "SystemSettingUpdated")

    def test_update_value_with_same_value_is_idempotent_no_op(self) -> None:
        setting = SystemSetting.set(
            key=SystemSettingKey("maps.provider"),
            value={"provider": "google"},
            scope="platform",
            clock=CLOCK,
        )
        setting.pull_domain_events()
        setting.update_value({"provider": "google"}, clock=CLOCK)
        self.assertEqual(setting.pull_domain_events(), [])

    def test_equality_is_by_key(self) -> None:
        a = SystemSetting.set(
            key=SystemSettingKey("k1"), value={}, scope="platform", clock=CLOCK
        )
        b = SystemSetting.set(
            key=SystemSettingKey("k1"), value={"x": 1}, scope="org", clock=CLOCK
        )
        self.assertEqual(a, b)


class AuditEntryReadModelTests(unittest.TestCase):
    def _make_entry(self) -> AuditEntry:
        return AuditEntry(
            id=AuditEntryId(VALID_ENTRY_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            actor_user_id=UserId(VALID_USER_REF),
            action="TripStarted",
            entity_type="Trip",
            entity_id="01J8Z3K9G6X8YV5T4N2R7QW3TR",
            metadata={"actor_id": VALID_USER_REF},
            ip=None,
            correlation_id=None,
            created_at=CLOCK.now(),
        )

    def test_constructs_with_all_fields(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.action, "TripStarted")
        self.assertEqual(entry.entity_type, "Trip")

    def test_nullable_organization_and_actor(self) -> None:
        entry = AuditEntry(
            id=AuditEntryId(VALID_ENTRY_ULID),
            organization_id=None,
            actor_user_id=None,
            action="SystemSettingSet",
            entity_type="SystemSetting",
            entity_id=None,
            metadata=None,
            ip=None,
            correlation_id=None,
            created_at=CLOCK.now(),
        )
        self.assertIsNone(entry.organization_id)
        self.assertIsNone(entry.actor_user_id)

    def test_equality_is_by_id(self) -> None:
        a = self._make_entry()
        b = self._make_entry()
        self.assertEqual(a, b)

    def test_has_no_pull_domain_events_method(self) -> None:
        """A read-model, not an aggregate — see `entities.py`'s own module docstring."""
        entry = self._make_entry()
        self.assertFalse(hasattr(entry, "pull_domain_events"))


class RepositoryInterfaceShapeTests(unittest.TestCase):
    def test_audit_entry_repository_is_abstract_and_has_no_add(self) -> None:
        with self.assertRaises(TypeError):
            AuditEntryRepository()  # type: ignore[abstract]
        self.assertFalse(hasattr(AuditEntryRepository, "add"))
        for name in ("get", "list_all"):
            self.assertTrue(hasattr(AuditEntryRepository, name))

    def test_system_setting_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            SystemSettingRepository()  # type: ignore[abstract]
        for name in ("get", "add", "list_all"):
            self.assertTrue(hasattr(SystemSettingRepository, name))


if __name__ == "__main__":
    unittest.main()
