"""PostgreSQL-backed integration test for `vehicle_positions` monthly RANGE partitioning
(audit finding B15).

**This is the only place the partitioning can be proven.** `maintain_partitions` issues raw
`CREATE TABLE ... PARTITION OF` / `DROP TABLE` DDL, and the in-memory fake in
`tests/unit/test_tracking_application.py` deliberately does nothing and says so — partition DDL
has no meaningful in-memory analogue. A green unit suite tells you nothing about whether any of
this works, which is exactly the fake-vs-real gap CLAUDE.md's Permanent Engineering Lessons
already record twice for this codebase.

What is asserted here, none of which a fake could catch:

- the table is genuinely `PARTITION BY RANGE` (`relkind = 'p'`), not a plain heap
- a row routes to the correct monthly partition by `event_time`
- a row with an `event_time` outside every defined month still inserts, landing in `DEFAULT` —
  the safety net that stops a live GPS fix from a moving bus being rejected outright
- the maintenance job provisions months ahead, and is idempotent across repeated runs
- it drops only *fully*-expired partitions, never one straddling the retention cutoff
- it never drops the `DEFAULT` partition

Skipped (not failed) when no database is reachable, matching every other integration test here.
Every partition this test creates is dropped in teardown.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.modules.tracking.infra.repositories import SqlAlchemyTrackingUnitOfWork

#: Deliberately far from any real data so this test's partitions cannot collide with the ones
#: migration `c8b4d17e9f30` pre-created, and cannot be confused for production months.
_FAR_FUTURE = datetime(2031, 6, 15)


class VehiclePositionPartitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        if not settings.db.url:
            self.skipTest("No RAAD_DB__URL configured")
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.tag = uuid.uuid4().hex[:8]
        self._created_partitions: list[str] = []
        self._inserted_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._inserted_ids:
                await conn.execute(
                    text("DELETE FROM vehicle_positions WHERE id = ANY(:ids)"),
                    {"ids": self._inserted_ids},
                )
            for name in self._created_partitions:
                await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        await self.engine.dispose()

    def _uow(self) -> SqlAlchemyTrackingUnitOfWork:
        return SqlAlchemyTrackingUnitOfWork(
            self.session_factory, OutboxWriter(), AuditWriter()
        )

    async def _insert_position(self, event_time: datetime) -> str:
        position_id = self.ids.new_id()
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO vehicle_positions (id, organization_id, vehicle_id, "
                    "device_id, latitude, longitude, is_backfill, event_time, received_at) "
                    "VALUES (:id, :org, :veh, :dev, 2.05, 45.32, false, :et, :et)"
                ),
                {
                    "id": position_id,
                    "org": self.ids.new_id(),
                    "veh": self.ids.new_id(),
                    "dev": self.ids.new_id(),
                    "et": event_time,
                },
            )
        self._inserted_ids.append(position_id)
        return position_id

    async def _partition_of(self, position_id: str) -> str:
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT tableoid::regclass::text FROM vehicle_positions WHERE id = :id"
                ),
                {"id": position_id},
            )
            return result.scalar_one()

    async def test_the_table_is_actually_partitioned(self) -> None:
        """`relkind = 'p'` is the whole point of migration `c8b4d17e9f30`. A plain heap ('r')
        would mean the migration silently did not apply."""
        async with self.engine.connect() as conn:
            # Cast to text in SQL: `pg_class.relkind` is PostgreSQL's internal `"char"` type,
            # which asyncpg returns as `bytes` (b'p'), not `str`. Casting server-side is clearer
            # than decoding here and keeps the assertion about the value, not the driver.
            relkind = (
                await conn.execute(
                    text(
                        "SELECT relkind::text FROM pg_class "
                        "WHERE relname = 'vehicle_positions'"
                    )
                )
            ).scalar_one()
        self.assertEqual(relkind, "p")

    async def test_a_row_routes_to_its_month_partition(self) -> None:
        event_time = datetime(2026, 8, 20, 10, 30)
        position_id = await self._insert_position(event_time)
        self.assertEqual(
            await self._partition_of(position_id), "vehicle_positions_2026_08"
        )

    async def test_a_row_outside_every_month_lands_in_default_instead_of_failing(
        self,
    ) -> None:
        """**The safety net.** Without a DEFAULT partition this insert raises and the platform
        drops a real GPS fix from a moving school bus. 2099 is beyond every pre-created month."""
        position_id = await self._insert_position(datetime(2099, 1, 5, 8, 0))
        self.assertEqual(
            await self._partition_of(position_id), "vehicle_positions_default"
        )

    async def test_maintenance_provisions_months_ahead_and_is_idempotent(self) -> None:
        async with self._uow() as uow:
            created, _dropped = await uow.vehicle_positions.maintain_partitions(
                now=_FAR_FUTURE,
                months_ahead=2,
                retention_cutoff=_FAR_FUTURE - timedelta(days=3650),
            )
            await uow.commit()
        self._created_partitions.extend(created)

        # 2031-06 plus two months ahead.
        self.assertEqual(
            sorted(created),
            [
                "vehicle_positions_2031_06",
                "vehicle_positions_2031_07",
                "vehicle_positions_2031_08",
            ],
        )

        # Running again must create nothing — the job ticks on a schedule and a second run has
        # to be a no-op, or every tick would error on an already-existing partition.
        async with self._uow() as uow:
            created_again, _ = await uow.vehicle_positions.maintain_partitions(
                now=_FAR_FUTURE,
                months_ahead=2,
                retention_cutoff=_FAR_FUTURE - timedelta(days=3650),
            )
            await uow.commit()
        self.assertEqual(created_again, [])

    # ------------------------------------------------------------------------------------------
    # Drop behaviour.
    #
    # **These two tests destroyed 380,510 rows of real GPS history when first written, and the
    # shape below is what prevents that recurring.** The original versions proved "expired
    # partitions are dropped" by passing a far-*future* retention cutoff (2031, then 2099).
    # Both worked exactly as intended — and because `maintain_partitions` operates on the whole
    # table, a cutoff in the future makes *every* real monthly partition fully expired, so it
    # correctly dropped all of them and the live data with them. The production code was right;
    # the tests were the defect.
    #
    # The rule: an integration test exercising destructive DDL against a shared database must
    # only ever be able to destroy partitions it created itself. That is achieved here by
    # putting this test's own partitions in the far **past** (1990) and using a cutoff that sits
    # before every real month (1991) — so the only partitions that can possibly match are these.
    # ------------------------------------------------------------------------------------------

    async def _create_past_partition(self, year: int, month: int) -> str:
        name = f"vehicle_positions_{year}_{month:02d}"
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    f"CREATE TABLE {name} PARTITION OF vehicle_positions "
                    f"FOR VALUES FROM ('{year}-{month:02d}-01') "
                    f"TO ('{next_year}-{next_month:02d}-01')"
                )
            )
        self._created_partitions.append(name)
        return name

    async def test_only_fully_expired_partitions_are_dropped(self) -> None:
        """A partition straddling the cutoff still holds retainable data. Dropping it early
        deletes a bus's GPS history sooner than the retention policy promises — a worse failure
        than keeping it slightly longer — so the rule is deliberately conservative."""
        await self._create_past_partition(1990, 1)
        await self._create_past_partition(1990, 2)
        await self._create_past_partition(1990, 3)

        # Cutoff inside 1990-02: January is fully expired, February straddles it, March is
        # entirely after it. Nothing real is older than 1990, so nothing real can match.
        async with self._uow() as uow:
            created, dropped = await uow.vehicle_positions.maintain_partitions(
                now=_FAR_FUTURE,
                months_ahead=0,
                retention_cutoff=datetime(1990, 2, 15),
            )
            await uow.commit()
        # `months_ahead=0` still provisions `now`'s own month, so this sweep creates
        # `vehicle_positions_2031_06` as a side effect. Untracked, teardown leaks it into
        # the canonical database — an empty far-future partition nobody put there on purpose.
        self._created_partitions.extend(created)

        self.assertIn("vehicle_positions_1990_01", dropped)
        self.assertNotIn("vehicle_positions_1990_02", dropped)
        self.assertNotIn("vehicle_positions_1990_03", dropped)
        for name in dropped:
            if name in self._created_partitions:
                self._created_partitions.remove(name)

    async def test_the_default_partition_is_never_dropped(self) -> None:
        """DEFAULT is the only thing standing between a clock-skewed device and a rejected
        insert, so it must survive a sweep that expires everything around it."""
        await self._create_past_partition(1991, 1)

        async with self._uow() as uow:
            created, dropped = await uow.vehicle_positions.maintain_partitions(
                now=_FAR_FUTURE,
                months_ahead=0,
                retention_cutoff=datetime(1991, 6, 1),
            )
            await uow.commit()
        # `months_ahead=0` still provisions `now`'s own month, so this sweep creates
        # `vehicle_positions_2031_06` as a side effect. Untracked, teardown leaks it into
        # the canonical database — an empty far-future partition nobody put there on purpose.
        self._created_partitions.extend(created)

        # The sweep did fire — it removed this test's own expired partition...
        self.assertIn("vehicle_positions_1991_01", dropped)
        for name in dropped:
            if name in self._created_partitions:
                self._created_partitions.remove(name)
        # ...and left DEFAULT alone, which is the actual assertion.
        self.assertNotIn("vehicle_positions_default", dropped)

        async with self.engine.connect() as conn:
            still_there = (
                await conn.execute(
                    text("SELECT to_regclass('vehicle_positions_default')")
                )
            ).scalar()
        self.assertIsNotNone(still_there)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
