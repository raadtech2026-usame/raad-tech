"""Unit tests for `core.audit.writer.AuditWriter` (ADR-0007, Backend Stabilization phase).
Stdlib `unittest` — no `pytest` (not an approved dependency). No SQLAlchemy session/database
involved: `AuditWriter.write` only calls `session.add(...)`, so a minimal fake session capturing
that call is enough to verify field derivation without any I/O, mirroring how this codebase
tests every other pure "compute + hand to session.add" persistence-support class.

Covers the field-derivation mapping documented in `writer.py`'s own module docstring: `action`
from `event_type` verbatim, `entity_type`/`entity_id` from `aggregate_type`/`aggregate_id`,
`actor_user_id` from `payload["actor_id"]` (and `None` when absent or non-string),
`metadata_json` as the full payload, `ip` always `None`, and the naive-UTC timestamp fix.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.audit.writer import AuditEntryRecord, AuditWriter
from raad.core.events.base import DomainEvent


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


def make_event(
    *,
    event_type: str = "VideoSessionStarted",
    aggregate_type: str = "VideoSession",
    aggregate_id: str = "01J8Z3K9G6X8YV5T4N2R7QW3VS",
    org_id: str | None = "01J8Z3K9G6X8YV5T4N2R7QW3MD",
    correlation_id: str | None = None,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> DomainEvent:
    return DomainEvent(
        event_id="01J8Z3K9G6X8YV5T4N2R7QW3EV",
        event_type=event_type,
        version=1,
        occurred_at=occurred_at or datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc),
        org_id=org_id,
        correlation_id=correlation_id,
        payload=payload if payload is not None else {"actor_id": "01J8Z3K9G6X8YV5T4N2R7QW3AC"},
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


class AuditWriterFieldMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_is_event_type_verbatim(self) -> None:
        session = FakeSession()
        await AuditWriter().write(session, make_event(event_type="TripStarted"))
        entry: AuditEntryRecord = session.added[0]
        self.assertEqual(entry.action, "TripStarted")

    async def test_entity_type_and_id_come_from_aggregate_fields(self) -> None:
        session = FakeSession()
        await AuditWriter().write(
            session,
            make_event(aggregate_type="Trip", aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3TR"),
        )
        entry: AuditEntryRecord = session.added[0]
        self.assertEqual(entry.entity_type, "Trip")
        self.assertEqual(entry.entity_id, "01J8Z3K9G6X8YV5T4N2R7QW3TR")

    async def test_organization_id_passes_through_including_none(self) -> None:
        session = FakeSession()
        await AuditWriter().write(session, make_event(org_id=None))
        entry: AuditEntryRecord = session.added[0]
        self.assertIsNone(entry.organization_id)

    async def test_actor_user_id_extracted_from_payload(self) -> None:
        session = FakeSession()
        await AuditWriter().write(
            session, make_event(payload={"actor_id": "01J8Z3K9G6X8YV5T4N2R7QW3AC"})
        )
        entry: AuditEntryRecord = session.added[0]
        self.assertEqual(entry.actor_user_id, "01J8Z3K9G6X8YV5T4N2R7QW3AC")

    async def test_actor_user_id_none_when_payload_has_no_actor_id(self) -> None:
        session = FakeSession()
        await AuditWriter().write(session, make_event(payload={"device_id": "dev-1"}))
        entry: AuditEntryRecord = session.added[0]
        self.assertIsNone(entry.actor_user_id)

    async def test_actor_user_id_none_when_actor_id_is_not_a_string(self) -> None:
        session = FakeSession()
        await AuditWriter().write(session, make_event(payload={"actor_id": None}))
        entry: AuditEntryRecord = session.added[0]
        self.assertIsNone(entry.actor_user_id)

    async def test_metadata_json_is_the_full_payload(self) -> None:
        session = FakeSession()
        payload = {"actor_id": "01J8Z3K9G6X8YV5T4N2R7QW3AC", "device_id": "dev-2"}
        await AuditWriter().write(session, make_event(payload=payload))
        entry: AuditEntryRecord = session.added[0]
        self.assertEqual(entry.metadata_json, payload)

    async def test_ip_is_always_none(self) -> None:
        session = FakeSession()
        await AuditWriter().write(session, make_event())
        entry: AuditEntryRecord = session.added[0]
        self.assertIsNone(entry.ip)

    async def test_correlation_id_passes_through(self) -> None:
        session = FakeSession()
        await AuditWriter().write(
            session, make_event(correlation_id="01J8Z3K9G6X8YV5T4N2R7QW3CR")
        )
        entry: AuditEntryRecord = session.added[0]
        self.assertEqual(entry.correlation_id, "01J8Z3K9G6X8YV5T4N2R7QW3CR")

    async def test_created_at_is_stripped_to_naive_utc(self) -> None:
        session = FakeSession()
        aware = datetime(2026, 7, 21, 9, 30, 0, tzinfo=timezone.utc)
        await AuditWriter().write(session, make_event(occurred_at=aware))
        entry: AuditEntryRecord = session.added[0]
        self.assertIsNone(entry.created_at.tzinfo)
        self.assertEqual(entry.created_at, aware.replace(tzinfo=None))

    async def test_write_all_writes_one_row_per_event(self) -> None:
        session = FakeSession()
        events = [
            make_event(event_type="TripScheduled", aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3T1"),
            make_event(event_type="TripStarted", aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3T1"),
        ]
        await AuditWriter().write_all(session, events)
        self.assertEqual(len(session.added), 2)
        self.assertEqual(session.added[0].action, "TripScheduled")
        self.assertEqual(session.added[1].action, "TripStarted")

    async def test_write_all_with_no_events_writes_nothing(self) -> None:
        session = FakeSession()
        await AuditWriter().write_all(session, [])
        self.assertEqual(session.added, [])


if __name__ == "__main__":
    unittest.main()
