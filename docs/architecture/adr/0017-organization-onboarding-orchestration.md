# ADR-0017: Organization Onboarding Orchestration (Organization ↔ IAM)

## Status
Accepted (direct user decision — RAAD business model realignment, 2026-07-28). Extends
**ADR-0003**'s accepted Option A pattern (application-owned provisioning port) to a second
module boundary: `organization` ↔ `iam`.

## Context
The new RAAD business model's Organization Onboarding workflow is explicit and sequential: (1)
RAAD creates the Organization, (2) RAAD selects a subscription plan, (3) RAAD creates the
Organization Administrator, (4) RAAD hands the Org Admin a username/phone + temporary password,
(5) the Org Admin logs in and lands on their own empty dashboard.

Today, `POST /organizations` (`raad/modules/organization/api/routers.py`,
`RegisterOrganizationCommand`) only ever creates the `Organization` row — it has no knowledge of
`iam` at all, matching `.claude/rules/backend.md` #3's no-cross-module-DB-access rule, but also
meaning steps 2-4 above are entirely manual and disconnected today: a Founder must separately
call `POST /users`, and there is no temporary-password hand-off mechanism (`User.status` is only
`invited/active/disabled` — `iam/domain/entities.py` has no password-reset-required concept at
all).

Two real gaps, not one:
1. No orchestration links Organization creation to its first Org Admin `User`.
2. No temporary-password / forced-first-login-password-change mechanism exists anywhere in IAM.

## Decision

### 1. Reuse ADR-0003's Option A shape, applied to `organization` ↔ `iam`
`organization/application/ports.py` gains an `IamProvisioningPort` (same shape as `transport_ops`'s
`UserProvisioningPort` — an outbound port defined by the consuming module, implemented in
`organization/infra` by calling `iam`'s own public application-service facade, never `iam`'s
repository/ORM directly). A new `OnboardOrganizationCommand`/
`OrganizationApplicationService.onboard_organization`:
1. Creates the `Organization` (existing `Organization.register(...)`, unchanged).
2. Calls `IamProvisioningPort.create_user_with_temporary_password(organization_id=..., role=
   Role.ORG_ADMIN, ...)`, receiving back a `user_id` and the one-time plaintext temporary
   password.
3. Commits `organization`'s own Unit of Work; `iam`'s own commit already happened inside step 2
   (two separate transaction boundaries, exactly ADR-0003's already-accepted trade-off).
4. Returns the full `OrganizationDTO` **plus** the Org Admin's `user_id`/username/temporary
   password to the caller (Founder), exactly once — the response is the only place this
   plaintext value is ever exposed; it is never stored or retrievable again.

Failure handling mirrors ADR-0003's Failure Handling section verbatim (idempotent retry against
an already-created `User` preferred over destructive compensation), substituting
`Organization`/`Role.ORG_ADMIN` for `Parent`.

### 2. `is_password_change_required` on `User`
`users` gains a `NOT NULL BOOLEAN` column, `is_password_change_required` (naming matches
`.claude/rules/naming.md`'s `is_`/`has_` boolean convention), defaulting `True` whenever a
temporary password is set (both this workflow and — via the same underlying `iam` primitive —
any future admin-initiated password reset), `False` for a normal self-chosen password change.
`User.set_temporary_password_hash(...)` (a new domain method alongside the existing
`change_password_hash`) sets both the hash and the flag together; `User.change_password_hash`
(the existing method, used for a user-initiated change) clears the flag. Enforced at
`POST /auth/login`/session issuance: a successful login with `is_password_change_required=True`
still issues tokens (the user must be able to reach a change-password screen) but the frontend
gates every other route behind a forced "change your password" screen until a subsequent
`change-password` call clears the flag — a presentation-layer gate backed by the real flag in the
JWT claims/response body, not a client-only check (`.claude/rules/frontend.md` #2).

### 3. Temporary password generation
A cryptographically random password (existing `secrets` stdlib usage pattern, no new dependency)
is generated in `iam/application/services.py`, hashed via the existing `core.security.
PasswordHasher` before persisting, and returned in plaintext only in the synchronous API response
— never logged, never re-derivable. This is the same "generate, hash, return once" shape any
credential hand-off in this codebase already needs; nothing net-new architecturally, just applied
here for the first time.

## Consequences
- Founder-only creation of Organizations is **unchanged** (already correctly gated —
  `organization.organizations.create` stays founder-only per the existing seeded RBAC matrix).
- One new migration (`users.is_password_change_required`), one new domain method on `User`, one
  new port + adapter in `organization`, one new orchestrating command.
- `CreateOrganizationForm.tsx` (frontend) is extended to capture Plan selection + Org Admin
  identity (full name, email/phone) in the same guided flow, and to show the returned temporary
  password in a one-time reveal modal.
- No new bounded context, no change to `.claude/rules/architecture.md` #6's fixed ten.

## Verification
- Unit: `OnboardOrganizationCommand` orchestration (both success and the `iam`-succeeds/
  `organization`-fails partial-failure path, per ADR-0003's Failure Handling), `User.
  set_temporary_password_hash`/`is_password_change_required` invariants.
- Integration: a real end-to-end walkthrough — Founder onboards an org, the returned temporary
  password successfully authenticates, `is_password_change_required=True` is enforced, changing
  the password clears it.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean.

## References
- `docs/architecture/adr/0003-parent-registration-orchestration.md` (the pattern this ADR reuses,
  see its own "Extension" section)
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §4.2 (`organizations`), §4.3 (`users`)
- `.claude/rules/naming.md` (boolean column convention)
- `.claude/rules/security.md` #8 (audit every identity-creating action)
- `.claude/rules/frontend.md` #2 (server-enforced, not client-only, gating)
- `raad/modules/organization/application/`, `raad/modules/iam/domain/entities.py`,
  `raad/modules/iam/application/services.py`
