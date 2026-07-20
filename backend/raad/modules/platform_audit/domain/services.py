"""Domain services for the `platform_audit` module (Backend LLD §5.1).

None are defined here. `SystemSetting.set`/`update_value` are self-contained, no-I/O aggregate
behavior (`entities.py`); `AuditEntry` has no behavior at all (a read-model, not an aggregate).
No cross-aggregate orchestration exists in this module — mirrors `billing.domain.services`'s
identical "no domain services needed" reasoning.
"""
