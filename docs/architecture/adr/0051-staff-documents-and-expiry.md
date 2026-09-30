# ADR-0051: Staff Documents and Expiry Notifications

## Status

**Accepted** (2026-09-30), Phase 1 of the transport-management roadmap, with ADR-0049.

## Context

Nothing in RAAD records a credential or its expiry: not a licence, a medical certificate or a police
clearance. School-transport operators need to see what is about to lapse before an unqualified person
drives children.

There is no file store and no upload dependency, the same gap that deferred expense attachments in
ADR-0047.

## Decision

### 1. Organization-configurable document types

`staff_document_types` (organization, name, `alert_lead_days`, archived).

- Existing organizations are seeded with:
  - Driving licence
  - National ID/Passport
  - Medical certificate
  - Police clearance
  - First-aid certificate
  - Other
- **Lead days are set per type,** default 30 and 7.

### 2. `staff_documents`: metadata only

Each row records staff, type, number, issued date, expiry date, `replaced_by_id` (the renewal chain)
and notes.

- **No file, scan or upload.** An ID is stored as type, number and expiry, never an image.
- **Status is computed** from the expiry date and the type's lead days, never stored:
  - `valid`
  - `expiring`
  - `expired`
  - `no_expiry`
  - `superseded` (replaced by a renewal)
- **Documents are optional.**
- **Renewal** records a new document and links the old one to it. History is kept.
- **Numbers are sensitive:** Org Admin only (ADR-0049 §6), and never written into events or logs.

### 3. Expiry notifications

A worker job, `notify_expiring_staff_documents`, runs under the existing scheduler lock. It is on by
default and switched off with `RAAD_WORKERS__STAFF_DOCUMENT_EXPIRY_ALERTS=false`.

For every current (not superseded) document it computes the thresholds crossed: each lead day, plus 0
for expired.

- It notifies **every active Org Admin of that organization, in-app**, using the existing `system`
  notification type. No new notification-enum value is added.
- It then records the smallest threshold already sent on the document (`alerted_threshold_days`), so
  each threshold is sent **exactly once**. A new or renewed document starts fresh.
- It composes three modules' application services in the worker, never their tables:
  - `transport_ops` (documents due);
  - `iam` (active org admins of the organization);
  - `notifications` (create).

## Consequences

- There is no enforcement in this phase. Blocking or warning on trips when a document has expired
  belongs to Phase 4.
- Attachments wait for a file store and an approved upload dependency.
