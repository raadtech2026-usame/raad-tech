"""`ReportCatalog` / `ReportExportService` / renderer tests (ADR-0040 §6).

Three things are checked here, and the first is a security property rather than a formatting one.

**1. A caller cannot export a report their role was never offered.** `reporting.reports.request`
is one permission covering every definition, so it cannot distinguish "may export their own
school's billing" from "may export RAAD's own operating costs". `ReportDefinition.roles` draws
that line, and `ReportExportService.export` must enforce it — not only `ReportCatalog.list_for`,
which decides what is *listed*. Without the export-time check an Org Admin could name
`platform.invoices` directly, whose real builder deliberately sets `organization_ids=None` to
span every tenant, or `platform.profit_and_loss`, which reads a module with no `organization_id`
column for any scope filter to match (ADR-0040 §1).

**2. Exports are real files.** `openpyxl` and `reportlab` produce genuine `.xlsx` and `.pdf`
bytes — asserted by magic number, so a renderer that silently degraded to CSV or an empty body
would fail here rather than in a user's download folder.

**3. The catalogue's registration invariants** — unique keys, scope filtering.
"""

from __future__ import annotations

import unittest
import zipfile
from io import BytesIO

from raad.core.di.report_definitions import _MAX_ROWS, _Rows, _collect, _metadata
from raad.core.errors.exceptions import AuthorizationError, NotFoundError
from raad.core.pagination import MAX_PAGE_SIZE, OffsetPage, OffsetPageRequest
from raad.core.tenancy.principal import Principal, Role
from raad.modules.reporting.application.catalog import (
    ReportCatalog,
    ReportDefinition,
    ReportRequest,
)
from raad.modules.reporting.application.export_service import ReportExportService
from raad.modules.reporting.application.report_table import ReportTable
from raad.modules.reporting.infra.renderers import (
    ExcelReportRenderer,
    PdfReportRenderer,
)

ORG_ADMIN = Principal(
    user_id="admin-1", role=Role.ORG_ADMIN, org_id="01J8Z3K9G6X8YV5T4N2R7QW3MD"
)
FOUNDER = Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)
SUPPORT = Principal(user_id="support-1", role=Role.SUPPORT_STAFF, org_id=None)
FINANCE = Principal(user_id="finance-1", role=Role.FINANCE_STAFF, org_id=None)


def _table(title: str = "Test Report") -> ReportTable:
    return ReportTable(
        title=title,
        subtitle="A subtitle",
        headers=["Period", "Student", "Amount"],
        rows=[["2026-09", "Amina", "50.00"], ["2026-09", "Yusuf", "75.50"]],
        metadata={"Period": "2026-09", "Invoices": "2"},
        numeric_columns=[2],
        total_row=["TOTAL", "", "125.50"],
    )


def _definition(
    key: str, *, scope: str, roles: tuple[Role, ...] = ()
) -> ReportDefinition:
    async def build(request: ReportRequest) -> ReportTable:
        return _table(key)

    return ReportDefinition(
        key=key,
        title=key,
        description="",
        scope=scope,
        build=build,
        roles=roles,
    )


def _catalog() -> ReportCatalog:
    catalog = ReportCatalog()
    catalog.register(
        _definition(
            "org.student_billing",
            scope="organization",
            roles=(Role.ORG_ADMIN, Role.FOUNDER, Role.SUPPORT_STAFF, Role.FINANCE_STAFF),
        )
    )
    catalog.register(
        _definition(
            "platform.invoices",
            scope="platform",
            roles=(Role.FOUNDER, Role.SUPPORT_STAFF, Role.FINANCE_STAFF),
        )
    )
    catalog.register(
        _definition(
            "platform.profit_and_loss",
            scope="platform",
            roles=(Role.FOUNDER, Role.FINANCE_STAFF),
        )
    )
    catalog.register(_definition("open.everything", scope="platform"))
    return catalog


def _service() -> ReportExportService:
    return ReportExportService(
        catalog=_catalog(),
        renderers={"xlsx": ExcelReportRenderer(), "pdf": PdfReportRenderer()},
    )


class CatalogTests(unittest.TestCase):
    def test_duplicate_keys_are_refused_at_registration(self) -> None:
        catalog = ReportCatalog()
        catalog.register(_definition("a", scope="platform"))
        with self.assertRaises(ValueError):
            catalog.register(_definition("a", scope="platform"))

    def test_listing_hides_definitions_a_role_may_not_generate(self) -> None:
        keys = {d.key for d in _catalog().list_for(ORG_ADMIN)}
        self.assertIn("org.student_billing", keys)
        self.assertNotIn("platform.invoices", keys)
        self.assertNotIn("platform.profit_and_loss", keys)

    def test_a_definition_with_no_role_list_is_offered_to_everyone(self) -> None:
        self.assertIn(
            "open.everything", {d.key for d in _catalog().list_for(ORG_ADMIN)}
        )

    def test_scope_filters_the_listing(self) -> None:
        keys = {d.key for d in _catalog().list_for(FOUNDER, scope="organization")}
        self.assertEqual(keys, {"org.student_billing"})

    def test_support_staff_may_not_see_the_platform_pnl(self) -> None:
        """`finance_staff`/`founder` only — RAAD's own costs are not a support surface."""
        keys = {d.key for d in _catalog().list_for(SUPPORT)}
        self.assertNotIn("platform.profit_and_loss", keys)
        self.assertIn("platform.invoices", keys)


class ExportRoleEnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_org_admin_cannot_export_a_cross_tenant_platform_report(self) -> None:
        with self.assertRaises(AuthorizationError):
            await _service().export(
                definition_key="platform.invoices",
                format="pdf",
                request=ReportRequest(principal=ORG_ADMIN),
            )

    async def test_org_admin_cannot_export_raads_own_profit_and_loss(self) -> None:
        with self.assertRaises(AuthorizationError):
            await _service().export(
                definition_key="platform.profit_and_loss",
                format="pdf",
                request=ReportRequest(principal=ORG_ADMIN),
            )

    async def test_support_staff_cannot_export_the_platform_pnl_either(self) -> None:
        with self.assertRaises(AuthorizationError):
            await _service().export(
                definition_key="platform.profit_and_loss",
                format="xlsx",
                request=ReportRequest(principal=SUPPORT),
            )

    async def test_finance_staff_can_export_the_platform_pnl(self) -> None:
        rendered = await _service().export(
            definition_key="platform.profit_and_loss",
            format="xlsx",
            request=ReportRequest(principal=FINANCE),
        )
        self.assertTrue(rendered.content)

    async def test_org_admin_can_export_their_own_school_report(self) -> None:
        rendered = await _service().export(
            definition_key="org.student_billing",
            format="pdf",
            request=ReportRequest(principal=ORG_ADMIN),
        )
        self.assertTrue(rendered.content)

    async def test_an_unknown_definition_key_is_a_404_not_a_403(self) -> None:
        with self.assertRaises(NotFoundError):
            await _service().export(
                definition_key="org.does_not_exist",
                format="pdf",
                request=ReportRequest(principal=FOUNDER),
            )

    async def test_an_unsupported_format_is_refused(self) -> None:
        with self.assertRaises(NotFoundError):
            await _service().export(
                definition_key="org.student_billing",
                format="csv",
                request=ReportRequest(principal=FOUNDER),
            )


class RenderedArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_xlsx_export_is_a_real_workbook_with_the_rows_in_it(self) -> None:
        rendered = await _service().export(
            definition_key="org.student_billing",
            format="xlsx",
            request=ReportRequest(principal=FOUNDER),
        )

        self.assertEqual(
            rendered.media_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(rendered.filename.endswith(".xlsx"))
        # An .xlsx is a ZIP container; "PK" is the signature. A CSV pretending to be one, or an
        # empty body, fails here.
        self.assertTrue(rendered.content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(rendered.content)) as archive:
            self.assertIn("xl/workbook.xml", archive.namelist())
            shared = b"".join(
                archive.read(name)
                for name in archive.namelist()
                if name.startswith("xl/")
            )
        self.assertIn(b"Amina", shared)

    async def test_pdf_export_is_a_real_pdf(self) -> None:
        rendered = await _service().export(
            definition_key="org.student_billing",
            format="pdf",
            request=ReportRequest(principal=FOUNDER),
        )

        self.assertEqual(rendered.media_type, "application/pdf")
        self.assertTrue(rendered.filename.endswith(".pdf"))
        self.assertTrue(rendered.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", rendered.content[-1024:])

    def test_renderers_handle_a_report_with_no_rows(self) -> None:
        """An empty period is an ordinary outcome, not an error — a school that billed nothing
        this month must still get a file back rather than a 500."""
        empty = ReportTable(title="Empty", headers=["A", "B"], rows=[])
        self.assertTrue(ExcelReportRenderer().render(empty).startswith(b"PK"))
        self.assertTrue(PdfReportRenderer().render(empty).startswith(b"%PDF-"))

    def test_a_non_string_cell_does_not_break_either_renderer(self) -> None:
        """One builder leaking a value object must not turn an export into a 500.

        `org.student_billing` put a `BillingPeriod` into a cell. reportlab `str()`d it inside a
        `Paragraph` and produced a fine PDF; openpyxl raised
        `ValueError: Cannot convert BillingPeriod(...) to Excel`. Same table, same data, one
        format working and the other failing — so the coercion belongs at the renderer boundary,
        not only in whichever builder was noticed.
        """

        class _Period:
            def __str__(self) -> str:
                return "2026-09"

        table = ReportTable(
            title="Mixed cells",
            headers=["Period", "Count", "Missing"],
            rows=[[_Period(), 12, None]],
            total_row=[_Period(), 12, None],
        )

        xlsx = ExcelReportRenderer().render(table)
        self.assertTrue(xlsx.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(xlsx)) as archive:
            body = b"".join(
                archive.read(name) for name in archive.namelist() if name.startswith("xl/")
            )
        self.assertIn(b"2026-09", body)
        self.assertTrue(PdfReportRenderer().render(table).startswith(b"%PDF-"))

    def test_a_none_cell_renders_as_a_dash_not_the_word_none(self) -> None:
        table = ReportTable(title="Gaps", headers=["A"], rows=[[None]])
        with zipfile.ZipFile(BytesIO(ExcelReportRenderer().render(table))) as archive:
            body = b"".join(
                archive.read(name) for name in archive.namelist() if name.startswith("xl/")
            )
        self.assertNotIn(b">None<", body)

    def test_renderers_handle_a_table_with_no_total_row(self) -> None:
        table = ReportTable(
            title="No totals", headers=["A"], rows=[["1"], ["2"]], total_row=None
        )
        self.assertTrue(ExcelReportRenderer().render(table).startswith(b"PK"))
        self.assertTrue(PdfReportRenderer().render(table).startswith(b"%PDF-"))


class _CountingRepository:
    """Records every page request it is asked for, and serves `total` sequential rows."""

    def __init__(self, total: int) -> None:
        self._rows = list(range(total))
        self.requests: list[tuple[int, int]] = []

    async def list_page(self, page_request, *, filters, sort, search):
        self.requests.append((page_request.page, page_request.page_size))
        start = page_request.offset
        return OffsetPage(
            data=self._rows[start : start + page_request.page_size],
            total=len(self._rows),
            page=page_request.page,
            page_size=page_request.page_size,
        )


class ReportRowCollectionTests(unittest.IsolatedAsyncioTestCase):
    """Regression cover for a live defect: every list-backed report returned `422`, not a report.

    The builders asked for `OffsetPageRequest(page=1, page_size=1000)`, and that constructor
    rejects anything above `MAX_PAGE_SIZE` (100) with a `ValidationError`. Seven of the eleven
    report definitions therefore rendered nothing at all against the running API, while the whole
    test suite stayed green — no test had ever driven a builder. These tests drive the collector.
    """

    def test_the_documented_cap_exceeds_what_one_page_request_allows(self) -> None:
        # The premise of the bug, asserted rather than assumed: if these were ever equal, the
        # single-page read would have been correct and this helper unnecessary.
        self.assertGreater(_MAX_ROWS, MAX_PAGE_SIZE)
        with self.assertRaises(Exception):
            OffsetPageRequest(page=1, page_size=_MAX_ROWS)

    async def test_never_requests_a_page_larger_than_the_repository_allows(self) -> None:
        repository = _CountingRepository(total=450)

        rows = await _collect(repository)

        self.assertTrue(all(size <= MAX_PAGE_SIZE for _, size in repository.requests))
        self.assertEqual(len(rows.data), 450)
        self.assertEqual(rows.total, 450)
        self.assertFalse(rows.is_truncated)

    async def test_stops_at_the_documented_cap_and_reports_the_true_total(self) -> None:
        repository = _CountingRepository(total=2500)

        rows = await _collect(repository)

        self.assertEqual(len(rows.data), _MAX_ROWS)
        self.assertEqual(rows.total, 2500)
        self.assertTrue(rows.is_truncated)

    async def test_a_short_final_page_ends_the_loop(self) -> None:
        repository = _CountingRepository(total=150)

        await _collect(repository)

        # Two requests, not an endless walk past the end of the data.
        self.assertEqual(repository.requests, [(1, 100), (2, 100)])

    async def test_an_empty_repository_produces_one_request_and_no_rows(self) -> None:
        repository = _CountingRepository(total=0)

        rows = await _collect(repository)

        self.assertEqual(rows.data, [])
        self.assertEqual(len(repository.requests), 1)

    def test_metadata_names_the_cut_when_the_cap_bit(self) -> None:
        truncated = _metadata(_Rows(data=[1] * 1000, total=4200), "Invoices")
        self.assertEqual(truncated["Invoices"], "4200")
        self.assertIn("Showing the first 1000 of 4200", truncated["Note"])

    def test_metadata_adds_no_note_when_the_report_is_complete(self) -> None:
        complete = _metadata(_Rows(data=[1] * 12, total=12), "Invoices", Period="2026-09")
        self.assertNotIn("Note", complete)
        self.assertEqual(complete["Period"], "2026-09")



if __name__ == "__main__":  # pragma: no cover
    unittest.main()
