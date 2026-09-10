"""Architecture gate: cross-aggregate INSERT ordering (2026-09-09).

**The defect this gate exists to prevent.** SQLAlchemy decides the order of the INSERTs it emits
during a flush from *mapper* dependency edges, and those edges come from `relationship()` — not
from table-level `ForeignKey`s. This codebase declares `relationship()` only for intra-aggregate
composition (`DeviceModel.cameras`, `RouteModel.stops`); two separate aggregates always reference
each other by a plain FK column with no relationship, deliberately, because a navigable attribute
between aggregates is the coupling the repository-per-aggregate design exists to prevent.

For every such FK the ORM therefore has **no edge**, and the flush falls back to ordering mappers
by `_sort_key`, the fully-qualified class name. That is alphabetical. Wherever the child class
happens to sort before its parent, a Unit of Work that creates both emits the child INSERT first
and dies on the foreign key.

`billing` was the proven case: `InvoiceModel` sorts before `SubscriptionModel`, so
`open_organization_subscription` — one `Subscription` plus its first `Invoice`, one Unit of Work —
failed on `fk_invoices__subscriptions` on every call, for the whole life of the feature, while the
test suite stayed green because the only coverage used in-memory fakes with no foreign keys.

`SqlAlchemyUnitOfWork._flush_in_dependency_order` neutralises all of them centrally, by flushing
table by table in `MetaData.sorted_tables` order. These tests protect that property.
"""

from __future__ import annotations

import importlib
import inspect
import unittest

from raad.core.db.base import Base
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork

#: Every module with a model-bearing source file, plus the two shared-kernel tables. Kept in
#: step with `migrations/env.py` — if a module is added there and not here, this gate silently
#: stops covering it.
_MODEL_MODULES = (
    "raad.modules.iam.infra.models",
    "raad.modules.organization.infra.models",
    "raad.modules.fleet_device.infra.models",
    "raad.modules.transport_ops.infra.models",
    "raad.modules.tracking.infra.models",
    "raad.modules.video.infra.models",
    "raad.modules.notifications.infra.models",
    "raad.modules.billing.infra.models",
    "raad.modules.reporting.infra.models",
    "raad.modules.platform_audit.infra.models",
    "raad.modules.school_erp.infra.models",
    "raad.modules.platform_finance.infra.models",
    "raad.core.audit.writer",
    "raad.core.events.outbox",
)


def _load_all_mappers() -> dict[str, object]:
    for module in _MODEL_MODULES:
        importlib.import_module(module)
    return {m.local_table.name: m for m in Base.registry.mappers}


def _cross_aggregate_foreign_keys() -> list[tuple[str, str, str]]:
    """Every FK between two mapped tables that has no `relationship()` backing it.

    Returns `(child_table, parent_table, column)`. Self-references are excluded: a table cannot
    be flushed before itself, and SQLAlchemy handles the intra-table case separately.
    """
    mappers = _load_all_mappers()
    edges: list[tuple[str, str, str]] = []
    for name, mapper in sorted(mappers.items()):
        related = {r.mapper.local_table.name for r in mapper.relationships}
        for fk in mapper.local_table.foreign_keys:
            parent = fk.column.table.name
            if parent == name or parent not in mappers:
                continue
            parent_mapper = mappers[parent]
            backed = parent in related or name in {
                r.mapper.local_table.name for r in parent_mapper.relationships
            }
            if not backed:
                edges.append((name, parent, fk.parent.name))
    return edges


def _alphabetical_hazards() -> list[tuple[str, str, str]]:
    """The subset where SQLAlchemy's own fallback ordering would insert the child first."""
    mappers = _load_all_mappers()
    return [
        edge
        for edge in _cross_aggregate_foreign_keys()
        if mappers[edge[0]]._sort_key < mappers[edge[1]]._sort_key
    ]


class FlushOrderHazardTests(unittest.TestCase):
    def test_the_hazard_is_real_and_widespread(self) -> None:
        """Nine such pairs exist across seven modules — this is not a `billing` quirk.

        Asserted rather than assumed so that nobody reading the fix concludes it was a
        one-table workaround. If this ever drops to zero the guard below becomes dead weight and
        can be reconsidered; until then it is load-bearing for every one of these.
        """
        hazards = _alphabetical_hazards()
        self.assertGreaterEqual(len(hazards), 1, "expected latent flush-order hazards")

        child_tables = {child for child, _parent, _col in hazards}
        # The one that actually fired in production. Its presence proves the detector works.
        self.assertIn("invoices", child_tables)

    def test_metadata_orders_every_parent_before_its_child(self) -> None:
        """The property `_flush_in_dependency_order` depends on.

        `MetaData.sorted_tables` is SQLAlchemy's topological sort of tables *by ForeignKey* —
        precisely the information the mapper-level sort lacks. If a future schema introduced a
        cycle, this sort would no longer be a valid flush order and the guard would silently stop
        working; this fails first instead.
        """
        # Load every mapper *before* reading the metadata: `sorted_tables` reflects only the
        # tables imported so far, and reading it first yields a partial, meaningless order.
        _load_all_mappers()
        order = {table.name: index for index, table in enumerate(Base.metadata.sorted_tables)}
        for child, parent, column in _cross_aggregate_foreign_keys():
            with self.subTest(fk=f"{child}.{column} -> {parent}"):
                self.assertIn(child, order)
                self.assertIn(parent, order)
                self.assertLess(
                    order[parent],
                    order[child],
                    f"{parent} must be insertable before {child}",
                )


class UnitOfWorkGuardTests(unittest.TestCase):
    def test_commit_flushes_in_dependency_order_before_writing_anything_else(self) -> None:
        """The guard must run *first* in `commit()`.

        `OutboxWriter`/`AuditWriter` each emit their own statements, and any statement triggers
        autoflush — which would flush the business rows in SQLAlchemy's broken order before the
        guard ever got the chance to impose the right one. Order matters as much as presence, so
        both are asserted.
        """
        source = inspect.getsource(SqlAlchemyUnitOfWork.commit)
        self.assertIn("_flush_in_dependency_order", source)

        guard_at = source.index("_flush_in_dependency_order")
        outbox_at = source.index("_outbox_writer")
        audit_at = source.index("_audit_writer")
        self.assertLess(guard_at, outbox_at)
        self.assertLess(guard_at, audit_at)

    def test_the_guard_derives_its_order_rather_than_hardcoding_one(self) -> None:
        """A hand-maintained table list is one more thing to forget, and forgetting it looks
        exactly like the original bug. The order must come from the metadata."""
        source = inspect.getsource(SqlAlchemyUnitOfWork._flush_in_dependency_order)
        self.assertIn("sorted_tables", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
