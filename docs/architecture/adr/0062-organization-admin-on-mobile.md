# ADR-0062: Organization Admin on mobile, read-only

- **Status:** Accepted
- **Date:** 2026-10-07
- **Amends:** `.claude/rules/flutter.md` #1 ("no admin features on mobile")
- **Extends:** ADR-0061 (mobile app). **Does not change:** ADR-0026 (video), ADR-0031 (fleet
  overview), ADR-0053 (daily operations), ADR-0055 (safety alerts)

## Context

RAAD Mobile v1.0.0 serves parents and drivers. `.claude/rules/flutter.md` #1 said the app has
two role experiences and no admin features. On 2026-10-07 the product owner asked that an
Organization Admin can sign in to the same app and see their own organization. That request
is the change of requirement the rule needs; this ADR records it.

An Organization Admin signing in to v1.0.0 reaches a screen saying the account cannot use the
app. The person who runs a school's transport therefore has nothing in their pocket while
buses are on the road, which is when an uncovered trip or an SOS matters most.

Two things were checked before deciding:

- **Roles.** The backend has seven roles: `founder`, `regional_manager`, `support_staff`,
  `finance_staff`, `org_admin`, `driver`, `parent`. There is no separate "organization user"
  role; `org_admin` is the only organization-side account. None is invented here.
- **Permissions.** Every endpoint this ADR uses is already called by the web dashboard and is
  already granted to `org_admin`. None is granted to `parent`. `driver` holds only
  `transport_ops.trips.list`, which is older than this ADR and is not used by any driver
  screen.

## Decision

### 1. One app, three experiences

The role in the session decides the experience: parent, driver, organization admin. There is
one login screen and one forced password change for all three. RAAD's own staff roles keep
the "use the web dashboard" screen: their work is cross-organization and is not designed for
a phone.

Showing a screen is presentation only (`.claude/rules/frontend.md` #2). A parent or driver
who reached the admin screens by any means would get 403 from every request they make.

### 2. Read-only, and only what is useful on the move

The admin experience answers three questions: what is running, what needs attention, which
buses are connected.

| Screen | Endpoint (existing) | Permission (existing, `org_admin` holds it) |
|---|---|---|
| Overview: counts | `GET /vehicles`, `/trips?filter[status]=in_progress`, `/students`, `/drivers`, `/routes` with `page_size=1`, reading `page.total` | `fleet_device.vehicles.read`, `transport_ops.{trips,students,drivers,routes}.list` |
| Overview: buses online | `GET /tracking/vehicles/online` | `tracking.vehicles.read_latest` plus the route's own role check (ADR-0031) |
| Today | `GET /daily-operations?date=` | `transport_ops.daily_operations.read` |
| Alerts | `GET /safety-alerts?status=open&status=acknowledged` | `tracking.safety_alerts.list` |
| Notifications, account | as for the other roles | own data |

No backend change, no new route, no new permission, no migration.

Nothing is written from these screens. Acknowledging an SOS sends a command to the terminal
(ADR-0057), cancelling a trip notifies parents (ADR-0054), and both deserve the web
dashboard's confirmation steps and context. They can be added later, one at a time, each
with its own decision.

Finance, registration, timetable editing, reports and device management stay on the web.

### 3. No video for the admin on mobile

`.claude/rules/frontend.md` #4 keeps Org Admin video on the web dashboard, and
`.claude/rules/flutter.md` #3 allows mobile video only for a parent with an individual grant
(ADR-0026). Neither changes. The admin screens have no camera entry.

### 4. One design system, light and dark

The app's colours now come from the web dashboard's `frontend/src/styles/tokens.css`: the
same primary blue, surfaces, borders, text and status colours, and the same dark theme
(`[data-theme="dark"]`). Like the web, the app follows the device setting until the person
chooses light or dark, and remembers the choice on the device. This applies to all three
experiences; the admin does not get a theme of its own.

Not carried over: the web's typefaces (Sora, Manrope). Bundling them is a new asset with its
own licence review and is left for a separate change.

### 5. Honest figures

A count that cannot be read is shown as a dash, never as zero. If the first request is
refused (offline, signed out, the organization's subscription has lapsed) the overview shows
the server's own message instead of a page of dashes. The online list shows "N of M" when the
server's cap of 100 applies.

## Consequences

- `.claude/rules/flutter.md` #1 is amended to three experiences.
- The web dashboard's "mobile-only roles" list is unchanged: parent and driver still have no
  web dashboard.
- An Org Admin whose organization's subscription is inactive is refused by the server
  (ADR-0039) on mobile exactly as on the web.
- A new APK is needed for any of this to reach a phone; v1.0.0 is unaffected until then.

## Not built

- Any write from the admin screens.
- Live map for the admin: the online list has no positions to draw until the latest-position
  cache is confirmed in production.
- Search and filters; lists of students, parents or drivers.
- Push notifications (unchanged from ADR-0061 §8).
