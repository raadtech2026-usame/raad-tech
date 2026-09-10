"""Concrete report renderers (ADR-0040 §6) — the first real implementations of
`ReportRendererPort`'s intent, which had been deliberately unbound since it was defined.

**Two libraries, isolated to this one file.** `openpyxl` (MIT) writes `.xlsx`; `reportlab`
(BSD-3-Clause) writes `.pdf`. Nothing else in the codebase imports either, so the blast radius of
both is this module.

**Rendering is row-shaped, not domain-shaped.** A renderer receives a `ReportTable` — a title,
column headers, and rows of already-formatted strings — and knows nothing about invoices, buses
or subscriptions. That is what keeps `reporting` free of every other module's domain types while
still producing their reports: each owning module builds the table, this file draws it.

**Artifacts are returned as bytes, never stored.** Phase-2 §10.1's object store does not exist in
this repository, and inventing one is out of ADR-0040's scope. `ReportRendererPort.render`'s
contract (return an artifact *URL*) therefore stays unimplemented on purpose — see
`ReportExportService` in `application/services.py` for the synchronous streaming path that
actually works today, and ADR-0040 §6 for why that split is honest rather than a shortcut.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from raad.modules.reporting.application.export_service import ReportRenderer
from raad.modules.reporting.application.report_table import ReportTable
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

#: RAAD brand blue (`docs/architecture/logo-raad.png`). Used for header fills in both formats so
#: an exported report is recognisably the same product as the dashboard it came from.
_BRAND = "1E63FF"
_BRAND_RGB = colors.HexColor("#1E63FF")
_HEADER_TEXT = colors.white
_ZEBRA = colors.HexColor("#F7F8FA")
_BORDER = colors.HexColor("#E2E6EC")


def _cell(value: object) -> str:
    """Every cell reaches a renderer as text.

    `ReportTable`'s contract already says rows are "already-formatted strings", and builders are
    expected to honour it — but openpyxl raises `ValueError: Cannot convert ... to Excel` on
    anything it does not recognise, while reportlab quietly `str()`s the same value inside a
    `Paragraph`. That asymmetry is how one builder leaking a `BillingPeriod` value object made
    `org.student_billing` return a working PDF and a `500` for XLSX. Coercing here means a stray
    non-string is a cosmetic wart in one report rather than a failed download, in both formats
    identically. `None` becomes an em dash rather than the string "None".
    """
    if value is None:
        return "—"
    return value if isinstance(value, str) else str(value)


class ExcelReportRenderer(ReportRenderer):
    """`.xlsx` output.

    Column widths are derived from actual content length rather than fixed, because a bus roster
    and a P&L have nothing in common dimensionally and a fixed width makes one of them unreadable.
    """

    MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    EXTENSION = "xlsx"

    def render(self, table: ReportTable) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        # Excel rejects a sheet name over 31 chars or containing []:*?/\ — truncate rather than
        # let a long report title raise deep inside openpyxl.
        sheet.title = _safe_sheet_name(table.title)

        row_index = 1
        sheet.cell(row=row_index, column=1, value=table.title).font = Font(
            bold=True, size=14, color=_BRAND
        )
        row_index += 1

        if table.subtitle:
            sheet.cell(row=row_index, column=1, value=table.subtitle).font = Font(
                size=10, color="6B7688"
            )
            row_index += 1

        for key, value in table.metadata.items():
            sheet.cell(row=row_index, column=1, value=f"{key}:").font = Font(bold=True, size=9)
            sheet.cell(row=row_index, column=2, value=_cell(value)).font = Font(size=9)
            row_index += 1

        row_index += 1
        header_row = row_index
        thin = Side(style="thin", color="E2E6EC")
        for column_index, header in enumerate(table.headers, start=1):
            cell = sheet.cell(row=header_row, column=column_index, value=header)
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.fill = PatternFill("solid", fgColor=_BRAND)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = Border(bottom=thin)
        row_index += 1

        for row in table.rows:
            for column_index, value in enumerate(row, start=1):
                cell = sheet.cell(row=row_index, column=column_index, value=_cell(value))
                cell.font = Font(size=10)
                if (column_index - 1) in table.numeric_columns:
                    cell.alignment = Alignment(horizontal="right")
                cell.border = Border(bottom=thin)
            row_index += 1

        if table.total_row:
            for column_index, value in enumerate(table.total_row, start=1):
                cell = sheet.cell(row=row_index, column=column_index, value=_cell(value))
                cell.font = Font(bold=True, size=10)
                cell.fill = PatternFill("solid", fgColor="F1F3F6")
                if (column_index - 1) in table.numeric_columns:
                    cell.alignment = Alignment(horizontal="right")

        _autosize(sheet, table)
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()


class PdfReportRenderer(ReportRenderer):
    """`.pdf` output, via reportlab's `platypus` flowables.

    `platypus` rather than hand-drawn canvas text specifically because it paginates a long table
    across pages and repeats the header row — a 200-student bus roster is a multi-page document,
    and a hand-rolled canvas would silently write past the bottom margin.

    Orientation is chosen from the column count: a wide financial table is unreadable squeezed
    into portrait A4, and a narrow one wastes half a landscape page.
    """

    MEDIA_TYPE = "application/pdf"
    EXTENSION = "pdf"

    #: Above this many columns, switch to landscape.
    _LANDSCAPE_COLUMN_THRESHOLD = 6

    def render(self, table: ReportTable) -> bytes:
        buffer = io.BytesIO()
        page_size = (
            landscape(A4)
            if len(table.headers) > self._LANDSCAPE_COLUMN_THRESHOLD
            else A4
        )
        document = SimpleDocTemplate(
            buffer,
            pagesize=page_size,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title=table.title,
            author="RAAD Platform",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "RaadTitle",
            parent=styles["Title"],
            fontSize=16,
            alignment=0,
            spaceAfter=2,
            textColor=_BRAND_RGB,
        )
        subtitle_style = ParagraphStyle(
            "RaadSubtitle",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#6B7688"),
            spaceAfter=6,
        )
        cell_style = ParagraphStyle(
            "RaadCell", parent=styles["Normal"], fontSize=8, leading=10
        )
        header_style = ParagraphStyle(
            "RaadHeader",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=_HEADER_TEXT,
            fontName="Helvetica-Bold",
        )

        story: list = [Paragraph(table.title, title_style)]
        if table.subtitle:
            story.append(Paragraph(table.subtitle, subtitle_style))
        if table.metadata:
            meta = "  ·  ".join(f"<b>{k}:</b> {v}" for k, v in table.metadata.items())
            story.append(Paragraph(meta, subtitle_style))
        story.append(Spacer(1, 6))

        # Every cell is a Paragraph so long text wraps inside its column instead of overflowing
        # the table — the single most common way a generated PDF table becomes unreadable.
        data = [[Paragraph(h, header_style) for h in table.headers]]
        data.extend([[Paragraph(_cell(c), cell_style) for c in row] for row in table.rows])
        if table.total_row:
            data.append(
                [
                    Paragraph(f"<b>{c}</b>", cell_style)
                    for c in table.total_row
                ]
            )

        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND_RGB),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            # Zebra striping over the body rows only (row 0 is the header).
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
        ]
        for column in table.numeric_columns:
            style_commands.append(("ALIGN", (column, 1), (column, -1), "RIGHT"))
        if table.total_row:
            style_commands.append(
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F3F6"))
            )

        pdf_table = Table(data, repeatRows=1, hAlign="LEFT")
        pdf_table.setStyle(TableStyle(style_commands))
        story.append(pdf_table)

        document.build(story, onLaterPages=_footer, onFirstPage=_footer)
        return buffer.getvalue()


def _footer(canvas, document) -> None:
    """Page number plus generation timestamp on every page — what makes a printed report
    verifiable after it leaves the screen."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#9BA5B7"))
    canvas.drawString(
        14 * mm,
        8 * mm,
        f"RAAD Platform · generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    )
    canvas.drawRightString(
        document.pagesize[0] - 14 * mm, 8 * mm, f"Page {document.page}"
    )
    canvas.restoreState()


def _safe_sheet_name(title: str) -> str:
    invalid = set('[]:*?/\\')
    cleaned = "".join(c for c in title if c not in invalid).strip() or "Report"
    return cleaned[:31]


def _autosize(sheet, table: ReportTable) -> None:
    """Width from the widest actual value in each column, clamped so one long note cannot push a
    column off the page."""
    for column_index, header in enumerate(table.headers, start=1):
        widest = len(str(header))
        for row in table.rows:
            if column_index - 1 < len(row):
                widest = max(widest, len(str(row[column_index - 1])))
        sheet.column_dimensions[get_column_letter(column_index)].width = min(
            max(widest + 3, 10), 48
        )
