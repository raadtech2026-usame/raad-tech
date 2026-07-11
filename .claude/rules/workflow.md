# Rule: Engineering Workflow

Governs how changes are proposed, implemented, and shipped in this repository. Applies to every
phase of work, regardless of which bounded context or layer is being touched.

1. **New dependencies must be explained before being installed.** Before adding any new package,
   library, or external service dependency (backend, frontend, or Flutter), state: what it is,
   why it's needed, what it replaces or complements, and its license. Do not run an install command
   in the same turn the dependency is first proposed — get explicit go-ahead first.
2. **Only approved dependencies may be installed.** "Approved" means: already in use elsewhere in
   this repo (`requirements*.txt`, `pyproject.toml`, `package.json`, `pubspec.yaml`), or explicitly
   approved by the user in the current conversation. If no approved-dependency list exists yet for
   a given part of the stack, treat the first approval as establishing precedent and do not
   silently add alternatives to the same problem later (e.g. two different HTTP client libraries).
3. **Run formatting, linting, and tests after every completed phase** of work — not only at the very
   end. A "phase" is a coherent unit of work (e.g. one module's API layer, one migration + its
   repository code, one feature slice) that could plausibly be reviewed on its own. Do not batch
   verification across multiple unrelated phases.
4. **Show all changed files** before committing — a `git status` / `git diff --stat` (or
   equivalent) summarizing every file touched in the phase, not just a prose description.
5. **Create a Git commit with a meaningful message** for each completed phase, per
   [[git]] — new commit (never amend unless asked), message explains _why_, references the
   business rule or architecture section satisfied, and labels structural/scaffold-only commits as
   such.
6. **Never push without explicit confirmation.** Pushing to any remote (including `origin/main` or
   any feature branch) requires asking first, every time — a prior approval to push does not carry
   forward to later pushes.
7. **Never violate the approved architecture documents.** Every change must be checked against
   `docs/business/` and the `.claude/rules/*.md` files derived from them — in particular
   [[architecture]], [[backend]], [[database]], [[security]]. If a request would require violating
   one of these (e.g. a new bounded context, a cross-module DB read, a client-only permission
   check), stop and flag the conflict explicitly rather than implementing a workaround.
8. **Never implement business logic without an approved design.**
   Before writing business logic, verify that the corresponding Business Requirements, Architecture, LLD, Database Design, and API Contracts have already been approved. If documentation is missing or conflicts exist, stop and request clarification instead of making assumptions.
