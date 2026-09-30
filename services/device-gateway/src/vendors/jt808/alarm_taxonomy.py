"""JT/T 808 alarm word → RAAD's canonical alarm types (ADR-0055 §1).

The `0x0200` basic information carries a 32-bit alarm word (supplier spec
`MDVR-808-1078-spec.pdf` Table 5.10, JT/T 808-2019 Table 24). This is the vendor Anti-Corruption
Layer the Phase-2 architecture (§6) assigns to "alarm-bit conventions": the backend only ever sees
the names below, never a bit position, so a future vendor maps its own convention onto the same
names in its own adapter.

Only the bits RAAD acts on are mapped. The others (module faults, area/route alarms, …) are not
interpreted in this phase; `vehicle_positions.alarm_flags` still keeps the raw word.

**Not hardware-verified.** Which of these bits the procured terminal actually sets, and at what
thresholds (overspeed and fatigue are configured on the device), is unconfirmed while it is
offline.
"""

from __future__ import annotations

#: bit position → canonical alarm type.
ALARM_BITS: dict[int, str] = {
    0: "sos",  # emergency alarm, triggered by the alarm switch; cleared by 0x8203 (ADR-0057)
    1: "overspeed",
    2: "fatigue",
    8: "power_cut",  # main power off
    11: "camera_fault",
    29: "collision",
    30: "rollover",
    31: "illegal_door_open",
}

#: Types that alert Org Admins immediately (ADR-0055 §4). Kept here for reference; the backend
#: owns the decision and derives it from the type name.
CRITICAL_TYPES = frozenset({"sos", "collision", "rollover"})


def raised_alarm_types(previous_flags: int | None, current_flags: int) -> list[str]:
    """Types whose bit is set now and was not set in the previous report (a rising edge).
    `previous_flags=None` (no earlier report known) treats every set bit as new."""
    previous = previous_flags or 0
    new_bits = current_flags & ~previous
    return [name for bit, name in sorted(ALARM_BITS.items()) if new_bits & (1 << bit)]
