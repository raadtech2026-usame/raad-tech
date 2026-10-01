# ADR-0058: Staff Document Requirements and Compliance Status

## Status

**Accepted** (2026-10-01). Phase 4 ("Documents & Compliance expansion") of the transport-management
roadmap, with ADR-0059. The user adopted the recommended answer to all nine Phase 4 discovery
questions. Amends ADR-0051 §2 ("Documents are optional").

## Context

ADR-0051 records staff documents as metadata and alerts Org Admins before one expires. It defers
the rest: "There is no enforcement in this phase. Blocking or warning on trips when a document has
expired belongs to Phase 4." ADR-0049 defers "compliance enforcement (Phase 4)".

Two things are missing before anything can be enforced:

- **Nothing says a document is required.** A document type has a name, lead days and an archived
  flag. A driver with no licence on record looks the same as a driver whose licence is valid, so
  "missing" cannot be detected.
- **A person has no compliance status.** Each document has a status; a person does not.

Production holds no staff documents yet. A rule that treated every existing type as required
would mark every staff member non-compliant the moment it shipped.

## Decision

### 1. A document type says who must hold it

`staff_document_types` gains two columns:

- `required_for`: `none` (default), `drivers` or `all_staff`.
  - `drivers` means staff who have driver access (a `Driver` record), not a job title. A title is a
    label and grants nothing (ADR-0049 §2).
  - `all_staff` means every staff member, drivers included.
- `enforcement`: `warn` (default) or `block`. It only has meaning when `required_for` is not
  `none`. What each does is ADR-0059.

Both defaults leave behaviour exactly as it is today. An organization opts in type by type. No
existing type is changed by the migration, and no default type is seeded as required.

An archived type requires nothing. The setup screen says so before a required type is archived.

### 2. Compliance is computed, per person and per day, never stored

For a staff member on a given day, each requirement that applies to them is checked:

- **Met:** they hold a current document of that type (not superseded) with no expiry date, or
  with an expiry date on or after that day. A document is valid through its expiry date.
- **Expired:** every current document of that type expired before that day.
- **Missing:** no current document of that type.

Missing and expired both mean the requirement is not met. They are reported with different
reasons.

The person's status is one of:

- `compliant`: every applicable requirement is met.
- `expiring`: compliant, and a document that meets a requirement is inside its type's lead days.
- `not_compliant`: at least one requirement is not met.

A person is **blocked** on a day when a requirement they do not meet belongs to a type whose
enforcement is `block`.

Compliance applies to staff whose status is `active` or `inactive`. Someone who has `left` has no
compliance status.

"Today" is the service's UTC date, as everywhere else in this module. In an organization ahead of
UTC, a document stays valid for a few hours past local midnight on the day after it expires.

### 3. Where it is shown

- Each staff record carries its compliance status and reasons: the type name, `missing` or
  `expired`, and the expiry date. **Never the document number.**
- `GET /staff-compliance` lists staff who are `not_compliant` or `expiring`, worst first. It
  extends the expiring-documents panel.
- `GET /staff-document-types/{id}/impact?required_for=…` returns how many staff the setting would
  apply to and how many of them would not be compliant today. The setup screen shows it before a
  requirement is saved. It reads only.

### 4. Permissions and privacy

No new permission. Reading compliance uses `transport_ops.staff_documents.list`; changing a
type's requirement uses `transport_ops.staff_documents.manage`.

Founder, Regional Manager and Support Staff see status and reasons, read-only. Document numbers
stay Org Admin only (ADR-0049 §6). Drivers and parents see nothing.

`StaffDocumentTypeSaved` gains `required_for` and `enforcement`. No compliance event exists:
status is computed on read. No event or audit row carries a document number.

### 5. The driving licence is not unified

`Driver.license_no` stays as it is. The "Driving licence" document type is the compliance record
when an organization marks it required. There is no automatic link and no data migration between
the two.

## Consequences

- **Migration:** two additive columns and two enum types, with defaults `none` and `warn`. No row
  changes meaning. The downgrade drops the columns and the types.
- A missing required document raises no scheduled alert of its own, because it has no date to
  alert on. It appears in the compliance view, on the staff record, and through ADR-0059 on the
  daily board and in uncovered-trip alerts. Expiry alerts (ADR-0051 §3) are unchanged.
- **Not built:**
  - document files or scans (ADR-0051 stands: metadata only);
  - vehicle documents;
  - requirements per job title;
  - approval or verification workflows;
  - staff reading or submitting their own documents (Phase 5);
  - compliance reports (Phase 6).
