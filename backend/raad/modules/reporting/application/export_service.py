"""Report export use case (ADR-0040 §6).

**Why this exists rather than the API calling a renderer directly.** The first version of this
route imported `infra.renderers` straight into `api/routers.py`, and
`tests/architecture/test_api_layer_boundaries.py` rule 5 rejected it — correctly. The API layer
never imports infrastructure; it calls an application service, which depends on an *abstraction*
that infrastructure implements (`.claude/rules/backend.md` #2). That gate catching this is the
gate doing its job, so the fix is the real one rather than an exemption.

`ReportRenderer` below is that abstraction. Concrete `ExcelReportRenderer`/`PdfReportRenderer`
live in `infra/renderers.py` and are registered here by the composition root, which is the one
place allowed to know both.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from raad.core.errors.exceptions import AuthorizationError, NotFoundError
from raad.modules.reporting.application.catalog import ReportCatalog, ReportRequest
from raad.modules.reporting.application.report_table import ReportTable


class ReportRenderer(ABC):
    """Turns a `ReportTable` into bytes in one concrete format."""

    #: HTTP `Content-Type` for the produced bytes.
    MEDIA_TYPE: str = ""
    #: File extension, without the dot.
    EXTENSION: str = ""

    @abstractmethod
    def render(self, table: ReportTable) -> bytes:
        raise NotImplementedError


@dataclass(frozen=True)
class RenderedReport:
    content: bytes
    media_type: str
    filename: str


class ReportExportService:
    """Resolves a report definition, builds its table, and renders it in the requested format.

    Synchronous by design — see ADR-0040 §6: there is no object store to stage an artifact in, so
    a report is rendered on demand and streamed back rather than given a fabricated
    `artifact_url`. The asynchronous `ReportRun` aggregate is untouched and remains the right home
    for long runs once a store exists.
    """

    def __init__(self, *, catalog: ReportCatalog, renderers: dict[str, ReportRenderer]) -> None:
        self._catalog = catalog
        self._renderers = renderers

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return tuple(sorted(self._renderers))

    async def export(
        self, *, definition_key: str, format: str, request: ReportRequest
    ) -> RenderedReport:
        definition = self._catalog.get(definition_key)
        if definition is None:
            raise NotFoundError(f"Report {definition_key!r} not found")

        # `reporting.reports.request` is one permission shared by every report, so it cannot by
        # itself distinguish "may export their own school's billing" from "may export RAAD's own
        # operating costs". `definition.roles` is what draws that line, and it has to be enforced
        # *here* rather than only in `ReportCatalog.list_for`: the catalogue filter decides what a
        # caller is offered, and a caller can name a key they were never offered.
        #
        # Without this check an Org Admin could export `platform.invoices`/`platform.payments`/
        # `platform.subscriptions` — whose builders deliberately set `organization_ids=None` to
        # span every tenant — and `platform.profit_and_loss`/`platform.expenses`, which read
        # `platform_finance`, a module with no `organization_id` column for any scope filter to
        # match (ADR-0040 §1). That is precisely the cross-domain leak the three-module split
        # exists to make structurally impossible, so it is closed structurally here.
        if definition.roles and request.principal.role not in definition.roles:
            raise AuthorizationError(
                f"Role {request.principal.role.value!r} may not generate report "
                f"{definition_key!r}"
            )

        renderer = self._renderers.get(format)
        if renderer is None:
            # A 404 rather than a 500: an unsupported format is a caller mistake, and the route's
            # own pattern already constrains it — this is the belt to that suspenders.
            raise NotFoundError(f"Unsupported report format {format!r}")

        table = await definition.build(request)
        filename = (
            f"{definition_key.replace('.', '-')}-{date.today().isoformat()}."
            f"{renderer.EXTENSION}"
        )
        return RenderedReport(
            content=renderer.render(table),
            media_type=renderer.MEDIA_TYPE,
            filename=filename,
        )
