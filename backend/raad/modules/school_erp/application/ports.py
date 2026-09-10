"""Outbound ports the `school_erp` application layer depends on (Backend LLD §4.2).

`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with this
module's own six repositories, mirroring `billing.application.ports.BillingUnitOfWork` exactly.

**`StudentTransportContextPort` is how a bill learns which bus it is for.**
`.claude/rules/backend.md` #3 forbids `school_erp` reading `transport_ops` tables, so the
route/vehicle/driver an invoice captures at issue time (ADR-0040 §3) is resolved through this
port, whose concrete adapter lives in `core/di/` (the composition root) and calls
`transport_ops`'s own *application service*. That is the same provisioning-port shape ADR-0003
established and ADR-0017 reused for `IamProvisioningPort` — never a cross-module import from a
module into another module's internals.

Returning `None` for every field is a legitimate, expected outcome: a student with no active
assignment gets an invoice with no transport context rather than a failed issue. A school
billing a student who has not been assigned to a bus yet is an ordinary situation, not an error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.school_erp.domain.repositories import (
    ExpenseRepository,
    FeePlanRepository,
    FinancialCategoryRepository,
    IncomeRepository,
    StudentInvoiceRepository,
    StudentPaymentRepository,
)


@dataclass(frozen=True)
class StudentTransportContext:
    """The transportation a student is currently assigned to, as of invoice issue time. Every
    field is independently optional — a student may have a route but no vehicle assigned yet."""

    route_id: str | None = None
    vehicle_id: str | None = None
    driver_id: str | None = None


class StudentTransportContextPort(ABC):
    """Resolves a student's current transport assignment for invoice issuance.

    Deliberately batch-shaped (`resolve_many`) as well as single: monthly invoice generation for
    a whole school resolves hundreds of students at once, and a per-student call there would be
    the N+1 this codebase has already had to fix elsewhere.
    """

    @abstractmethod
    async def resolve(self, *, student_id: str) -> StudentTransportContext:
        raise NotImplementedError

    @abstractmethod
    async def resolve_many(
        self, *, student_ids: list[str]
    ) -> dict[str, StudentTransportContext]:
        """Students with no resolvable assignment are simply absent from the returned mapping —
        callers treat a miss as "no transport context", never as an error."""
        raise NotImplementedError


class SchoolErpUnitOfWork(UnitOfWork):
    """Bundles this module's six repositories onto one transaction boundary.

    Recording a student payment writes a `StudentPayment` *and* advances its `StudentInvoice`;
    both must commit together or neither, which is exactly what sharing this Unit of Work
    guarantees. The concrete implementation is
    `infra.repositories.SqlAlchemySchoolErpUnitOfWork`.
    """

    financial_categories: FinancialCategoryRepository
    fee_plans: FeePlanRepository
    student_invoices: StudentInvoiceRepository
    student_payments: StudentPaymentRepository
    income: IncomeRepository
    expenses: ExpenseRepository
