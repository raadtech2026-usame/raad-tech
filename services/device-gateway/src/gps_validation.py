"""Coordinate-plausibility ACL guard, shared by every vendor adapter.

`.claude/rules/jt808.md` #2 isolates *vendor dialect* variation in a per-vendor Anti-Corruption
Layer (`vendors/<name>/`) — but "is this coordinate even physically sane" is not a vendor
concept, so it is not duplicated per vendor the way BCD/D°M′S″ decoding is. This mirrors
`vendors/lsz/handlers/position_handler.py`'s own `_clamp_heading`/`_clamp_alarm_flags`
precedent: a defensive sanity check belongs at the device-plane ACL boundary, before a value
ever crosses into a `DevicePositionReported` event, never after.

Used together with each vendor's own wire-level fix-validity flag (JT/T 808's `status` DWORD
bit 1, "positioned"; the LSZ protocol's 'A'/'V' positioning-status flag) to compute
`DevicePositionReported.is_gps_valid` — see that event's own module docstring for the full
root-cause record this closes (RAAD Live Tracking wrong-location investigation).
"""

from __future__ import annotations

import math

_LATITUDE_MIN, _LATITUDE_MAX = -90.0, 90.0
_LONGITUDE_MIN, _LONGITUDE_MAX = -180.0, 180.0

# "Null island" (0, 0) is open ocean in the Gulf of Guinea, never a real RAAD bus location.
# Treated as implausible within a small epsilon so a genuinely zeroed/garbage GPS fix that lands
# a few float-rounding ULPs away from exact (0.0, 0.0) is still caught, not just the literal pair.
_NULL_ISLAND_EPSILON_DEG = 0.0001


def is_plausible_coordinate(latitude: float, longitude: float) -> bool:
    """`False` for NaN/Infinity, out-of-range, or null-island — the same "reject, don't invent
    a fallback" posture this codebase already applies to every other malformed-input case."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return False
    if not (_LATITUDE_MIN <= latitude <= _LATITUDE_MAX):
        return False
    if not (_LONGITUDE_MIN <= longitude <= _LONGITUDE_MAX):
        return False
    if abs(latitude) < _NULL_ISLAND_EPSILON_DEG and abs(longitude) < _NULL_ISLAND_EPSILON_DEG:
        return False
    return True
