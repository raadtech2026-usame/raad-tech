"""Regression test for `school_erp.api.routers._parent_financial_summary_response`
(2026-09-10, "Parent & Student Domain Restructure + Parent Payments").

**Why this file exists.** Every `ParentFinanceApplicationService` test
(`test_school_erp_parent_finance_application.py`) calls the application service directly and
never touches the router's own DTO -> Pydantic-response conversion — so a defect living entirely
in that conversion stayed invisible to a fully green suite while `GET /school-finance/parents/
{parent_id}/summary` 500'd against the running API for every caller with at least one child.

**The specific fault, found by live HTTP verification, not by any test.**
`ParentFinancialSummaryResponse(**dto.__dict__)` passed `dto.children` — a list of
`ParentChildFinancialDTO` *dataclass* instances — straight through as the `children:
list[ParentChildFinancialResponse]` field. Pydantic v2 does not coerce an arbitrary dataclass
into a different model class on its own, so this raised `pydantic_core.ValidationError
(type=model_type)` on every summary with at least one child (a family with zero children/zero
invoices never exercised the `children` list, which is exactly why every unit test — all
zero-or-synthetic-DTO-shaped — missed it too). The same "a renderer must coerce what a builder
hands it" lesson CLAUDE.md's Permanent Engineering Lessons already names for report builders.

This is the same seam `test_school_erp_api_schemas.py` documents for *request* models — this
file is the response-side counterpart.
"""

from __future__ import annotations

import unittest

from raad.modules.school_erp.api.routers import _parent_financial_summary_response
from raad.modules.school_erp.api.schemas import ParentFinancialSummaryResponse
from raad.modules.school_erp.application.queries import (
    ParentChildFinancialDTO,
    ParentFinancialSummaryDTO,
)


class ParentFinancialSummaryResponseConversionTests(unittest.TestCase):
    def test_converts_a_summary_with_no_children_without_raising(self) -> None:
        dto = ParentFinancialSummaryDTO(
            parent_id="parent-1",
            currency="USD",
            total_due="0.00",
            total_paid="0.00",
            outstanding="0.00",
            status="no_invoices",
            children=[],
        )
        response = _parent_financial_summary_response(dto)
        self.assertIsInstance(response, ParentFinancialSummaryResponse)
        self.assertEqual(response.children, [])

    def test_converts_a_summary_with_children_without_raising(self) -> None:
        """The regression guard: this is the exact shape (one or more children) that raised
        `ValidationError` in production before the fix."""
        dto = ParentFinancialSummaryDTO(
            parent_id="parent-1",
            currency="USD",
            total_due="50.00",
            total_paid="30.00",
            outstanding="20.00",
            status="partially_paid",
            children=[
                ParentChildFinancialDTO(
                    student_id="student-1",
                    full_name="Mohamed Ahmed",
                    status="active",
                    total_due="50.00",
                    total_paid="30.00",
                    outstanding="20.00",
                    invoice_count=1,
                )
            ],
        )
        response = _parent_financial_summary_response(dto)
        self.assertEqual(len(response.children), 1)
        child = response.children[0]
        self.assertEqual(child.student_id, "student-1")
        self.assertEqual(child.full_name, "Mohamed Ahmed")
        self.assertEqual(child.outstanding, "20.00")
        self.assertEqual(child.invoice_count, 1)


if __name__ == "__main__":
    unittest.main()
