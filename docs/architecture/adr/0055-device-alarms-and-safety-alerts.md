# ADR-0055: Device Alarm Taxonomy and Safety Alerts

## Status

**Accepted** (2026-09-30), Phase 3 of the transport-management roadmap ("Safety & Incidents"),
with ADR-0056 and ADR-0057. Product decisions taken by the user on 2026-09-30 ("use your
recommended answers"). Closes Known Issues #7 and #8.

## Context

Every JT/T 808 `0x0200` report carries a 32-bit alarm word (Table 5.10 of the supplier's
`MDVR-808-1078-spec.pdf`). RAAD stores it raw on `vehicle_positions.alarm_flags` and shows it
nowhere; `0` there means "not interpreted", not "no alarm" (Known Issue #8). `DeviceAlarmRaised`
is defined in the device gateway and never constructed (Known Issue #7). So when a driver presses
the SOS button, or the terminal reports a collision, nobody is told.

The Phase-2 architecture (§6, "Normalization / ACL") already places "alarm-bit conventions" in
the device gateway's vendor adapter layer. This ADR fills that slot.

## Decision

### 1. The taxonomy lives in the device gateway

A table in the JT/T 808 adapter maps alarm bits to canonical `alarm_type` names:

| Bit | `alarm_type` | Critical |
|---|---|---|
| 0 | `sos` | yes |
| 1 | `overspeed` | no |
| 2 | `fatigue` | no |
| 29 | `collision` | yes |
| 30 | `rollover` | yes |
| 31 | `illegal_door_open` | no |
| 8 | `power_cut` | no |
| 11 | `camera_fault` | no |

Other bits are not interpreted in this phase. A new vendor maps its own convention onto the same
names in its own adapter; the backend never sees a vendor bit.

### 2. Only a rising edge is published

`DeviceAlarmRaised` (one event per newly set bit) is published when a recognised bit is set in a
report and was not set in the previous report from that terminal. The previous word is kept per
terminal in the gateway's cache Redis (`device-gateway:alarm-flags:{terminal_id}`, 30-day TTL,
swapped atomically with `SET … GET`), so a gateway restart does not re-raise alarms still set.
It is a key of its own rather than a read of the latest-position snapshot, because the snapshot
is keyed by vehicle and written after the report, so it cannot give the previous word atomically. A backfilled report (`0x0704`, or late) carries
`backfill=true`, never raises an alarm on its own, and is handled at the backend (§4).

The event carries `terminal_id`, `organization_id`, `vehicle_id`, `device_id`, `alarm_type`,
the raw `alarm_flags`, the report's position and speed, `event_time` and `received_at`.

### 3. `SafetyAlert` in `tracking`

A safety alert is device telemetry tied to a vehicle, like a geofence crossing, so it belongs to
`tracking`. A processor consumes `DeviceAlarmRaised` and records a `SafetyAlert`:
- `vehicle_id`, `alarm_type`, `is_critical`, `raised_at`, position and speed, the trip in
  progress on that bus at that time and its driver (resolved through `transport_ops`'s application
  service, never a table read);
- status `open → acknowledged → resolved` or `false_alarm`; `incident_id` once turned into an
  incident (ADR-0056); who acted and when (the audit trail).

**One open alert per bus and type.** A second rising edge while an alert of that type is still
open on that bus increments its `occurrences` and `last_raised_at` instead of creating a new one,
so a flapping bit is one alert, not a storm.

### 4. Who is told

- **Critical types (`sos`, `collision`, `rollover`)**: an in-app `system` notification to every
  active Org Admin, sent by a Notification Worker processor on `SafetyAlertRaised`. It is not
  subscription-gated (a safety notification, `.claude/rules/backend.md` #6). A repeat on an open
  alert does not notify again.
- **An alarm more than 10 minutes old when received** (backfill or a delayed report) is recorded
  but not announced as live; the Safety page shows when it actually happened.
- Other types appear on the Safety page only.

### 5. Surfaces and permissions

`GET /safety-alerts` (filter by status, bus, type, date), `POST /safety-alerts/{id}/acknowledge`,
`/resolve`, `/false-alarm`. Permissions `tracking.safety_alerts.list` (org_admin, founder,
regional_manager, support_staff) and `tracking.safety_alerts.manage` (org_admin). Finance Staff,
driver and parent get none.

## Consequences

- Known Issues #7 and #8 close.
- **Not hardware-verified.** Which bits this terminal sets, and at what thresholds (overspeed and
  fatigue are configured on the device), cannot be tested while it is offline. The feature ships
  with that stated in the UI and in PROJECT_STATUS.
- `vehicle_positions.alarm_flags` keeps the raw word; nothing about position storage changes.
- Not built: platform-side overspeed detection from GPS speed, geofence/route-deviation alerts,
  driver scoring.
