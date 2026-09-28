"""Application-layer tests for `ParentFinanceApplicationService` (ADR-0042, 2026-09-11 —
supersedes ADR-0041 §1's `StudentInvoice`-grouping design).

Stdlib `unittest` with in-memory fakes — no SQLAlchemy, no FastAPI, no database, mirroring
`test_school_erp_application.py`'s exact structure. `ParentApplicationService`/
`StudentParentApplicationService` (owned by `transport_ops`) are faked here as simple
fixture-driven stand-ins, not real instances — this service only calls their public async methods
(`get_parent_by_id`/`list_parents_by_ids`/`list_students_for_parent`), never their domain/infra.

**The invariant this file exists to protect**: a "Parent Invoice" is a real, persisted
`ParentInvoice` row — one per family per period, generated directly from a `ParentBillingProfile`,
never a grouping of per-student rows. Tests below prove: one invoice regardless of child count,
an equal-split allocation that always sums back to the family total, idempotent monthly
generation, a frozen historical amount that a later fee change cannot rewrite, the exact
ADR-0047 payment ledger (allocation, over/duplicate-payment guards, void reversal), and that one family's data never leaks into
another's summary or listing.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
    RuleViolationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.school_erp.application.commands import (
    CancelParentInvoiceCommand,
    CreateOrUpdateParentBillingProfileCommand,
    GenerateParentInvoicesCommand,
    SetParentBillingProfileStatusCommand,
    SetStudentBillingFeeCommand,
    PaymentAllocationRequest,
    RecordParentPaymentCommand,
    VoidParentPaymentCommand,
)
from raad.modules.school_erp.application.ports import (
    StudentTransportContext,
    StudentTransportContextPort,
)
from raad.modules.school_erp.application.services import ParentFinanceApplicationService
from raad.modules.school_erp.domain.entities import ParentBillingProfile, ParentInvoice
from raad.modules.school_erp.domain.repositories import (
    ParentBillingProfileRepository,
    ParentInvoiceRepository,
)
from _school_erp_ledger_fakes import (
    InMemoryStudentBillingProfileRepository,
    billed_student_ids,
    InMemoryParentPaymentRepository,
    invoices_for_student,
    summarise_lines_by_vehicle,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    ParentBillingProfileId,
    ParentBillingProfileStatus,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
)

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ZT"
PARENT_A = "01J8Z3K9G6X8YV5T4N2R7QPRTA"
PARENT_B = "01J8Z3K9G6X8YV5T4N2R7QPRTB"
STUDENT_A1 = "01J8Z3K9G6X8YV5T4N2R7QSTA1"
STUDENT_A2 = "01J8Z3K9G6X8YV5T4N2R7QSTA2"
STUDENT_B1 = "01J8Z3K9G6X8YV5T4N2R7QSTB1"
STUDENT_A3 = "01J8Z3K9G6X8YV5T4N2R7QSTA3"
BUS_1 = "01J8Z3K9G6X8YV5T4N2R7QBS01"
BUS_2 = "01J8Z3K9G6X8YV5T4N2R7QBS02"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, now: datetime) -> None:
        self._now = now


CLOCK = FixedClock(datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def make_actor(role: Role = Role.ORG_ADMIN, org_id: str = ORG) -> Principal:
    return Principal(user_id="admin-1", role=role, org_id=org_id)


def _paginate(items: list, page_request: OffsetPageRequest) -> OffsetPage:
    items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    return OffsetPage(
        data=items[start : start + page_request.page_size],
        total=total,
        page=page_request.page,
        page_size=page_request.page_size,
    )


# ---- Fakes: this module's own two repositories -------------------------------------------------


class InMemoryParentBillingProfileRepository(ParentBillingProfileRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, ParentBillingProfile] = {}

    async def get(self, profile_id: ParentBillingProfileId) -> ParentBillingProfile | None:
        return self.by_id.get(str(profile_id))

    async def get_by_parent(self, parent_id: ParentId) -> ParentBillingProfile | None:
        return next(
            (p for p in self.by_id.values() if str(p.parent_id) == str(parent_id)), None
        )

    def add(self, profile: ParentBillingProfile) -> None:
        self.by_id[str(profile.id)] = profile

    async def list_page(self, page_request, *, filters, sort, search) -> OffsetPage:
        return _paginate(list(self.by_id.values()), page_request)

    async def list_active_for_billing(
        self, *, as_of_period: BillingPeriod
    ) -> list[ParentBillingProfile]:
        return [
            p
            for p in self.by_id.values()
            if p.status is ParentBillingProfileStatus.ACTIVE
            and str(p.billing_start_period) <= str(as_of_period)
        ]


class InMemoryParentInvoiceRepository(ParentInvoiceRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, ParentInvoice] = {}

    async def get(self, invoice_id: ParentInvoiceId) -> ParentInvoice | None:
        return self.by_id.get(str(invoice_id))

    async def get_by_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> ParentInvoice | None:
        return next(
            (
                i
                for i in self.by_id.values()
                if str(i.parent_id) == str(parent_id) and str(i.period) == str(period)
            ),
            None,
        )

    async def billed_student_ids_for_period(self, *, period: BillingPeriod) -> set[str]:
        return billed_student_ids(self.by_id.values(), period)

    async def exists_for_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> bool:
        return any(
            str(i.parent_id) == str(parent_id)
            and str(i.period) == str(period)
            and i.status is not ParentInvoiceStatus.CANCELLED
            for i in self.by_id.values()
        )

    def add(self, invoice: ParentInvoice) -> None:
        self.by_id[str(invoice.id)] = invoice

    async def list_page(self, page_request, *, filters: list[FilterCondition], sort, search) -> OffsetPage:
        items = list(self.by_id.values())
        for condition in filters:
            if condition.op != "eq":
                continue
            if condition.field == "period":
                items = [i for i in items if str(i.period) == condition.value]
            elif condition.field == "parent_id":
                items = [i for i in items if str(i.parent_id) == condition.value]
            elif condition.field == "status":
                items = [i for i in items if i.status.value == condition.value]
        return _paginate(items, page_request)

    async def list_for_parent(self, parent_id: ParentId) -> list[ParentInvoice]:
        return [i for i in self.by_id.values() if str(i.parent_id) == str(parent_id)]

    async def summarise_totals(self, *, period=None):
        raise NotImplementedError("not exercised by this test file")

    async def list_for_student(self, student_id):
        return invoices_for_student(self.by_id.values(), student_id)

    async def summarise_lines_by_vehicle_between(self, *, start, end):
        return summarise_lines_by_vehicle(self.by_id.values(), start=start, end=end)

    async def currencies_for_period(self, *, period=None):
        raise NotImplementedError("not exercised by this test file")

    async def currencies_invoiced_between(self, *, start, end):
        raise NotImplementedError("not exercised by this test file")


class FakeSchoolErpUnitOfWork:
    """Bundles only the repositories the parent-level use cases here read/write — billing
    profiles, invoices and the ADR-0047 payment ledger."""

    def __init__(self) -> None:
        self.parent_billing_profiles = InMemoryParentBillingProfileRepository()
        self.student_billing_profiles = InMemoryStudentBillingProfileRepository()
        self.parent_invoices = InMemoryParentInvoiceRepository()
        self.parent_payments = InMemoryParentPaymentRepository()
        self.recorded_events: list = []
        self.commit_count = 0

    async def __aenter__(self) -> "FakeSchoolErpUnitOfWork":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class FakeTransportOpsUnitOfWork:
    """A no-op stand-in — every call site that takes this parameter only forwards it to a fake
    `ParentApplicationService`/`StudentParentApplicationService` method below, neither of which
    actually reads it."""

    async def __aenter__(self) -> "FakeTransportOpsUnitOfWork":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


@dataclass
class FakeParent:
    id: str
    organization_id: str
    full_name: str


@dataclass
class FakeChild:
    student_id: str
    full_name: str
    status: str = "active"
    is_primary: bool = True


class FakeParentApplicationService:
    """Stands in for `transport_ops.ParentApplicationService` — only the two methods
    `ParentFinanceApplicationService` actually calls."""

    def __init__(self, parents: dict[str, FakeParent]) -> None:
        self._parents = parents

    async def get_parent_by_id(self, query, *, uow):
        parent = self._parents.get(query.parent_id)
        if parent is None:
            raise NotFoundError(f"Parent {query.parent_id!r} not found")
        return parent

    async def list_parents_by_ids(self, parent_ids, *, uow):
        return [self._parents[pid] for pid in parent_ids if pid in self._parents]


class FakeStudentParentApplicationService:
    """Stands in for `transport_ops.StudentParentApplicationService` — only
    `list_students_for_parent`, the one method `ParentFinanceApplicationService` calls."""

    def __init__(self, children_by_parent: dict[str, list[FakeChild]]) -> None:
        self._children_by_parent = children_by_parent

    async def list_students_for_parent(self, query, *, uow):
        return list(self._children_by_parent.get(query.parent_id, []))


@dataclass
class FakeStudent:
    id: str
    organization_id: str
    full_name: str
    status: str = "active"


class FakeStudentApplicationService:
    """Stands in for `transport_ops.StudentApplicationService` — `get_student_by_id` is what
    404s a student outside the caller's scope before a fee is set (ADR-0048)."""

    def __init__(self, students: dict[str, FakeStudent]) -> None:
        self._students = students

    async def get_student_by_id(self, query, *, uow):
        student = self._students.get(query.student_id)
        if student is None:
            raise NotFoundError(f"Student {query.student_id!r} not found")
        return student


class FakeTransportContextPort(StudentTransportContextPort):
    def __init__(self, mapping: dict[str, StudentTransportContext] | None = None) -> None:
        self.mapping = mapping or {}

    async def resolve(self, *, student_id: str) -> StudentTransportContext:
        return self.mapping.get(student_id, StudentTransportContext())

    async def resolve_many(self, *, student_ids: list[str]):
        return {sid: self.mapping[sid] for sid in student_ids if sid in self.mapping}


def make_service(
    *,
    parents: dict[str, FakeParent],
    children_by_parent: dict[str, list[FakeChild]],
    transport: StudentTransportContextPort | None = None,
    students: dict[str, FakeStudent] | None = None,
) -> ParentFinanceApplicationService:
    return ParentFinanceApplicationService(
        clock=CLOCK,
        id_generator=SequentialIdGenerator(),
        parent_service=FakeParentApplicationService(parents),
        student_parent_service=FakeStudentParentApplicationService(children_by_parent),
        transport_context=transport,
        student_service=FakeStudentApplicationService(students or {}),
    )


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.parents = {
            PARENT_A: FakeParent(id=PARENT_A, organization_id=ORG, full_name="Ahmed Mohamed"),
            PARENT_B: FakeParent(id=PARENT_B, organization_id=ORG, full_name="Hassan Ali"),
        }
        self.children = {
            PARENT_A: [
                FakeChild(student_id=STUDENT_A1, full_name="Mohamed"),
                FakeChild(student_id=STUDENT_A2, full_name="Aisha"),
            ],
            PARENT_B: [FakeChild(student_id=STUDENT_B1, full_name="Yusuf")],
        }
        self.transport = FakeTransportContextPort(
            {
                STUDENT_A1: StudentTransportContext(vehicle_id=BUS_1, route_id="route-1"),
                STUDENT_A2: StudentTransportContext(vehicle_id=BUS_1, route_id="route-1"),
                STUDENT_B1: StudentTransportContext(vehicle_id=BUS_2),
            }
        )
        self.students = {
            child.student_id: FakeStudent(
                id=child.student_id, organization_id=ORG, full_name=child.full_name
            )
            for children in self.children.values()
            for child in children
        }
        self.service = make_service(
            parents=self.parents,
            children_by_parent=self.children,
            transport=self.transport,
            students=self.students,
        )
        self.school_erp_uow = FakeSchoolErpUnitOfWork()
        self.transport_ops_uow = FakeTransportOpsUnitOfWork()
        self.actor = make_actor()

    async def _set_fee(self, student_id: str, fee: str, *, currency: str = "USD"):
        return await self.service.set_student_billing_fee(
            SetStudentBillingFeeCommand(
                student_id=student_id, monthly_fee=fee, currency=currency, actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )

    async def _open_profile(
        self,
        parent_id: str = PARENT_A,
        *,
        per_child: str | dict[str, str] | None = "40.00",
        billing_start_period: str = "2026-09",
        due_day: int = 10,
        currency: str = "USD",
    ) -> ParentBillingProfile:
        """Opens the family's billing account and prices each of its children (ADR-0048):
        `per_child` is one fee for every child, a `{student_id: fee}` map, or `None` to leave
        the children unpriced."""
        if per_child is not None:
            for child in self.children.get(parent_id, []):
                fee = per_child if isinstance(per_child, str) else per_child.get(child.student_id)
                if fee is not None:
                    await self._set_fee(child.student_id, fee, currency=currency)
        dto = await self.service.create_or_update_billing_profile(
            CreateOrUpdateParentBillingProfileCommand(
                organization_id=ORG,
                parent_id=parent_id,
                currency=currency,
                billing_start_period=billing_start_period,
                due_day=due_day,
                actor=self.actor,
            ),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        return await self.school_erp_uow.parent_billing_profiles.get(
            ParentBillingProfileId(dto.id)
        )

    async def _generate(self, period: str = "2026-09"):
        return await self.service.generate_parent_invoices(
            GenerateParentInvoicesCommand(organization_id=ORG, period=period, actor=self.actor),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )

    async def _pay(
        self,
        invoice_id: str,
        amount: str,
        *,
        allocations: dict[str, str] | None = None,
        key: str | None = None,
        actor: Principal | None = None,
        currency: str = "USD",
        received_on: date = date(2026, 9, 12),
    ):
        return await self.service.record_parent_payment(
            RecordParentPaymentCommand(
                invoice_id=invoice_id,
                amount=amount,
                currency=currency,
                method="cash",
                received_on=received_on,
                reference="RCPT-1",
                notes=None,
                allocations=(
                    tuple(
                        PaymentAllocationRequest(student_id=sid, amount=value)
                        for sid, value in allocations.items()
                    )
                    if allocations is not None
                    else None
                ),
                idempotency_key=key,
                actor=actor or self.actor,
            ),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )

    async def _void(self, payment_id: str, reason: str | None = "Bounced cheque"):
        return await self.service.void_parent_payment(
            VoidParentPaymentCommand(payment_id=payment_id, reason=reason, actor=self.actor),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )

    async def _stored(self, invoice_id: str):
        return await self.school_erp_uow.parent_invoices.get(ParentInvoiceId(invoice_id))


# ---- ParentBillingProfile -----------------------------------------------------------------------


class BillingProfileTests(_Base):
    async def test_create_billing_profile(self) -> None:
        profile = await self._open_profile()
        self.assertEqual(profile.currency, "USD")
        self.assertEqual(profile.due_day, 10)
        self.assertIs(profile.status, ParentBillingProfileStatus.ACTIVE)
        self.assertFalse(hasattr(profile, "monthly_fee"), "the account carries no family fee")

    async def test_updating_an_existing_profile_edits_in_place_no_duplicate(self) -> None:
        await self._open_profile(per_child="40.00")
        await self._open_profile(per_child="50.00", due_day=15, billing_start_period="2026-10")

        self.assertEqual(len(self.school_erp_uow.parent_billing_profiles.by_id), 1)
        profile = await self.school_erp_uow.parent_billing_profiles.get_by_parent(
            ParentId(PARENT_A)
        )
        self.assertEqual(profile.due_day, 15)
        self.assertEqual(str(profile.billing_start_period), "2026-10")
        self.assertEqual(len(self.school_erp_uow.student_billing_profiles.by_id), 2)

    async def test_parent_belonging_to_another_organization_is_rejected(self) -> None:
        with self.assertRaises(DomainError):
            await self.service.create_or_update_billing_profile(
                CreateOrUpdateParentBillingProfileCommand(
                    organization_id=OTHER_ORG,
                    parent_id=PARENT_A,
                    currency="USD",
                    billing_start_period="2026-09",
                    due_day=10,
                    actor=make_actor(org_id=OTHER_ORG),
                ),
                school_erp_uow=self.school_erp_uow,
                transport_ops_uow=self.transport_ops_uow,
            )

    async def test_unknown_parent_is_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self.service.create_or_update_billing_profile(
                CreateOrUpdateParentBillingProfileCommand(
                    organization_id=ORG,
                    parent_id="01J8Z3K9G6X8YV5T4N2R7QUNKN",
                    currency="USD",
                    billing_start_period="2026-09",
                    due_day=10,
                    actor=self.actor,
                ),
                school_erp_uow=self.school_erp_uow,
                transport_ops_uow=self.transport_ops_uow,
            )

    async def test_deactivate_then_reactivate(self) -> None:
        profile = await self._open_profile()
        await self.service.set_billing_profile_status(
            SetParentBillingProfileStatusCommand(
                billing_profile_id=str(profile.id), is_active=False, actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
        )
        stored = await self.school_erp_uow.parent_billing_profiles.get(profile.id)
        self.assertIs(stored.status, ParentBillingProfileStatus.INACTIVE)

        await self.service.set_billing_profile_status(
            SetParentBillingProfileStatusCommand(
                billing_profile_id=str(profile.id), is_active=True, actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
        )
        stored = await self.school_erp_uow.parent_billing_profiles.get(profile.id)
        self.assertIs(stored.status, ParentBillingProfileStatus.ACTIVE)

    async def test_editing_the_fee_never_rewrites_an_already_generated_invoice(self) -> None:
        """September at $40 a child, October onward at $50: September's invoice stays $80. The
        line amounts are frozen at generation, never re-read from the student's fee."""
        await self._open_profile(per_child="40.00")
        (september,) = await self._generate(period="2026-09")
        self.assertEqual(september.amount, "80.00")

        await self._open_profile(per_child="50.00")

        stored_september = await self.school_erp_uow.parent_invoices.get(
            ParentInvoiceId(september.id)
        )
        self.assertEqual(stored_september.amount.amount, Decimal("80.00"))

        (october,) = await self._generate(period="2026-10")
        self.assertEqual(october.amount, "100.00")


# ---- Monthly generation -------------------------------------------------------------------------


class GenerateParentInvoicesTests(_Base):
    async def test_one_invoice_per_parent_regardless_of_child_count(self) -> None:
        """PARENT_A has two children — must produce exactly one ParentInvoice, never two."""
        await self._open_profile(PARENT_A, per_child="40.00")
        invoices = await self._generate()

        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0].amount, "80.00")
        self.assertEqual(len(invoices[0].lines), 2)

    async def test_each_line_is_its_own_students_fee_and_the_total_is_their_sum(self) -> None:
        """ADR-0048: no family figure is split. Two children priced differently get different
        lines, and the invoice total is exactly their sum."""
        await self._open_profile(PARENT_A, per_child={STUDENT_A1: "10.00", STUDENT_A2: "20.00"})
        (invoice,) = await self._generate()

        self.assertEqual(
            {line.student_id: line.amount for line in invoice.lines},
            {STUDENT_A1: "10.00", STUDENT_A2: "20.00"},
        )
        self.assertEqual(invoice.amount, "30.00")
        self.assertEqual({line.balance_due for line in invoice.lines}, {"10.00", "20.00"})

    async def test_transport_context_is_captured_on_each_line(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        (invoice,) = await self._generate()

        by_student = {line.student_id: line for line in invoice.lines}
        self.assertEqual(by_student[STUDENT_A1].vehicle_id, BUS_1)
        self.assertEqual(by_student[STUDENT_A2].vehicle_id, BUS_1)

    async def test_rerunning_the_same_period_is_idempotent(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        first = await self._generate()
        second = await self._generate()

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(len(self.school_erp_uow.parent_invoices.by_id), 1)

    async def test_a_profile_whose_billing_has_not_started_yet_is_skipped(self) -> None:
        await self._open_profile(PARENT_A, billing_start_period="2026-11")
        invoices = await self._generate(period="2026-09")
        self.assertEqual(invoices, [])

    async def test_an_inactive_profile_is_skipped(self) -> None:
        profile = await self._open_profile(PARENT_A)
        await self.service.set_billing_profile_status(
            SetParentBillingProfileStatusCommand(
                billing_profile_id=str(profile.id), is_active=False, actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
        )
        invoices = await self._generate()
        self.assertEqual(invoices, [])

    async def test_a_parent_with_no_active_children_is_skipped(self) -> None:
        self.children[PARENT_A] = [
            FakeChild(student_id=STUDENT_A1, full_name="Mohamed", status="graduated")
        ]
        await self._open_profile(PARENT_A)
        invoices = await self._generate()
        self.assertEqual(invoices, [])

    async def test_two_families_each_get_their_own_invoice_in_one_run(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")

        invoices = await self._generate()
        by_parent = {inv.parent_id: inv for inv in invoices}
        self.assertEqual(len(invoices), 2)
        self.assertEqual(by_parent[PARENT_A].amount, "80.00")
        self.assertEqual(by_parent[PARENT_B].amount, "50.00")


# ---- Payment ledger (ADR-0047 — replaces ADR-0042 §4's Unpaid/Partial/Paid control) ---------


class ParentPaymentTests(_Base):
    """PARENT_A has two children on one $80 invoice ($40 each). Every test here asserts the
    same two invariants from a different direction: the invoice's paid amount is always the sum
    of its students' paid amounts, and money is never recorded twice or beyond what is owed."""

    async def asyncSetUp(self) -> None:
        super().setUp()
        await self._open_profile(PARENT_A, per_child="40.00")
        (self.invoice,) = await self._generate()
        self.lines = {line.student_id: line for line in self.invoice.lines}

    async def test_a_payment_without_an_allocation_is_split_pro_rata(self) -> None:
        payment = await self._pay(self.invoice.id, "30.00")
        split = {a.student_id: a.amount for a in payment.allocations}
        self.assertEqual(split, {STUDENT_A1: "15.00", STUDENT_A2: "15.00"})

        stored = await self._stored(self.invoice.id)
        self.assertIs(stored.status, ParentInvoiceStatus.PARTIAL)
        self.assertEqual(stored.amount_paid, Decimal("30.00"))
        self.assertEqual(
            sum((line.amount_paid for line in stored.lines), Decimal("0.00")), Decimal("30.00")
        )

    async def test_a_payment_for_one_student_only_touches_that_students_line(self) -> None:
        await self._pay(self.invoice.id, "40.00", allocations={STUDENT_A2: "40.00"})
        stored = await self._stored(self.invoice.id)
        by_student = {str(line.student_id): line for line in stored.lines}
        self.assertEqual(by_student[STUDENT_A2].balance_due, Decimal("0.00"))
        self.assertEqual(by_student[STUDENT_A1].balance_due, Decimal("40.00"))
        self.assertIs(stored.status, ParentInvoiceStatus.PARTIAL)

    async def test_paying_every_student_settles_the_invoice(self) -> None:
        await self._pay(self.invoice.id, "40.00", allocations={STUDENT_A1: "40.00"})
        await self._pay(self.invoice.id, "40.00", allocations={STUDENT_A2: "40.00"})
        stored = await self._stored(self.invoice.id)
        self.assertIs(stored.status, ParentInvoiceStatus.PAID)
        self.assertEqual(stored.balance_due, Decimal("0.00"))

    async def test_an_already_paid_invoice_refuses_another_payment(self) -> None:
        """The P0.1 duplicate-payment guard, applied to school finance."""
        await self._pay(self.invoice.id, "80.00")
        with self.assertRaises(ConflictError):
            await self._pay(self.invoice.id, "10.00")
        self.assertEqual(len(self.school_erp_uow.parent_payments.by_id), 1)

    async def test_overpayment_is_refused_and_leaves_nothing_behind(self) -> None:
        with self.assertRaises(DomainError):
            await self._pay(self.invoice.id, "80.01")
        with self.assertRaises(DomainError):
            await self._pay(self.invoice.id, "41.00", allocations={STUDENT_A1: "41.00"})
        stored = await self._stored(self.invoice.id)
        self.assertEqual(stored.amount_paid, Decimal("0.00"))
        self.assertEqual(self.school_erp_uow.parent_payments.by_id, {})

    async def test_a_currency_mismatch_is_refused(self) -> None:
        with self.assertRaises(DomainError):
            await self._pay(self.invoice.id, "10.00", currency="SOS")
        self.assertEqual(self.school_erp_uow.parent_payments.by_id, {})

    async def test_allocations_must_add_up_to_the_payment(self) -> None:
        with self.assertRaises(DomainError):
            await self._pay(
                self.invoice.id, "30.00", allocations={STUDENT_A1: "10.00", STUDENT_A2: "10.00"}
            )

    async def test_a_student_not_on_the_invoice_cannot_be_allocated_to(self) -> None:
        with self.assertRaises(DomainError):
            await self._pay(self.invoice.id, "10.00", allocations={STUDENT_B1: "10.00"})

    async def test_a_cancelled_invoice_refuses_payment(self) -> None:
        await self.service.cancel_parent_invoice(
            CancelParentInvoiceCommand(invoice_id=self.invoice.id, reason="Error", actor=self.actor),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        with self.assertRaises(RuleViolationError):
            await self._pay(self.invoice.id, "10.00")

    async def test_resubmitting_the_same_idempotency_key_records_one_payment(self) -> None:
        first = await self._pay(self.invoice.id, "20.00", key="form-4f9a2c1e")
        second = await self._pay(self.invoice.id, "20.00", key="form-4f9a2c1e")
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.school_erp_uow.parent_payments.by_id), 1)
        self.assertEqual((await self._stored(self.invoice.id)).amount_paid, Decimal("20.00"))

    async def test_voiding_reverses_exactly_that_payment(self) -> None:
        first = await self._pay(self.invoice.id, "40.00", allocations={STUDENT_A1: "40.00"})
        await self._pay(self.invoice.id, "20.00", allocations={STUDENT_A2: "20.00"})
        voided = await self._void(first.id)
        self.assertTrue(voided.is_voided)
        self.assertEqual(voided.voided_reason, "Bounced cheque")

        stored = await self._stored(self.invoice.id)
        by_student = {str(line.student_id): line for line in stored.lines}
        self.assertEqual(by_student[STUDENT_A1].amount_paid, Decimal("0.00"))
        self.assertEqual(by_student[STUDENT_A2].amount_paid, Decimal("20.00"))
        self.assertIs(stored.status, ParentInvoiceStatus.PARTIAL)

    async def test_voiding_twice_never_reverses_twice(self) -> None:
        payment = await self._pay(self.invoice.id, "40.00")
        await self._void(payment.id)
        await self._void(payment.id)
        self.assertEqual((await self._stored(self.invoice.id)).amount_paid, Decimal("0.00"))

    async def test_voiding_requires_a_reason(self) -> None:
        payment = await self._pay(self.invoice.id, "40.00")
        with self.assertRaises(DomainError):
            await self._void(payment.id, reason="  ")
        self.assertEqual((await self._stored(self.invoice.id)).amount_paid, Decimal("40.00"))

    async def test_org_admin_cannot_pay_or_void_another_organizations_invoice(self) -> None:
        with self.assertRaises(AuthorizationError):
            await self._pay(self.invoice.id, "10.00", actor=make_actor(org_id=OTHER_ORG))
        payment = await self._pay(self.invoice.id, "10.00")
        with self.assertRaises(AuthorizationError):
            await self.service.void_parent_payment(
                VoidParentPaymentCommand(
                    payment_id=payment.id, reason="x", actor=make_actor(org_id=OTHER_ORG)
                ),
                school_erp_uow=self.school_erp_uow,
                transport_ops_uow=self.transport_ops_uow,
            )

    async def test_payment_events_carry_the_per_student_split_for_the_audit_trail(self) -> None:
        await self._pay(self.invoice.id, "30.00")
        recorded = [
            e for e in self.school_erp_uow.recorded_events
            if e.event_type == "school_erp.ParentPaymentRecorded"
        ]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(
            {a["student_id"] for a in recorded[0].payload["allocations"]},
            {STUDENT_A1, STUDENT_A2},
        )
        self.assertEqual(recorded[0].payload["actor_id"], self.actor.user_id)

    async def test_family_summary_uses_each_childs_real_paid_amount(self) -> None:
        await self._pay(self.invoice.id, "40.00", allocations={STUDENT_A1: "40.00"})
        summary = await self.service.get_parent_financial_summary(
            PARENT_A, school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow
        )
        children = {child.student_id: child for child in summary.children}
        self.assertEqual(children[STUDENT_A1].total_paid, "40.00")
        self.assertEqual(children[STUDENT_A1].outstanding, "0.00")
        self.assertEqual(children[STUDENT_A2].total_paid, "0.00")
        self.assertEqual(children[STUDENT_A2].outstanding, "40.00")
        self.assertEqual(summary.total_paid, "40.00")

    async def test_listing_a_familys_payments_names_each_child(self) -> None:
        await self._pay(self.invoice.id, "30.00")
        payments = await self.service.list_parent_payments(
            PARENT_A, school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow
        )
        self.assertEqual(len(payments), 1)
        self.assertEqual({a.full_name for a in payments[0].allocations}, {"Mohamed", "Aisha"})
        self.assertEqual(payments[0].period, "2026-09")


class CancelInvoiceTests(_Base):
    async def asyncSetUp(self) -> None:
        super().setUp()
        await self._open_profile(PARENT_A, per_child="40.00")
        (self.invoice,) = await self._generate()

    async def test_cancel_an_unpaid_invoice(self) -> None:
        updated = await self.service.cancel_parent_invoice(
            CancelParentInvoiceCommand(
                invoice_id=self.invoice.id, reason="Issued in error", actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(updated.status, "cancelled")

    async def test_cannot_cancel_an_invoice_that_has_received_payment(self) -> None:
        await self._pay(self.invoice.id, "10.00")
        with self.assertRaises(RuleViolationError):
            await self.service.cancel_parent_invoice(
                CancelParentInvoiceCommand(
                    invoice_id=self.invoice.id, reason=None, actor=self.actor
                ),
                school_erp_uow=self.school_erp_uow,
                transport_ops_uow=self.transport_ops_uow,
            )

    async def test_voiding_every_payment_makes_the_invoice_cancellable_again(self) -> None:
        payment = await self._pay(self.invoice.id, "10.00")
        await self._void(payment.id)
        updated = await self.service.cancel_parent_invoice(
            CancelParentInvoiceCommand(
                invoice_id=self.invoice.id, reason="Family withdrew", actor=self.actor
            ),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(updated.status, "cancelled")

    async def test_a_cancelled_period_can_be_regenerated(self) -> None:
        """Idempotency is keyed off *non-cancelled* invoices only — cancelling one and
        re-running generation for that period must produce a fresh invoice, not skip it."""
        await self.service.cancel_parent_invoice(
            CancelParentInvoiceCommand(invoice_id=self.invoice.id, reason=None, actor=self.actor),
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        regenerated = await self._generate()
        self.assertEqual(len(regenerated), 1)
        self.assertNotEqual(regenerated[0].id, self.invoice.id)


# ---- Financial summary / listing ----------------------------------------------------------------


class FinancialSummaryTests(_Base):
    async def test_summary_aggregates_across_periods(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        (september,) = await self._generate(period="2026-09")
        await self._pay(september.id, "80.00")
        await self._generate(period="2026-10")  # left unpaid

        summary = await self.service.get_parent_financial_summary(
            PARENT_A,
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(summary.total_due, "160.00")
        self.assertEqual(summary.total_paid, "80.00")
        self.assertEqual(summary.outstanding, "80.00")
        self.assertEqual(summary.status, "partially_paid")

    async def test_a_family_with_no_invoices_reports_no_invoices_not_unpaid(self) -> None:
        summary = await self.service.get_parent_financial_summary(
            PARENT_A,
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(summary.status, "no_invoices")
        self.assertEqual(summary.total_due, "0.00")

    async def test_family_isolation_another_parents_invoice_is_invisible(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="999.00")
        await self._generate()

        summary = await self.service.get_parent_financial_summary(
            PARENT_A,
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(summary.total_due, "80.00")


    async def test_a_family_billed_in_two_currencies_is_refused_not_summed(self) -> None:
        """Finance P0.5: USD 80 + SOS 9000 must not be reported as one "9080.00" total."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._generate(period="2026-09")
        await self._open_profile(PARENT_A, per_child="4500.00", currency="SOS")
        await self._generate(period="2026-10")

        with self.assertRaises(ConflictError):
            await self.service.get_parent_financial_summary(
                PARENT_A,
                school_erp_uow=self.school_erp_uow,
                transport_ops_uow=self.transport_ops_uow,
            )


class ListParentInvoicesTests(_Base):
    async def test_filters_by_period_and_parent(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")
        await self._generate(period="2026-09")

        page = await self.service.list_parent_invoices(
            page=1, page_size=25, period="2026-09", status=None, parent_id=PARENT_A,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].parent_id, PARENT_A)
        self.assertEqual(page.data[0].parent_name, "Ahmed Mohamed")
        self.assertEqual(page.data[0].children_count, 2)

    async def test_filters_by_vehicle_id(self) -> None:
        """`vehicle_id` lives on the invoice's own lines, not the invoice — PARENT_A's children
        ride BUS_1, PARENT_B's rides BUS_2 (see `setUp`)."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")
        await self._generate(period="2026-09")

        bus_1_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(bus_1_page.total, 1)
        self.assertEqual(bus_1_page.data[0].parent_id, PARENT_A)

        bus_2_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_2,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(bus_2_page.total, 1)
        self.assertEqual(bus_2_page.data[0].parent_id, PARENT_B)

    async def test_matches_when_only_one_currently_assigned_child_has_a_resolvable_vehicle(
        self,
    ) -> None:
        """A family whose children don't *all* currently resolve a vehicle (e.g. one child's own
        assignment hasn't been created yet) still matches on whichever one does — the same
        "any currently-assigned child's vehicle is the family's vehicle" resolution
        `set_family_transportation`'s own consistency guarantee makes safe."""
        # STUDENT_A2 has no entry in `self.transport.mapping` at all - an ordinary "not assigned
        # yet" child, distinct from a stale/removed assignment.
        del self.transport.mapping[STUDENT_A2]
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._generate(period="2026-09")

        page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].parent_id, PARENT_A)

    async def test_vehicle_filter_uses_the_familys_current_vehicle_not_the_frozen_invoice_line(
        self,
    ) -> None:
        """The regression this fix closes: a family's invoice line freezes the vehicle at issue
        time (ADR-0040 §3), but the Vehicle filter is discovery, not accounting — it must reflect
        where the family rides *today*, even after `set_family_transportation` moves them to a
        different bus post-issuance. Simulates that move by mutating the transport-context fake
        after generation (mirroring `set_family_transportation`'s own real-world effect on what
        `TransportOpsStudentContextAdapter.resolve_many` next returns)."""
        await self._open_profile(PARENT_A, per_child="40.00")
        (generated,) = await self._generate(period="2026-09")
        self.assertEqual(generated.lines[0].vehicle_id, BUS_1)  # frozen at issue time

        # The family is reassigned to BUS_2 *after* the invoice above already exists.
        self.transport.mapping[STUDENT_A1] = StudentTransportContext(vehicle_id=BUS_2)
        self.transport.mapping[STUDENT_A2] = StudentTransportContext(vehicle_id=BUS_2)

        current_bus_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_2,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(current_bus_page.total, 1)
        self.assertEqual(current_bus_page.data[0].parent_id, PARENT_A)

        stale_bus_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(stale_bus_page.total, 0)

        # The historical record itself is never rewritten - only the filter's own resolution.
        detail = await self.service.get_parent_invoice_detail(
            generated.id,
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(detail.lines[0].vehicle_id, BUS_1)

    async def test_all_vehicles_returns_every_family(self) -> None:
        """`vehicle_id=None` ("All Vehicles") — every family's invoice is visible, regardless of
        which vehicle their children ride."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")
        await self._generate(period="2026-09")

        page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=None,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(page.total, 2)
        self.assertEqual({row.parent_id for row in page.data}, {PARENT_A, PARENT_B})

    async def test_vehicle_with_no_matching_family_returns_an_empty_page(self) -> None:
        """A vehicle no family is currently assigned to — an honest empty result, never someone
        else's invoices."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._generate(period="2026-09")

        page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None,
            vehicle_id="01J8Z3K9G6X8YV5T4N2R7QBSNO",  # a real-shaped id nobody rides
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(page.total, 0)
        self.assertEqual(page.data, [])

    async def test_vehicle_filter_never_changes_the_invoice_amount(self) -> None:
        """Filtering by Vehicle is discovery only — it must never split, allocate, or otherwise
        touch a family's own frozen invoice amount/paid/balance."""
        await self._open_profile(PARENT_A, per_child="40.00")
        (unfiltered,) = await self._generate(period="2026-09")

        page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(page.total, 1)
        filtered = page.data[0]
        self.assertEqual(filtered.amount, unfiltered.amount)
        self.assertEqual(filtered.amount_paid, unfiltered.amount_paid)
        self.assertEqual(filtered.balance_due, unfiltered.balance_due)
        self.assertEqual(filtered.amount, "80.00")

    async def test_combines_vehicle_with_status_filter(self) -> None:
        """Vehicle AND Status apply together — never Vehicle overriding Status or vice versa."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")
        generated = await self._generate(period="2026-09")
        invoice_a = next(inv for inv in generated if inv.parent_id == PARENT_A)

        await self._pay(invoice_a.id, "80.00")

        paid_bus_1 = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status="paid", parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(paid_bus_1.total, 1)
        self.assertEqual(paid_bus_1.data[0].parent_id, PARENT_A)

        # Same vehicle, but the *other* status — PARENT_A is no longer unpaid, so this must be
        # empty, not a stale match from the Vehicle half alone.
        unpaid_bus_1 = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status="unpaid", parent_id=None, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(unpaid_bus_1.total, 0)

    async def test_combines_vehicle_with_parent_filter(self) -> None:
        """Vehicle AND Parent search apply together."""
        await self._open_profile(PARENT_A, per_child="40.00")
        await self._open_profile(PARENT_B, per_child="50.00")
        await self._generate(period="2026-09")

        # The right parent on the right vehicle: one match.
        match = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=PARENT_A, vehicle_id=BUS_1,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(match.total, 1)
        self.assertEqual(match.data[0].parent_id, PARENT_A)

        # The right parent, but the *other* family's vehicle: no match — Vehicle is never
        # widened/ignored just because a Parent filter is also present.
        mismatch = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=PARENT_A, vehicle_id=BUS_2,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(mismatch.total, 0)

    async def test_combines_vehicle_with_date_range(self) -> None:
        """Vehicle AND From/To apply together."""
        self.addCleanup(CLOCK.advance, datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc))
        await self._open_profile(PARENT_A, per_child="40.00", billing_start_period="2026-09")
        (september_invoice,) = await self._generate(period="2026-09")

        CLOCK.advance(datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc))
        (october_invoice,) = await self._generate(period="2026-10")

        september_bus_1 = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            date_from="2026-09-01", date_to="2026-09-30",
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual([row.id for row in september_bus_1.data], [september_invoice.id])

        october_bus_1 = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None, vehicle_id=BUS_1,
            date_from="2026-10-01", date_to="2026-10-31",
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual([row.id for row in october_bus_1.data], [october_invoice.id])

    async def test_filters_by_date_range(self) -> None:
        """`date_from`/`date_to` filter on `invoice_date` (the Finance page's own From/To picker,
        independent of `period`) — the Finance UI cleanup's own additive filter. PARENT_A's own
        profile stays active across both runs (an ordinary, expected second month of billing), so
        this asserts on which *invoice_date* each range includes, not on a total invoice count."""
        # `CLOCK` is a module-level singleton shared by every test in this file — restore it
        # regardless of outcome so advancing it here can never leak into a later test.
        self.addCleanup(CLOCK.advance, datetime(2026, 9, 10, 8, 0, 0, tzinfo=timezone.utc))

        await self._open_profile(PARENT_A, per_child="40.00", billing_start_period="2026-09")
        (september_invoice,) = await self._generate(period="2026-09")  # invoice_date 2026-09-10

        CLOCK.advance(datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc))
        (october_invoice,) = await self._generate(period="2026-10")  # invoice_date 2026-10-10

        september_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None,
            date_from="2026-09-01", date_to="2026-09-30",
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        september_ids = {row.id for row in september_page.data}
        self.assertIn(september_invoice.id, september_ids)
        self.assertNotIn(october_invoice.id, september_ids)

        october_page = await self.service.list_parent_invoices(
            page=1, page_size=25, period=None, status=None, parent_id=None,
            date_from="2026-10-01", date_to="2026-10-31",
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        october_ids = {row.id for row in october_page.data}
        self.assertIn(october_invoice.id, october_ids)
        self.assertNotIn(september_invoice.id, october_ids)

    async def test_detail_includes_every_child_line_with_a_resolved_name(self) -> None:
        await self._open_profile(PARENT_A, per_child="40.00")
        (invoice,) = await self._generate()

        detail = await self.service.get_parent_invoice_detail(
            invoice.id,
            school_erp_uow=self.school_erp_uow,
            transport_ops_uow=self.transport_ops_uow,
        )
        names = {line.student_id: line.full_name for line in detail.lines}
        self.assertEqual(names[STUDENT_A1], "Mohamed")
        self.assertEqual(names[STUDENT_A2], "Aisha")


# ---- Per-student pricing (ADR-0048) ------------------------------------------------------------


class PerStudentPricingTests(_Base):
    """The worked example from the directive: three children at $10, $20 and $30 on one $60
    family invoice, each child's line their own fee, payments allocated per child."""

    def setUp(self) -> None:
        super().setUp()
        self.children[PARENT_A].append(FakeChild(student_id=STUDENT_A3, full_name="Hawa"))
        self.students[STUDENT_A3] = FakeStudent(id=STUDENT_A3, organization_id=ORG, full_name="Hawa")
        self.transport.mapping[STUDENT_A2] = StudentTransportContext(vehicle_id=BUS_2)
        self.fees = {STUDENT_A1: "10.00", STUDENT_A2: "20.00", STUDENT_A3: "30.00"}

    async def _family_invoice(self, period: str = "2026-09"):
        await self._open_profile(PARENT_A, per_child=self.fees)
        (invoice,) = await self._generate(period)
        return invoice

    async def _preview(self, actor: Principal | None = None, organization_id: str = ORG):
        return await self.service.preview_parent_invoice_generation(
            organization_id=organization_id, period="2026-09", actor=actor or self.actor,
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )

    async def test_ten_twenty_thirty_bill_sixty_with_one_line_per_child(self) -> None:
        invoice = await self._family_invoice()
        self.assertEqual(invoice.amount, "60.00")
        lines = {line.student_id: line for line in invoice.lines}
        self.assertEqual({sid: line.amount for sid, line in lines.items()}, self.fees)
        self.assertEqual({sid: line.balance_due for sid, line in lines.items()}, self.fees)
        # Each line keeps the bus its own child rode at generation time.
        self.assertEqual(lines[STUDENT_A1].vehicle_id, BUS_1)
        self.assertEqual(lines[STUDENT_A2].vehicle_id, BUS_2)

    async def test_a_thirty_dollar_payment_defaults_pro_rata_and_can_be_directed(self) -> None:
        invoice = await self._family_invoice()
        default = await self._pay(invoice.id, "30.00")
        self.assertEqual(
            {a.student_id: a.amount for a in default.allocations},
            {STUDENT_A1: "5.00", STUDENT_A2: "10.00", STUDENT_A3: "15.00"},
        )
        await self._void(default.id)

        await self._pay(invoice.id, "30.00", allocations={STUDENT_A1: "10.00", STUDENT_A2: "20.00"})
        stored = await self._stored(invoice.id)
        self.assertEqual(
            {str(line.student_id): line.balance_due for line in stored.lines},
            {STUDENT_A1: Decimal("0.00"), STUDENT_A2: Decimal("0.00"), STUDENT_A3: Decimal("30.00")},
        )
        self.assertEqual((stored.amount_paid, stored.balance_due), (Decimal("30.00"), Decimal("30.00")))
        self.assertIs(stored.status, ParentInvoiceStatus.PARTIAL)

    async def test_changing_a_students_fee_affects_only_future_invoices(self) -> None:
        september = await self._family_invoice("2026-09")
        await self._set_fee(STUDENT_A3, "35.00")
        (october,) = await self._generate("2026-10")

        stored_september = await self._stored(september.id)
        self.assertEqual(stored_september.amount.amount, Decimal("60.00"))
        self.assertEqual(
            {str(line.student_id): line.amount.amount for line in stored_september.lines}[STUDENT_A3],
            Decimal("30.00"),
        )
        self.assertEqual(october.amount, "65.00")

    async def test_an_unpriced_child_is_left_out_and_reported_never_guessed(self) -> None:
        await self._open_profile(PARENT_A, per_child={STUDENT_A1: "10.00", STUDENT_A3: "0.00"})
        preview = await self._preview()
        self.assertEqual(
            {item.student_id: item.reason for item in preview.skipped},
            {STUDENT_A2: "no_fee", STUDENT_A3: "free"},
        )
        self.assertEqual(preview.totals_by_currency, {"USD": "10.00"})

        (invoice,) = await self._generate()
        self.assertEqual([line.student_id for line in invoice.lines], [STUDENT_A1])
        self.assertEqual(invoice.amount, "10.00")

    async def test_the_preview_is_exactly_what_the_run_issues_and_writes_nothing(self) -> None:
        await self._open_profile(PARENT_A, per_child=self.fees)
        await self._open_profile(PARENT_B, per_child="15.00")
        preview = await self._preview()
        self.assertEqual(self.school_erp_uow.parent_invoices.by_id, {})

        issued = await self._generate()
        self.assertEqual(
            {f.parent_id: (f.total, {l.student_id: l.amount for l in f.lines}) for f in preview.families},
            {i.parent_id: (i.amount, {l.student_id: l.amount for l in i.lines}) for i in issued},
        )
        self.assertEqual(preview.totals_by_currency, {"USD": "75.00"})

        again = await self._preview()
        self.assertEqual(again.families, [])
        self.assertEqual({item.reason for item in again.skipped}, {"already_invoiced"})

    async def test_a_child_with_two_billed_guardians_is_billed_once_by_the_primary(self) -> None:
        self.children[PARENT_B].append(
            FakeChild(student_id=STUDENT_A1, full_name="Mohamed", is_primary=False)
        )
        await self._open_profile(PARENT_A, per_child=self.fees)
        await self._open_profile(PARENT_B, per_child={STUDENT_B1: "15.00"})
        issued = {inv.parent_id: inv for inv in await self._generate()}

        billed = [line.student_id for inv in issued.values() for line in inv.lines]
        self.assertEqual(billed.count(STUDENT_A1), 1)
        self.assertIn(STUDENT_A1, [line.student_id for line in issued[PARENT_A].lines])
        self.assertEqual(issued[PARENT_B].amount, "15.00")

    async def test_a_fee_in_another_currency_is_reported_not_converted(self) -> None:
        await self._open_profile(PARENT_A, per_child={STUDENT_A1: "10.00", STUDENT_A2: "20.00"})
        await self._set_fee(STUDENT_A3, "5000.00", currency="SOS")
        preview = await self._preview()
        self.assertEqual(
            [(item.student_id, item.reason) for item in preview.skipped],
            [(STUDENT_A3, "currency_mismatch")],
        )
        self.assertEqual(preview.families[0].total, "30.00")

    async def test_the_family_fee_view_sums_active_priced_children(self) -> None:
        await self._open_profile(PARENT_A, per_child={STUDENT_A1: "10.00", STUDENT_A2: "20.00"})
        fees = await self.service.get_parent_student_fees(
            PARENT_A, school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow
        )
        self.assertEqual(
            (fees.monthly_total, fees.currency, fees.unpriced_active_students), ("30.00", "USD", 1)
        )
        self.assertEqual(
            {item.student_id: item.monthly_fee for item in fees.students},
            {STUDENT_A1: "10.00", STUDENT_A2: "20.00", STUDENT_A3: None},
        )

    async def test_a_fee_can_only_be_set_on_a_student_in_the_callers_organization(self) -> None:
        with self.assertRaises(AuthorizationError):
            await self.service.set_student_billing_fee(
                SetStudentBillingFeeCommand(
                    student_id=STUDENT_A1, monthly_fee="10.00", currency="USD",
                    actor=make_actor(org_id=OTHER_ORG),
                ),
                school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
            )
        with self.assertRaises(NotFoundError):
            await self._set_fee("01J8Z3K9G6X8YV5T4N2R7QUNKN", "10.00")
        with self.assertRaises(DomainError):
            await self._set_fee(STUDENT_A1, "-1.00")
        self.assertEqual(self.school_erp_uow.student_billing_profiles.by_id, {})

    async def test_another_organization_cannot_preview_or_generate_this_one(self) -> None:
        await self._open_profile(PARENT_A, per_child=self.fees)
        with self.assertRaises(AuthorizationError):
            await self._preview(actor=make_actor(org_id=OTHER_ORG))
        other = await self.service.generate_parent_invoices(
            GenerateParentInvoicesCommand(
                organization_id=OTHER_ORG, period="2026-09", actor=make_actor(org_id=OTHER_ORG)
            ),
            school_erp_uow=self.school_erp_uow, transport_ops_uow=self.transport_ops_uow,
        )
        self.assertEqual(other, [])


if __name__ == "__main__":
    unittest.main()
