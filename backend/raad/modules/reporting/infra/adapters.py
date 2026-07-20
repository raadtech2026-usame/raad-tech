"""External adapters for `reporting` (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

Deliberately empty this phase. The task's own Out of Scope section explicitly forbids PDF
generation, Excel generation, BI dashboards, scheduled reports, and an analytics engine —
persistence only. No rendering port exists to adapt either (`application/ports.py`'s own
docstring explains why none was declared). A future `ReportRenderer` adapter (object-store
artifact writer, PDF/Excel engine) belongs here once a documented port interface and an
approved integration exist — mirrors `billing.infra.adapters`/`notifications.infra.adapters`'s
identical "deliberately absent, not stubbed" precedent.
"""
