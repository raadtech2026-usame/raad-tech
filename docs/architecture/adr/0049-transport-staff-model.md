# ADR-0049: Transport Staff Model — one person record, Driver as its driving extension

## Status

**Accepted** (2026-09-30). This is Phase 1 ("Transport People Foundation") of the transport-management
roadmap. The user approved the Phase 1 discovery report and adopted its recommended answer to every
business question.

## Context

A school bus is crewed by more people than its driver: attendants, assistants, conductors,
supervisors. RAAD modelled only one of them.

- **`Driver`** (`transport_ops`, `drivers`) holds `license_no`, `status` and a **required**
  `user_id`.
  - Every driver has a login: `POST /drivers` always provisions an `iam.User`, ADR-0003.
  - It carries no name or phone. Those live on the login account.
  - Every trip points at it (`trips.driver_id`, an in-module foreign key).
- There was no record for anyone else on a bus. Nothing held an operational profile either:
  employee reference, start date, emergency contact.
- `iam.users` email and phone are unique platform-wide, so a login cannot be the identity of a person
  who has no login.

Precedents inside this module:
- `Student` is a person record with no login.
- `Parent` keeps its own `full_name`/phone/emergency contact beside a login link, so an operational
  name that differs from the login's is already accepted.

## Decision

### 1. `TransportStaff` is the person record; `Driver` becomes its driving extension

`transport_staff` (organization-owned) holds the operational identity:

- full name, phone and alternate phone;
- job title;
- employee reference (optional, unique per organization when set);
- start date;
- status (`active`, `inactive`, `left`);
- emergency contact name/phone;
- notes.

A staff member **may exist with no login and with no bus**.

`drivers` gains a required, unique `staff_id`. `Driver` keeps exactly what it had: licence, status, the
`user_id` login link, and every trip reference. **A staff member can drive trips only if they have a
`Driver` row**, and a `Driver` row still requires a login, as the Project Brief requires ("Drivers must
authenticate before operating a vehicle", §7.6).

Three roles, three sources of truth, no duplicate person:

| Question | Answered by |
|---|---|
| Who is this person, how do we reach them? | `transport_staff` |
| May they drive a trip? | the linked `drivers` row (licence + login) |
| How do they sign in? | `iam.users` |

The name exists on both the staff record and the login account once a person has a login, as it
already does for `Parent`. Operations display the staff record; sign-in uses the account.

### 2. Configurable job titles

`transport_staff_roles` (organization, name, sort order, archived).

- **A title is a label and grants nothing.** "Driver" is a title; driving is the `Driver` extension. The
  UI flags a mismatch (a "Driver" title with no driver profile, or the reverse) but there is no hard
  rule.
- Every existing organization is seeded with Driver, Attendant, Assistant, Conductor and Supervisor.
- A new organization starts empty and can add the same defaults with one action.
- A title in use can be archived, never deleted.

### 3. Paths for creating people

- **New staff member:** `POST /transport-staff`, with no login.
- **Existing staff member gains a login:** "give driver access" provisions the login through the
  existing `UserProvisioningPort` (temporary password, ADR-0003) and creates the linked `Driver`, so no
  second person record ever exists.
- **`POST /drivers`** keeps its contract and now also creates the staff record in the same transaction.

Non-driver staff get no login role in this phase (Phase 5).

### 4. Leaving

Setting a staff member to `left` does all of the following in one transaction:

- ends every open bus assignment on that day (ADR-0050);
- marks a linked `Driver` inactive;
- keeps all history.

### 5. No new bounded context

The staff model lives in `transport_ops`, which already owns `Driver`, `Trip`, `Route` and
`StudentAssignment`. A separate module would have to reach drivers and trips through application
services and would duplicate driver identity, the very thing this ADR avoids.
`.claude/rules/architecture.md` #6 stays at twelve modules.

### 6. Visibility

| Who | Access |
|---|---|
| Org Admin | everything |
| Founder, Regional Manager, Support Staff | read names, titles, status, assignments and document status and expiry; **emergency contacts and document numbers are omitted** from their responses |
| Finance Staff, Driver, Parent | no staff permission |

Parents see nothing about staff. A driver reads their own profile through `/me`.

## Consequences

- **Migration:**
  - one `transport_staff` row per existing driver, with name and phone copied from the linked login
    account;
  - `drivers.staff_id` is filled, then made required;
  - default titles are seeded for existing organizations.
- **`GET /drivers` and `/me/driver-profile` gain fields;** nothing is removed.
- **Out of scope:**
  - payroll, recruitment, attendance, leave, appraisal and benefits;
  - absence and substitutes (Phase 2), incidents (Phase 3), compliance enforcement (Phase 4);
  - staff mobile flows and a non-driver login role (Phase 5).
- **One person as both parent and staff:** remains two records, because logins are unique by
  phone/email. A later identity design can join them.
