"""The staff document expiry-alert job (ADR-0051 §3)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.config.settings import Settings, WorkerSettings
from raad.core.di.container import Container
from raad.core.pagination import OffsetPage
from raad.core.time.clock import Clock
from raad.core.workers.scheduler import IntervalScheduler
from raad.interfaces.workers.bootstrap import _register_scheduled_jobs
from raad.interfaces.workers.staff_document_alerts import (
    alert_text,
    notify_expiring_staff_documents,
)
from raad.modules.transport_ops.application.queries import DueExpiryAlertDTO

TODAY = date(2026, 9, 30)
ORG_A = "01J8Z3K9G6X8YV5T4N2R7QW3MA"
ORG_B = "01J8Z3K9G6X8YV5T4N2R7QW3MB"


def _alert(document_id: str, organization_id: str = ORG_A, **overrides) -> DueExpiryAlertDTO:
    values = dict(
        organization_id=organization_id,
        document_id=document_id,
        staff_id="staff-1",
        staff_name="Amina Warsame",
        type_name="Driving licence",
        expires_on=date(2026, 10, 7),
        threshold_days=7,
    )
    values.update(overrides)
    return DueExpiryAlertDTO(**values)


class _StaffService:
    def __init__(self, alerts: list[DueExpiryAlertDTO]) -> None:
        self.alerts = alerts
        self.marked: list[tuple[str, int]] = []

    async def collect_due_expiry_alerts(self, *, uow):
        return list(self.alerts)

    async def mark_expiry_alerted(self, document_id, threshold_days, *, uow):
        self.marked.append((document_id, threshold_days))


class _User:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


class _UserService:
    def __init__(self, admins: dict[str, list[str]]) -> None:
        self.admins = admins
        self.queries = []

    async def list_users(self, query, *, uow):
        self.queries.append(query)
        filters = {f.field: f.value for f in query.filters}
        assert filters["role"] == "org_admin" and filters["status"] == "active"
        ids = self.admins.get(filters["organization_id"], [])
        return OffsetPage(
            data=[_User(i) for i in ids], total=len(ids), page=1, page_size=100
        )


class _NotificationService:
    def __init__(self) -> None:
        self.commands = []

    async def create_notification(self, command, *, uow):
        self.commands.append(command)


async def _run(staff: _StaffService, users: _UserService, notes: _NotificationService) -> int:
    return await notify_expiring_staff_documents(
        today=TODAY,
        staff_service=staff,  # type: ignore[arg-type]
        user_service=users,  # type: ignore[arg-type]
        notification_service=notes,  # type: ignore[arg-type]
        transport_ops_uow=lambda: object(),  # type: ignore[arg-type,return-value]
        iam_uow=lambda: object(),  # type: ignore[arg-type,return-value]
        notifications_uow=lambda: object(),  # type: ignore[arg-type,return-value]
    )


class NotifyExpiringStaffDocumentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_active_org_admin_gets_one_notification_per_alert(self) -> None:
        staff = _StaffService([_alert("d1"), _alert("d2", ORG_B)])
        users = _UserService({ORG_A: ["a1", "a2"], ORG_B: ["b1"]})
        notes = _NotificationService()

        sent = await _run(staff, users, notes)

        self.assertEqual(sent, 2)
        self.assertEqual(
            sorted((c.organization_id, c.recipient_user_id) for c in notes.commands),
            [(ORG_A, "a1"), (ORG_A, "a2"), (ORG_B, "b1")],
        )
        self.assertTrue(all(c.type == "system" for c in notes.commands))
        self.assertEqual(notes.commands[0].data["kind"], "staff_document_expiry")
        self.assertEqual(sorted(staff.marked), [("d1", 7), ("d2", 7)])

    async def test_an_organization_without_an_admin_keeps_its_alerts_for_later(self) -> None:
        staff = _StaffService([_alert("d1")])
        notes = _NotificationService()

        sent = await _run(staff, _UserService({}), notes)

        self.assertEqual((sent, notes.commands, staff.marked), (0, [], []))

    async def test_notification_payload_carries_no_document_number(self) -> None:
        notes = _NotificationService()
        await _run(_StaffService([_alert("d1")]), _UserService({ORG_A: ["a1"]}), notes)
        self.assertEqual(
            set(notes.commands[0].data),
            {"kind", "staff_id", "document_id", "expires_on", "threshold_days"},
        )


class AlertTextTests(unittest.TestCase):
    def test_wording_follows_the_real_days_left(self) -> None:
        cases = {
            date(2026, 10, 30): "Driving licence expires in 30 days",
            date(2026, 10, 1): "Driving licence expires tomorrow",
            TODAY: "Driving licence expires today",
            date(2026, 1, 1): "Driving licence has expired",
        }
        for expires_on, title in cases.items():
            with self.subTest(expires_on=expires_on):
                self.assertEqual(alert_text(_alert("d", expires_on=expires_on), TODAY)[0], title)


class _Clock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 9, 30, tzinfo=timezone.utc)


class RegistrationTests(unittest.TestCase):
    def _job_names(self, settings: Settings) -> set[str]:
        scheduler = IntervalScheduler(_Clock())
        _register_scheduled_jobs(scheduler, Container(), settings)
        return {job.name for job in scheduler._jobs}

    def test_on_by_default_and_off_with_the_flag(self) -> None:
        self.assertIn("notify_expiring_staff_documents", self._job_names(Settings()))
        off = Settings(workers=WorkerSettings(staff_document_expiry_alerts=False))
        self.assertNotIn("notify_expiring_staff_documents", self._job_names(off))


if __name__ == "__main__":
    unittest.main()
