"""Parses the "location and status" field group — a fixed run of 18 comma-separated tokens
embedded inside every `V101` (registration) and `V114` (position report) message body, per
`mdvrdocs/mdvr网络通信协议V0.00.30_150103 - 英文.doc`'s own field table (§ "location and status").
This is the GPS-normalization Anti-Corruption Layer step `docs/vendor/HARDWARE_INTEGRATION_PLAN.md`
§1/§7 names as required work: this vendor's coordinate encoding does not match either JT/T 808's
convention or, in one case, its own prose description consistently — see below.

**Token layout (18 tokens, order per the vendor document's own field table, cross-checked against
two independent worked examples in the primary and supplementary vendor documents):**

```
[0]  positioning status  ('A'/'V' fix flag + satellite count, e.g. "A0010")
[1]  longitude degrees    (signed int; sign = hemisphere, negative = West)
[2]  longitude minutes    (unsigned int, 0-59)
[3]  longitude seconds    (unsigned int, scaled - see "Coordinate scaling" below)
[4]  latitude degrees     (signed int; sign = hemisphere, negative = South)
[5]  latitude minutes     (unsigned int, 0-59)
[6]  latitude seconds     (unsigned int, scaled)
[7]  ground speed         (decimal string, km/h) - best-effort, see "Confidence" below
[8]  ground course        (string) - best-effort, see "Confidence" below
[9]  component status + alarm flags (16 hex chars) - opaque, not decoded
[10] component status + alarm mask  (16 hex chars) - opaque, not decoded
[11] device temperature   (decimal string, deg C) - best-effort
[12] engine temperature   (decimal string, deg C) - best-effort
[13] cabin temperature    (decimal string, deg C) - best-effort
[14] mileage              (string, meters per the doc's own "单位米" note) - best-effort
[15] fuel level           (decimal string, liters) - best-effort
[16] parking duration     (string, seconds) - best-effort
[17] "RPM|SPEED"          (pipe-delimited string) - opaque, not decoded
```

**Confidence — stated explicitly, not implied.** Latitude/longitude and the fix-valid flag are
**high confidence**: derived from the vendor document's own field order *and independently
cross-validated* against two separate worked examples (one in the primary protocol document, one
in the supplementary packet-capture document) that both decode to real-world coordinates
consistent with the vendor's own stated factory location (Shenzhen, Guangdong — see "Coordinate
scaling" below for the arithmetic). Ground speed/course, mileage, fuel, and the temperature fields
are **best-effort only**: their field *positions* follow the vendor table's documented order, but
none could be independently cross-validated the way lat/lon were (the worked examples show a
stationary test device with implausible-looking values at several of these positions that this
module cannot fully reconcile with the prose description — e.g. "ground course" showing values
far outside the documented 0-360 range in both captured examples). Rather than silently presenting
a guess as fact, this parser still extracts these fields (so nothing is thrown away) but callers
must treat them as unverified passthrough data pending confirmation against real device traffic —
which is exactly why `RecordVehiclePositionCommand`/`DevicePositionReported`'s own `speed_kph`/
`heading_deg`/`alarm_flags` fields are optional: this parser only populates them when a value is
present and parses cleanly, never fabricating a fallback.

**Coordinate scaling — the specific, evidence-based choice made here.** The vendor document's own
prose illustration ("如'-80,89,920'表示西经80º89'0920\"") is internally implausible taken literally
(89 minutes exceeds the valid 0-59 range) and does not match the scaling this module actually
uses — flagged, not silently followed. Instead, the two real worked examples (device `00007`,
Shenzhen) were decoded arithmetically: raw seconds value `341826000` / `10_000_000` = `34.1826`
arc-seconds, combined with degrees=114/minutes=3 giving `114°03'34.1826"E` = `114.059495°E` —
matching Shenzhen's real-world longitude (~114.06°E) to within normal in-city variation; latitude
similarly resolves to `22.673229°N`, matching Shenzhen's real-world latitude (~22.54-22.7°N
depending on district — the vendor's own factory address is Longhua District, a northern Shenzhen
suburb, consistent with the higher end of that range). Both worked examples resolve consistently
under this same `/10_000_000` scaling, independently of each other. This module therefore treats
the seconds sub-field as arc-seconds scaled by `10_000_000` (i.e. 7 implied decimal places), not
whatever scaling the document's own short illustrative string implies.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.vendors.lsz_mdvr.protocol.exceptions import MdvrMalformedMessageError

_LOCATION_STATUS_TOKEN_COUNT = 18
_SECONDS_SCALE = 10_000_000


@dataclass(frozen=True)
class LocationStatus:
    fix_valid: bool
    satellite_count: int | None
    latitude: float
    longitude: float
    ground_speed_kph: float | None
    heading_deg: int | None
    mileage_m: int | None
    fuel_liters: float | None
    component_status_alarm: int | None  # group[9], 16 hex chars - opaque bitfield, not decoded
    # beyond parsing the hex string to an int; individual bit meanings are documented (Hardware
    # Analysis §5) but decoding them into named alarm booleans is out of scope for this ACL step.
    raw_tokens: tuple[str, ...]


def _to_decimal_degrees(*, degrees_token: str, minutes_token: str, seconds_token: str) -> float:
    degrees = int(degrees_token)
    minutes = int(minutes_token)
    seconds = int(seconds_token) / _SECONDS_SCALE
    magnitude = abs(degrees) + minutes / 60 + seconds / 3600
    return -magnitude if degrees < 0 else magnitude


def _parse_positioning_status(token: str) -> tuple[bool, int | None]:
    if not token:
        raise MdvrMalformedMessageError("Empty positioning-status token.")
    fix_valid = token[0] == "A"
    satellite_part = token[1:]
    satellite_count = int(satellite_part) if satellite_part.isdigit() else None
    return fix_valid, satellite_count


def _best_effort_float(token: str) -> float | None:
    try:
        return float(token) if token else None
    except ValueError:
        return None


def _best_effort_int(token: str) -> int | None:
    try:
        return int(float(token)) if token else None
    except ValueError:
        return None


def _best_effort_hex(token: str) -> int | None:
    try:
        return int(token, 16) if token else None
    except ValueError:
        return None


def parse_location_status(tokens: list[str]) -> tuple[LocationStatus, list[str]]:
    """Consumes the first 18 tokens of `tokens` as the "location and status" group, returning
    the parsed result and whatever tokens remain (the caller's own message-specific trailing
    fields, e.g. `V114`'s "drive flag")."""
    if len(tokens) < _LOCATION_STATUS_TOKEN_COUNT:
        raise MdvrMalformedMessageError(
            f"Expected at least {_LOCATION_STATUS_TOKEN_COUNT} location-and-status tokens, "
            f"got {len(tokens)}."
        )
    group = tokens[:_LOCATION_STATUS_TOKEN_COUNT]
    remainder = tokens[_LOCATION_STATUS_TOKEN_COUNT:]

    fix_valid, satellite_count = _parse_positioning_status(group[0])
    latitude = _to_decimal_degrees(
        degrees_token=group[4], minutes_token=group[5], seconds_token=group[6]
    )
    longitude = _to_decimal_degrees(
        degrees_token=group[1], minutes_token=group[2], seconds_token=group[3]
    )

    status = LocationStatus(
        fix_valid=fix_valid,
        satellite_count=satellite_count,
        latitude=latitude,
        longitude=longitude,
        ground_speed_kph=_best_effort_float(group[7]),
        heading_deg=_best_effort_int(group[8]),
        mileage_m=_best_effort_int(group[14]),
        fuel_liters=_best_effort_float(group[15]),
        component_status_alarm=_best_effort_hex(group[9]),
        raw_tokens=tuple(group),
    )
    return status, remainder
