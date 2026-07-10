# Rule: Documentation

1. `CLAUDE.md` and `docs/business/` are the sources of truth. New documentation must trace back to
   them or to a formally adopted ADR — never invent architecture to fill a documentation gap.
2. If two documents conflict, report the conflict explicitly rather than silently picking one (see
   the Enterprise Architect and Technical Writer agents).
3. Every module/service README must state its current implementation status honestly (structural
   scaffold only vs. partially implemented vs. complete) and must be updated when that status
   changes.
4. Architecture Decision Records live in `docs/architecture/adr/`, numbered sequentially
   (`0001-<slug>.md`, ...).
5. Generated documentation (OpenAPI/AsyncAPI specs in `docs/api/`) is never hand-edited — regenerate
   from source contracts.
6. Comments in code are reserved for non-obvious *why* (hidden constraints, workarounds, subtle
   invariants) — not restatements of what the code does.
