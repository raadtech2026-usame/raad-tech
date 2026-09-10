"""`ReportTable` — the shape every report builder produces and every renderer consumes.

Application layer, deliberately: it is a DTO, and putting it in `infra/renderers.py` would mean
`application/catalog.py` importing *upward* from infrastructure, inverting the dependency
direction `.claude/rules/backend.md` #2 fixes (`api -> application -> domain`; infra implements
what the inner layers define, it never supplies them). The renderers import this; nothing
imports the renderers except the composition root and the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReportTable:
    """One rendered report: a title, optional subtitle/metadata, headers, and string rows.

    Rows are **already formatted** by the module that owns the data — amounts as decimal strings,
    dates in the caller's chosen form. A renderer that formatted money would be a second place
    money formatting lives, and the two would drift.
    """

    title: str
    headers: list[str]
    rows: list[list[str]]
    subtitle: str | None = None
    #: Rendered as a "Key: value" strip under the title (period, organization, generated-at).
    metadata: dict[str, str] = field(default_factory=dict)
    #: Column indices to right-align. Numeric columns, chosen by the caller because only it
    #: knows which of its columns are amounts.
    numeric_columns: list[int] = field(default_factory=list)
    #: Optional totals row, rendered with emphasis at the foot of the table.
    total_row: list[str] | None = None
