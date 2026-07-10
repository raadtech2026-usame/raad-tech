# Skill: Security Review

## Purpose
Check a change for security regressions against RAAD's core invariants before merge.

## Workflow
1. Apply the tracking-visibility predicate check: does this change preserve capability ∧ scope ∧
   ownership ∧ time-window enforcement for any live-tracking surface it touches?
2. Confirm tenant isolation: new queries filtered by `organization_id`; RAAD-staff queries filtered
   by region/org scope where applicable.
3. Confirm the safety-vs-billing policy is not bypassed — safety capabilities must remain
   unconditionally granted regardless of subscription status.
4. Confirm video access remains Org-Admin-only by construction.
5. Confirm any new external input (webhooks, device frames, user input) is validated/untrusted by
   default — payment callbacks especially must be signature-verified.
6. Confirm audit logging is present for any new sensitive action (video session, cross-tenant access
   attempt, payment state transition, admin action).
7. Confirm no secrets or PII are logged in plaintext.

## When to use
Before merging any change touching authentication, authorization, tenancy, video, billing, or
external input handling. Always for changes touching minors' PII (location, identity).
