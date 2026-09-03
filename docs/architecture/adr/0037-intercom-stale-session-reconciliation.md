# ADR-0037: Intercom Stale-Session Reconciliation Backstop

## Status

**Accepted** (same session as ADR-0036, 2026-09-01, user directive: close a real live-found gap
before it can recur). Implemented same session — this document itself was not written at the
time, a real, disclosed documentation gap this entry closes retroactively, matching the posture
`.claude/rules/documentation.md` #2/`workflow.md` #8 require and the precedent ADR-0025 already
set for "a later ADR is where a reader lands for a correction." Every citation of "ADR-0037" in
the codebase (`backend/raad/core/config/settings.py`, `backend/raad/modules/video/application/
services.py`, `backend/raad/modules/video/infra/repositories.py`,
`backend/tests/integration/test_video_repository.py`, `backend/tests/unit/
test_video_application.py`, `frontend/src/features/video/useIntercomController.ts`/`.test.tsx`,
`frontend/src/shared/api/client.ts`) predates this file — this document formalizes what those
comments already describe in detail, it does not introduce new design.

## Context

ADR-0036's own §2 "one active intercom session per device" invariant depends on a `REQUESTED`/
`ACTIVE` intercom session eventually reaching a terminal state (`ENDED`/`FAILED`) — normally
driven by the relay's own `VideoSessionActivated`/`Ended`/`Failed` events, consumed by
`backend/raad/modules/video/events/subscribers.py` (ADR-0026 §7's own reconciliation-from-events
mechanism, unchanged and still primary).

**A live-found incident (2026-09-01, same session ADR-0036 was implemented in) proved that
primary path alone is not sufficient.** A poisoned broker message wedged the shared event-consumer
pipeline for over an hour. A `REQUESTED` intercom session's own correctly-published
`VideoSessionFailed` event was never processed as a result — the session stayed open in the
database indefinitely, and ADR-0036 §2's own working-as-designed exclusivity check then correctly,
but unhelpfully, rejected every other operator's own attempt to talk to that same bus, for as long
as the pipeline stayed wedged. The bug was in the shared event pipeline, not in anything
intercom-specific — but intercom is the one purpose where a single stuck session has an immediate,
visible, cross-operator blocking effect (ordinary live/playback video has no equivalent problem:
many simultaneous viewers of the same device is already the correct, unblocked behavior there).

## Decision

**A scheduled, `purpose=INTERCOM`-only reconciliation job, independent of the event pipeline.**
`VideoApplicationService.reconcile_stale_intercom_sessions` (`backend/raad/modules/video/
application/services.py`) lists every open (`REQUESTED`/`ACTIVE`) `VideoSession`, and force-fails
(`reason="reconciliation_stale_timeout"`) any `purpose=INTERCOM` one older than
`stale_after_seconds` (measured from `started_at` or `created_at`, whichever exists) — a pure
defense-in-depth backstop, not a replacement for the primary event-driven path, and explicitly
**not** extended to ordinary live/playback sessions (those aren't harmful to any other user the
same way, and reconciling them would be solving a problem nothing has actually reported).

- **Scheduling**: `backend/raad/interfaces/workers/bootstrap.py` registers it as a periodic job
  (mirrors `BillingApplicationService.sweep_expired_subscriptions`'s exact shape) at
  `intercom_reconciliation_interval_seconds` (default 60s).
- **Timeout**: `intercom_stale_session_timeout_seconds` (default 180s) — deliberately well past
  the relay's own worst-case internal timeout (`services/jt1078/src/session/session_manager.py`'s
  `ingest_timeout_seconds` (30s) + `absolute_idle_seconds` (60s) defaults), so this backstop never
  races the primary path under normal operation; it only ever fires when the primary path has
  already failed to act for an abnormally long time.
- Both settings live in `backend/raad/core/config/settings.py`'s `WorkerSettings`, matching every
  other worker's own tunable-interval precedent.

**A real repository bug found and fixed while implementing this** — `SqlAlchemyVideoSessionRepository.
list_all()` (`backend/raad/modules/video/infra/repositories.py`) used to convert rows straight
through `model_to_video_session` without registering them via `self._track` (unlike `get()`), so a
mutation made to an entity obtained through `list_all()` was silently discarded at `commit()` —
`flush_tracked_changes()` only re-projects tracked entities. `reconcile_stale_intercom_sessions`
is the *first* `list_all()` caller that ever mutates what it lists (the only prior caller,
`list_active_sessions_for_requester`, is read-only), which is exactly why the in-memory fake
repository used by this module's own unit tests never caught it — only a real-database integration
test exposed it (`backend/tests/integration/test_video_repository.py`). Fixed by tracking every
row `list_all()` returns, identically to `get()`.

**Frontend: `keepalive: true` on the intercom stop-on-unmount call** (`frontend/src/shared/api/
client.ts`'s `RequestOptions.keepalive`, threaded through `stopVideoSession` and used by
`useIntercomController.ts`'s unmount-cleanup effect). A UX/latency improvement only — lets the
browser complete the `POST /video/sessions/{id}/stop` call even if the tab is closing/navigating
away, rather than the request being silently aborted mid-flight — **not** the correctness
guarantee on its own; this ADR's own scheduled job is what actually guarantees a dead session can
never block another operator forever, regardless of whether the keepalive request is ever sent or
received.

## Consequences

- New `WorkerSettings` fields (`intercom_reconciliation_interval_seconds`,
  `intercom_stale_session_timeout_seconds`), no schema/migration.
- One new scheduled job, `interfaces/workers/bootstrap.py`, following the existing
  `RedisLockPort`-guarded periodic-job pattern every other scheduled job in this codebase already
  uses (`.claude/rules/backend.md` #5's transactional-outbox discipline is unaffected — this job
  reads/writes only through the existing `VideoUnitOfWork`/`AuditWriter` pipeline, no new event
  type).
- `SqlAlchemyVideoSessionRepository.list_all()` now tracks every row, closing a latent bug that
  would have silently affected any *future* mutating `list_all()` caller too, not just this one.
- Ordinary live/playback sessions remain reconciled only by the primary, event-driven path — a
  disclosed, deliberate scope boundary, not an oversight.

## Verification

- Backend: unit tests for `reconcile_stale_intercom_sessions` (`backend/tests/unit/
  test_video_application.py`) — scoping to `purpose=INTERCOM` only, the `stale_after_seconds`
  boundary, and that a non-stale open session is left untouched.
- Integration: `backend/tests/integration/test_video_repository.py` — the real-database regression
  test proving `list_all()` now tracks mutations that `commit()` actually persists (the exact bug
  class the in-memory fake repository could not catch).
- Frontend: `useIntercomController.test.tsx`'s existing unmount-cleanup test asserts
  `stopVideoSession` is called with `{ keepalive: true }` specifically on the unmount path,
  distinct from an explicit Stop-button click (which does not pass it).

## References

- `docs/architecture/adr/0036-two-way-intercom-implementation.md` — the feature this backstop
  protects; §2's own one-active-intercom-session-per-device invariant is what a stuck session
  incorrectly, if "correctly," enforced against every other operator during the live incident.
- `docs/architecture/adr/0026-parent-video-access-authorization.md` §7 — the primary,
  event-driven reconciliation path this ADR backstops, unchanged.
- `docs/architecture/adr/0024-jt1078-video-relay-architecture.md` §16 — the still-open, separate
  "no lifecycle event ever arrives at all" gap for *ordinary* live/playback sessions, which this
  ADR deliberately does not close (out of scope, per the Decision section above).
