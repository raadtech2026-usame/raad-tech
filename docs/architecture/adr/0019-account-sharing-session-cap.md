# ADR-0019: Account-Sharing Protection — Concurrent Session Cap

## Status
Accepted (direct user decision — RAAD business model realignment, 2026-07-28). User explicitly
selected the **lightweight tier** among three presented options (session cap vs. trusted-device
registration with fingerprinting vs. hardware-backed device attestation) — the latter two are
out of scope, see Consequences.

## Context
The new RAAD business model asks for protection against one account being shared across many
parents. No such infrastructure exists today: `iam`'s `RefreshToken` aggregate
(`raad/modules/iam/domain/entities.py`) already models one issued token per row (`user_id`,
`token_hash`, `issued_at`, `expires_at`, `revoked_at`) and the ORM model
(`RefreshTokenModel`, Database Design §4.5) already carries `user_agent`/`ip_address` columns —
but both are **dead**: nothing populates them at login/refresh, and nothing counts or limits how
many non-revoked, non-expired refresh tokens a single user can hold concurrently.

The Flutter mobile app (the platform Parent/Driver actually use, `.claude/rules/flutter.md` #1)
is still an empty structural scaffold with no native code — this rules out anything requiring
client-side device attestation or a stable hardware-backed identifier this phase, per the user's
explicit choice.

## Decision

### 1. `SessionLimitPolicy` — a new policy object in `core/policies/`
Mirrors the existing single-tested-policy-object pattern (`SubscriptionAccessPolicy`,
`VideoAccessPolicy`) rather than scattering ad hoc checks: a pure `evaluate(active_session_count,
max_sessions) -> PolicyDecision`-shaped object, unit-tested directly per
`.claude/rules/testing.md` #3's explicit-regression-test discipline for security-relevant
invariants.

### 2. Enforcement point: login and refresh
At `POST /auth/login` and `POST /auth/refresh` (`iam/application/services.py`), after issuing a
new `RefreshToken`, count the caller's own non-revoked, non-expired refresh tokens. If the count
exceeds the configured cap for that user's role, **revoke the oldest** (by `issued_at`) until
back under the cap — a "new device pushes out the oldest" default, not a hard rejection (an
outright reject-new-login would itself be a worse, more disruptive default with no way for a
legitimate user experiencing normal turnover — new phone, browser reinstall — to recover without
contacting support).

### 3. Cap value: per-role, configurable via the existing `SystemSetting` store
Reuses `platform_audit.SystemSetting` (`GET`/`PATCH /admin/settings`) — the exact precedent the
recent stop-approaching-distance change already established (org-configurable value living in
existing config infrastructure rather than a hardcoded constant, ADR-0014's amendment). A
sensible starting default (set at implementation time, not fixed forever by this ADR): tighter
for `parent`/`driver` (the literal "one account shared with many parents" scenario named in the
business model), looser for `org_admin`/RAAD-staff roles (who legitimately use multiple devices/
browsers for platform administration).

### 4. Populate the existing dead columns + one new one
`user_agent`/`ip_address` (already-existing `RefreshTokenModel` columns) are captured from the
request at login/refresh for the first time. One new column, `refresh_tokens.device_label`
(nullable `VARCHAR`, `.claude/rules/naming.md`-compliant), is added — a short, human-readable
label (e.g. derived from the parsed user-agent: "Chrome on Windows") shown back to the user in
their own session list, distinct from the raw `user_agent` string.

### 5. Self-service session management
- `GET /auth/sessions` — lists the caller's own active (non-revoked, non-expired) sessions:
  `device_label`, masked `ip_address`, `issued_at`, `expires_at`.
- `DELETE /auth/sessions/{id}` — revokes one specific session by id (the "secure device
  replacement flow": a user who lost a phone revokes that session explicitly rather than waiting
  for the cap to evict it).

### 6. Suspicious-login signal — logged only, no hard block
A login from a `device_label`/`ip_address` combination not seen in the user's last N sessions is
recorded as an `audit_entries` row (`.claude/rules/security.md` #8) — visibility only. Building an
automated block/step-up-auth response on top of this signal is explicitly **not** this phase's
scope; no document specifies a fraud-detection policy, and inventing one now would be exactly the
kind of undocumented business rule `.claude/rules/workflow.md` #8 asks this codebase to avoid.

## Consequences
- One new migration (`refresh_tokens.device_label`), one new policy object, two new self-service
  routes, `user_agent`/`ip_address` capture wired for the first time.
- **Explicitly deferred, per the user's own tier choice**: device fingerprinting/trusted-device
  approval flows (medium tier) and hardware-backed attestation (heavy tier, blocked on the
  Flutter app existing beyond its current empty scaffold). Revisiting either later requires no
  change to this ADR's mechanism — both would layer additional signals onto the same
  `refresh_tokens`-keyed session model, not replace it.
- This does not, by itself, stop a determined user from sharing credentials across a number of
  devices at or under the cap — it bounds the *scale* of sharing (a hard concurrent-session
  ceiling), which is the lightweight tier's own accepted trade-off.

## Verification
- Unit: `SessionLimitPolicy` (revoke-oldest behavior, per-role cap resolution, boundary cases —
  exactly at cap, one over, cap of 1).
- Integration: logging in past the cap actually revokes the oldest session's refresh token (a
  subsequent refresh attempt against the revoked token fails); `GET`/`DELETE /auth/sessions`
  round-trip against a real database.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean.

## References
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §4.5 (`refresh_tokens`)
- `docs/architecture/adr/0014-geofence-evaluation-config-gaps.md` (Amendment — the
  `SystemSetting`-configurable-value precedent this ADR reuses)
- `.claude/rules/testing.md` #3 (explicit regression tests for security-relevant invariants)
- `.claude/rules/security.md` #8 (audit logging)
- `raad/modules/iam/domain/entities.py` (`RefreshToken`), `raad/core/policies/`
