"""PostgreSQL-backed integration test for `raad.core.audit.reader.any_entry_references`
(Organization Management phase).

Found live, not designed up front: `BillingApplicationService.delete_plan`'s original single
check (`SubscriptionRepository.exists_for_plan`) only sees a subscription's *current* `plan_id`,
which stopped being a reliable "has this plan ever been used" proxy the moment `change_plan`
shipped in this same phase — a subscription that moves off a plan makes that plan invisible to
the check, even though a real invoice may already have been issued at its price. This test proves
the real SQL behind the second, closing check (`PlanHistoryPort` / `AuditPlanHistoryAdapter`)
against the actual `audit_entries.metadata_json` column — a fake cannot see whether
`.op("->>")` is the right operator for this column's real (`JSON`, not `JSONB`) type, only a real
database can.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable, mirroring every other integration test in this suite.
Every row this test writes is tagged with a unique per-run marker and deleted in `tearDown` —
these are synthetic test fixtures, not real audit facts, so cleaning them up does not touch this
codebase's own "audit rows are never hard-deleted" production rule (`.claude/rules/database.md`
#5), which protects genuine audit trails, not throwaway rows a test wrote directly.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.audit.reader import any_entry_references
from raad.core.audit.writer import AuditEntryRecord
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.ids.generator import UlidGenerator


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class AuditEntryReferenceLookupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.id_generator = UlidGenerator()
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )

    async def _seed(self, *, entity_type: str, metadata: dict) -> None:
        session = self.session_factory()
        try:
            entry_id = self.id_generator.new_id()
            session.add(
                AuditEntryRecord(
                    id=entry_id,
                    action="SubscriptionPlanChanged",
                    entity_type=entity_type,
                    metadata_json=metadata,
                )
            )
            await session.commit()
            self._created_ids.append(entry_id)
        finally:
            await session.close()

    async def test_finds_a_plan_id_named_directly(self) -> None:
        plan_id = uuid.uuid4().hex
        await self._seed(entity_type="Subscription", metadata={"plan_id": plan_id})

        session = self.session_factory()
        try:
            found = await any_entry_references(
                session, entity_type="Subscription", field="plan_id", value=plan_id
            )
        finally:
            await session.close()
        self.assertTrue(found)

    async def test_finds_a_plan_id_named_as_old_plan_id(self) -> None:
        """The exact shape `Subscription.change_plan`'s own `SubscriptionPlanChanged` event
        records — proves the field-name parameterization actually matters, not just that any
        JSON key match works."""
        old_plan_id = uuid.uuid4().hex
        new_plan_id = uuid.uuid4().hex
        await self._seed(
            entity_type="Subscription",
            metadata={"old_plan_id": old_plan_id, "new_plan_id": new_plan_id},
        )

        session = self.session_factory()
        try:
            found_old = await any_entry_references(
                session, entity_type="Subscription", field="old_plan_id", value=old_plan_id
            )
            found_as_new = await any_entry_references(
                session, entity_type="Subscription", field="new_plan_id", value=old_plan_id
            )
        finally:
            await session.close()
        self.assertTrue(found_old)
        self.assertFalse(found_as_new, "old_plan_id's value must not match under a different key")

    async def test_does_not_find_an_unrelated_plan_id(self) -> None:
        await self._seed(entity_type="Subscription", metadata={"plan_id": uuid.uuid4().hex})

        session = self.session_factory()
        try:
            found = await any_entry_references(
                session, entity_type="Subscription", field="plan_id", value=uuid.uuid4().hex
            )
        finally:
            await session.close()
        self.assertFalse(found)

    async def test_does_not_match_across_a_different_entity_type(self) -> None:
        """A plan id that happens to appear in some unrelated entity's own metadata must never
        false-positive a plan-deletion refusal."""
        plan_id = uuid.uuid4().hex
        await self._seed(entity_type="Organization", metadata={"plan_id": plan_id})

        session = self.session_factory()
        try:
            found = await any_entry_references(
                session, entity_type="Subscription", field="plan_id", value=plan_id
            )
        finally:
            await session.close()
        self.assertFalse(found)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
