# ADR-0003: Parent Registration Orchestration (IAM ↔ Transport Operations)

## Status
Proposed. Not yet accepted — for review only. **This ADR defines an architecture decision for
future implementation; it makes no code, schema, or migration changes.** No part of the current
Phase 10.6 `Parent` implementation is altered by this document.

## Context
`docs/business/RAAD_Phase3.2_Database_Design_v1.md` §6.3 defines `parents.user_id` as a required
(`NOT NULL`) reference to `iam.users` ("Login is via the linked `users` row (`role=parent`)"), and
§11.3 names `parents.user_id` explicitly as a canonical example of a **cross-context, ID-only
reference** — never a database foreign key, per `.claude/rules/database.md` #3.

Phase 10.6 implemented the `Parent` aggregate (`transport_ops`) per that spec:
`RegisterParentCommand`/`Parent.register()` take `user_id` as a **required, already-valid input**.
The service never creates, calls, or coordinates with `iam.User` — it assumes a `User` row
(`role=parent`) already exists and its id is supplied by the caller.

This is the first dependency, among the five completed bounded contexts, where creating one
aggregate (`Parent`) requires another bounded context's aggregate (`iam.User`) to already exist.
No prior module faced this: `Student` has no `iam` dependency, and `fleet_device`/`organization`/
`tracking` are each self-contained for creation purposes.

Neither `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` nor
`docs/business/RAAD_Phase3.3_API_Contracts_v1.md` specifies:
- which bounded context initiates or owns the end-to-end "register a parent" workflow,
- the order in which the `User` and `Parent` rows are created,
- whether the two creations are coordinated synchronously (in-process) or asynchronously
  (event-driven), or
- how a partial failure (one row created, the other not) is handled.

Per `.claude/rules/workflow.md` #8, business logic implementing this workflow must not be written
until that design is approved. This ADR is the design.

## Problem Statement
How should the platform create a `Parent` (transport_ops) and its linked login-capable `User`
(iam, `role=parent`) as a single coherent registration operation, given that:
- the two rows live in different bounded contexts, each with its own repository, Unit of Work, and
  transaction boundary (`.claude/rules/backend.md` #1–#3),
- `transport_ops` may not perform a cross-module DB read or write into `iam`'s tables
  (`.claude/rules/backend.md` #3), and
- `Parent.user_id` is `NOT NULL` — there is no "create Parent first, backfill user_id later" option
  without either relaxing that constraint (rejected — it's an explicit design requirement, §6.3)
  or holding the `Parent` aggregate in an unpersisted/pending state until the `User` exists?

## Constraints
1. **Modular monolith, strict module seams** (`.claude/rules/architecture.md` #1, #6):
   `iam` and `transport_ops` remain independently owned modules; the solution may not introduce a
   cross-module DB read/write, and may not merge the two into one module.
2. **`Parent.user_id` is required, ID-only, no DB FK** (Database Design §6.3, §11.3;
   `.claude/rules/database.md` #3) — already decided, not reopened here.
3. **Domain events + transactional outbox is the established cross-context integration
   mechanism** in this codebase (`.claude/rules/backend.md` #5; every completed module already
   uses it) — any new cross-context flow should reuse this mechanism rather than invent a second
   one.
4. **Device-plane event-driven mandate does not apply here.** `.claude/rules/architecture.md` #3
   ("device plane communicates with the business plane exclusively through asynchronous domain
   events") is scoped to JT808/JT1078 ↔ business-plane communication, not general business-context
   ↔ business-context orchestration. It is not evidence for or against synchronous orchestration
   between `iam` and `transport_ops`.
5. **No new bounded context** may be introduced to own this workflow (`.claude/rules/architecture.md`
   #6 — ten contexts, fixed set, ADR required to add an eleventh; this ADR does not propose one).
6. **Out of scope for this ADR:** the actual HTTP request/response shape for a "register parent"
   endpoint, Parent-Student linking, notification delivery, and authentication/session issuance —
   each belongs to its own already-scoped-out phase.

## Options Considered

### Option A — Synchronous cross-context orchestration via an application-layer port
`transport_ops.ParentApplicationService` depends on a narrow outbound port (e.g.
`UserProvisioningPort`, defined in `transport_ops/application/ports.py`, implemented in
`transport_ops/infra` by calling `iam`'s own public application-service facade — never `iam`'s
repositories or ORM models directly). The orchestrating use-case calls IAM synchronously to create
the `User`, then creates the `Parent` in the same request, coordinating two separate Units of Work.

- **Pro:** Immediate consistency — the caller gets a fully-formed `Parent` (with a valid `user_id`)
  or a clear synchronous failure. Simple to reason about; no eventual-consistency window during
  which a `Parent` exists without login capability.
  Reuses the existing "port defined by the consuming module, implemented in infra" DI pattern
  already used for every other outbound dependency in this codebase.
- **Con:** Two separate transaction boundaries (`iam`'s UoW, `transport_ops`'s UoW) cannot be
  committed atomically — a genuine distributed-transaction problem. If the `iam.User` commit
  succeeds but the `transport_ops.Parent` commit then fails, an orphaned `User` (role=parent, no
  linked `Parent` profile) is left behind, requiring compensation.

### Option B — Event-driven saga: `iam` creates the `User`, publishes an event, `transport_ops` reacts
A `UserInvited` (or a new `ParentUserProvisioned`) domain event, published by `iam` via the
existing outbox (`.claude/rules/backend.md` #5), is consumed by a `transport_ops` subscriber that
creates the `Parent` row asynchronously once the event arrives.

- **Pro:** No cross-module synchronous call; each module's Unit of Work stays genuinely
  independent, matching the "no synchronous RPC" flavor of the outbox pattern used elsewhere.
- **Con:** The registration workflow's completion is no longer visible to the original caller —
  the API response for "register a parent" can't return a finished `Parent` object, only an
  "accepted, pending" state, which is a worse experience for an Org Admin registering a parent
  interactively (this is an admin-initiated, user-facing action, not a background reaction to
  device telemetry — the domain shape that motivated the outbox pattern elsewhere in this
  codebase). It also requires building consumer/subscriber infrastructure for `transport_ops` that
  does not otherwise exist yet (the `events/` folder in every completed module today is
  publish-only scaffolding).

### Option C — `transport_ops` owns both writes directly (bypass module seams)
`ParentApplicationService` reads/writes `iam.users` directly via a shared repository or raw query.

- **Pro:** None beyond expedience.
- **Con:** Directly violates `.claude/rules/backend.md` #3 (no cross-module DB reads/writes) and
  `.claude/rules/architecture.md` #1 (strict internal modules). Rejected outright — included only
  for completeness.

### Option D — A dedicated orchestrating use-case outside both modules (e.g. in `interfaces/http`)
An API-layer handler (not inside either module) calls `iam`'s and `transport_ops`'s public
application services in sequence, with manual compensation on partial failure.

- **Pro:** Keeps both modules' application services simple and single-purpose; no new port needed
  in either module.
- **Con:** Puts orchestration and compensation logic in the interfaces layer, which
  `.claude/rules/backend.md` #2 reserves for routing/schemas, not use-case logic — every existing
  use-case, including cross-aggregate ones, is orchestrated inside an application service
  (`.claude/rules/architecture.md` §4.1 in the LLD: "application layer... enforces cross-aggregate
  coordination"). This option relocates that responsibility somewhere the codebase's own layering
  rule doesn't sanction.

## Recommended Option
**Option A — synchronous cross-context orchestration via an application-layer port**, owned by
`transport_ops`, with explicit compensation for the partial-failure case, subject to review.

Rationale: this is an admin-initiated, latency-sensitive, user-facing workflow (an Org Admin
registering a parent and expecting a usable result), not a background/telemetry reaction — the
same distinction the LLD already draws between synchronous application-service orchestration
(§4.1, the default for all use-cases) and the outbox/event mechanism (§10, reserved for
post-commit fan-out to other contexts, e.g. notifications). Option B's asynchronous shape fits
that latter category, not this one. Option A also requires no new infrastructure (no consumer/
subscriber machinery) beyond one new port + one new infra adapter, both following patterns already
proven in this codebase (every module's `application/ports.py` + `infra/` already follows exactly
this "interface defined by the consumer, implemented by the provider" shape).

The atomicity gap (two Units of Work, no distributed transaction) is real but bounded and
compensable — see **Failure Handling** below — and is preferred over Option B's UX regression or
Option D's layering violation.

## Sequence of Operations
1. Caller (Org Admin, via `POST /parents` or a dedicated registration endpoint — exact HTTP shape
   is a later, separate decision) submits parent registration details: `organization_id`,
   `full_name`, `phone` (optional), and the identity fields needed to create a login (e.g. `email`).
2. `transport_ops.ParentApplicationService` (the orchestrating use-case) begins:
   a. Calls the `UserProvisioningPort` (outbound port owned by `transport_ops`, satisfied by an
      `infra` adapter that calls `iam`'s own public application-service facade — never `iam`'s
      repository or ORM layer directly, preserving `.claude/rules/backend.md` #1's "only public
      surface" rule) to create a `User` with `role=parent`, scoped to `organization_id`.
   b. `iam`'s own application service creates the `User` aggregate, records its domain event(s)
      (e.g. `UserInvited`), and commits **its own Unit of Work** — this commit is real and durable
      the moment step (a) returns successfully.
   c. `transport_ops.ParentApplicationService` receives the new `user_id` and proceeds exactly as
      Phase 10.6 already implements: `Parent.register(user_id=..., ...)`, records `ParentRegistered`,
      commits **`transport_ops`'s own Unit of Work**.
3. On success, both rows exist, `Parent.user_id` references the just-created `User`, and the
   response returns the full `ParentDTO` to the caller synchronously — no change to the DTO shape
   already implemented in Phase 10.6.

## Responsibilities
**IAM (`iam`)**
- Owns `User` creation, uniqueness (email), password/credential setup or invite-flow issuance, and
  `role=parent` assignment.
- Exposes creation as a call on its own public application-service facade (its `__init__.py`
  surface, per `.claude/rules/backend.md` #1) — never exposes its repository or ORM models to
  `transport_ops`.
- Has no knowledge of `Parent`, `transport_ops`, or the registration workflow that consumes it —
  from `iam`'s perspective this is just "create a user."

**Transport Operations (`transport_ops`)**
- Owns the registration workflow itself: it is the caller/orchestrator, initiating the `User`
  creation and then creating the `Parent` profile that references it.
- Owns the `UserProvisioningPort` interface (defined in `transport_ops/application/ports.py`,
  following the exact pattern `TransportOpsUnitOfWork` and every other outbound port in this module
  already use) and the DI binding of its concrete `iam`-calling adapter
  (`core/di/bootstrap.py`, mirroring how every other cross-cutting port is bound today).
- Owns compensation on partial failure (below).

## Failure Handling
Two independent commits mean three failure points, each handled differently:

1. **`User` creation fails (step 2a/2b).** No `Parent` has been attempted yet. The registration
   fails cleanly; nothing is committed on either side. No compensation needed.
2. **`Parent` creation fails after `User` creation succeeded (step 2c).** This is the orphan case:
   a `User` (role=parent) exists with no linked `Parent` profile. Two compensations are viable and
   should both be evaluated at implementation time, not decided here:
   - **(preferred) Retry-safe idempotent recovery:** rather than deleting the orphaned `User`,
     surface the failure to the caller with the already-created `user_id`, and allow a **retry** of
     parent registration against that existing `user_id` (i.e. `RegisterParentCommand` should
     tolerate being re-driven against a `User` that already exists, rather than assuming it must
     create a fresh one every time). This avoids a destructive rollback across a module boundary
     transport_ops does not own, and matches the "at-least-once, idempotent handler" posture the
     LLD already mandates for outbox consumers (§10 wording,
     `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` line "every handler is idempotent").
   - **Compensating action:** `transport_ops` calls a `disable`/`revoke` operation on the same
     `UserProvisioningPort` to deactivate the orphaned `User` if retry is not appropriate (e.g. the
     caller abandons the flow). This is a compensating action, not a two-phase commit — `iam`'s own
     Unit of Work still owns and commits that state change independently.
3. **The orchestrating request itself is retried by the caller** (e.g. network timeout after step
   2b but before the caller sees the response). The workflow must be safe to re-invoke — this is
   why idempotent recovery (above) is preferred over a hard rollback: a naive delete-on-failure
   compensation is itself not safe against a retry racing the compensation.

Every step of this workflow — the `User` creation call, its success/failure, the `Parent` creation,
and any compensating action — must be audit-logged (`.claude/rules/security.md` #8), since parent
registration creates a new login-capable identity.

## Why This Aligns with DDD and Clean Architecture
- **Aggregate boundaries are preserved.** `User` and `Parent` remain two separate aggregate roots,
  each still solely responsible for its own invariants — this ADR does not merge them or let one
  reach into the other's internal state. `transport_ops` only ever holds `iam`'s `user_id` as an
  opaque identifier (Database Design §11.3), never a live reference to the `User` aggregate itself.
- **Dependency direction is unchanged.** The new `UserProvisioningPort` lives in
  `transport_ops/application/ports.py`, implemented by `transport_ops/infra` — exactly the existing
  `api → application → domain`, `infra implements domain-owned interfaces` shape
  (`.claude/rules/backend.md` #2). `transport_ops`'s domain layer still never imports `iam`,
  FastAPI, or SQLAlchemy.
- **The application layer remains the sole orchestrator.** Cross-aggregate coordination living in
  `ParentApplicationService` matches the LLD's own definition of that layer's job (§4.1: "enforces
  cross-aggregate coordination... manages the transaction boundary") — nothing new is invented,
  this ADR just extends "cross-aggregate" to "cross-context" using the same layer.
- **No cross-module DB access is introduced.** `transport_ops` never touches `iam`'s tables,
  models, or repositories — only its public application-service surface, preserving
  `.claude/rules/backend.md` #1 and #3 exactly.
- **Module seams stay extraction-ready.** Because the only coupling is a port interface + one
  facade call (not a shared table or shared repository), `iam` and `transport_ops` could still be
  split into separate deployables later (`.claude/rules/architecture.md` #7) by swapping the
  `UserProvisioningPort` adapter for a network call — the same extraction story every other
  cross-cutting port in this codebase already tells.

## Impact on Future Parent Portal and Mobile App Development
- **Parent Portal / mobile login** (`.claude/rules/flutter.md`) depends on this ADR being resolved
  first: a Parent cannot log in until its `User` row exists with valid credentials, so the
  registration workflow this ADR defines is a hard prerequisite for any Parent-facing
  authentication work, not an independent later phase.
- **No change to the Parent domain model or its DTOs.** This ADR only adds orchestration *above*
  the already-implemented `Parent` aggregate — `ParentDTO`, `Parent.register()`, and the existing
  `/parents` routes are unaffected in shape; only *how* `user_id` gets populated changes (via this
  orchestration instead of an already-known input).
- **Sets the pattern for Parent-Student linking** (explicitly deferred, per the Phase 10.6 scope) —
  that phase will need its own cross-aggregate coordination (`Parent` ↔ `Student` ↔
  `student_parents`), entirely within `transport_ops`, so it does not need this ADR's cross-context
  mechanism; but the registration workflow here must land first since a `student_parents` link is
  meaningless without a registered `Parent`.
- **Sets a precedent for `Driver`** (`drivers.user_id FK→users`, Database Design §6.1), which has
  the identical `transport_ops` ↔ `iam` shape as `Parent` and was already flagged as unaddressed —
  once this ADR is accepted, the same `UserProvisioningPort` should be reused for Driver
  registration rather than a second, parallel mechanism being designed independently.
- **Notification/FCM token registration** (Database Design §7.6/§7.7, `notifications` context,
  still scaffold-only) will eventually key off the same `user_id` — no impact on that context's own
  design, but confirms `user_id` is the correct join key for Parent's future notification
  preferences once `notifications` is implemented.

## References
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §6.3 (`parents.user_id`), §6.1
  (`drivers.user_id`, same shape), §11.3 (cross-context reference rule)
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §4.1 (application layer orchestration
  responsibility), §10 (outbox pattern, at-least-once/idempotent handler mandate)
- `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §4.1 (`/users`), §4.3 (`/parents`)
- `.claude/rules/architecture.md` #1, #3, #6
- `.claude/rules/backend.md` #1, #2, #3, #5
- `.claude/rules/database.md` #3
- `.claude/rules/security.md` #8
- `.claude/rules/workflow.md` #7, #8 (approved-design-before-implementation gate this ADR satisfies)
- `docs/architecture/adr/0001-business-entity-module-mapping.md` (Parent owned by `transport_ops`,
  not split into `iam`)
