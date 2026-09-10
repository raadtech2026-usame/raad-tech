"""Alembic environment (Backend LLD §17 `db`; `.claude/rules/database.md` #1: Alembic,
revisions in `backend/migrations/versions/`).

The connection URL comes from `raad.core.config.settings` (the same `RAAD_DB__URL` used by the
running application) rather than `alembic.ini`, so there is exactly one source of DB
configuration — never two that can drift. `target_metadata` is `Base.metadata`
(`raad.core.db.base`), the single shared `MetaData` every module's ORM models register onto,
so `alembic revision --autogenerate` sees the whole schema regardless of which module defines
a given table.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from raad.core.config.settings import get_settings
from raad.core.db.base import Base

# Shared-kernel tables (not owned by any single bounded-context module — ADR-0007 for
# audit_entries; outbox registers transitively via core/di/bootstrap.py's own import chain
# today, but audit_entries is imported explicitly here rather than relying on that same
# incidental mechanism).
import raad.core.audit.writer  # noqa: F401 — registers AuditEntryRecord

# Import every module's `infra/models.py` here so their ORM classes register onto
# `Base.metadata` before autogenerate runs.
import raad.modules.iam.infra.models  # noqa: F401 — registers UserModel/RefreshTokenModel
import raad.modules.organization.infra.models  # noqa: F401 — registers OrganizationModel/RegionModel
import raad.modules.fleet_device.infra.models  # noqa: F401 — registers Vehicle/Device/Camera/DeviceAssignment models
import raad.modules.tracking.infra.models  # noqa: F401 — registers VehiclePosition/GeofenceCrossing models
import raad.modules.transport_ops.infra.models  # noqa: F401 — registers StudentModel/ParentModel
import raad.modules.billing.infra.models  # noqa: F401 — registers Plan/Subscription/Invoice/Payment/TransportFee models
import raad.modules.notifications.infra.models  # noqa: F401 — registers Notification/DeviceToken models
import raad.modules.reporting.infra.models  # noqa: F401 — registers ReportRun model
import raad.modules.video.infra.models  # noqa: F401 — registers VideoSessionModel
import raad.modules.platform_audit.infra.models  # noqa: F401 — registers SystemSettingModel
import raad.modules.school_erp.infra.models  # noqa: F401 — registers FeePlan/StudentInvoice/StudentPayment/Income/Expense/FinancialCategory models (ADR-0040)
import raad.modules.platform_finance.infra.models  # noqa: F401 — registers PlatformExpense/PlatformIncome/PlatformFinancialCategory models (ADR-0040)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    settings = get_settings()
    if not settings.db.url:
        raise RuntimeError(
            "RAAD_DB__URL is not configured — set it before running Alembic migrations."
        )
    return settings.db.url


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ANN001, ARG001
    """Audit finding B15 — hide declarative-partition *children* from autogenerate.

    `vehicle_positions` is `PARTITION BY RANGE (event_time)` with one child table per month
    (`vehicle_positions_2026_08`, ...) plus a `DEFAULT` partition. Those children are real
    tables in `pg_class`, but they exist only because the parent's partitioning scheme creates
    them — no SQLAlchemy model declares them and none ever will.

    Without this filter, autogenerate reflects all 37 of them, finds no matching model, and
    proposes `DROP TABLE` for every one — i.e. `alembic check` reports permanent false drift,
    and `alembic revision --autogenerate` would cheerfully emit a migration that deletes the
    entire GPS history. Matching on the parent's own name prefix keeps the parent itself (and
    any unrelated table) fully checked.
    """
    if type_ in ("table", "index") and name and name.startswith("vehicle_positions_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Emits SQL to stdout without a live DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Runs migrations against a live DB using the app's own async engine builder
    (`core/db/engine.build_engine`) — the async driver connection is bridged to Alembic's
    sync migration API via `AsyncConnection.run_sync`, SQLAlchemy's documented pattern for
    async-engine projects."""
    from raad.core.config.settings import DbSettings
    from raad.core.db.engine import build_engine

    engine: AsyncEngine = build_engine(DbSettings(url=get_url()))

    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
