"""Vendor-specific device-plane protocol adapters (ADR-0009). Each subpackage here is a
self-contained protocol/dispatcher/handlers stack for one hardware vendor's actual wire format,
reusing the parent package's protocol-agnostic `connection/`/`session/`/`events/` layers unchanged
(`.claude/rules/jt808.md` #2's Anti-Corruption Layer principle, applied at a full-protocol-swap
grain — see `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`)."""
