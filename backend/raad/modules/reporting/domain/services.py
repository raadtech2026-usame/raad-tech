"""Domain services for the `reporting` module (Backend LLD §5.1).

None are defined in this phase. `ReportRun` is the only aggregate this module owns this phase —
no cross-aggregate orchestration exists to place here. Report *content* (what data a given
report actually summarizes) would be the natural candidate for a domain service, but no document
defines report contents/calculations for any report type (`value_objects.py`'s `ReportType`
docstring) — inventing one is explicitly forbidden by this phase's own instructions, so no such
service exists here, flagged rather than silently skipped.
"""
