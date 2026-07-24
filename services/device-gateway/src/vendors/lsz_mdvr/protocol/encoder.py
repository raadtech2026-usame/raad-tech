"""Builds outbound LSZ MDVR signaling-channel frames — the encode-side mirror of `parser.py`.

**The declared-length field's exact byte-counting rule is undetermined** (`framing.py`'s own
module docstring: the vendor document never precisely defines whether it includes/excludes the
length field's own comma or the trailing `#`). Parsing never relies on this value (`framing.py`
scans for the `#` terminator instead), so an outbound frame's declared length here is a best-effort
value — the byte length of every field from the transmission-sequence-number onward, not counting
the length field itself — computed for wire-plausibility only. If a real device turns out to
validate this field strictly, this is the one place to revisit once observed against live traffic.
"""

from __future__ import annotations

from datetime import datetime


def format_sent_at(moment: datetime) -> str:
    """`YYMMDD HHMMSS`, per the vendor document's own stated "current UTC time" convention for
    this field (`docs/vendor/HARDWARE_ANALYSIS.md`'s registration/heartbeat/position field
    tables) — callers pass an already-UTC `datetime`; this function does not convert timezones."""
    return moment.strftime("%y%m%d %H%M%S")


def build_frame(
    *,
    keyword: str,
    seq: int,
    device_serial_number: str,
    workstation_serial_number: str | None,
    sent_at_raw: str,
    fields: list[str],
) -> bytes:
    workstation = workstation_serial_number or ""
    content_fields = [
        str(seq),
        keyword,
        device_serial_number,
        workstation,
        sent_at_raw,
        *fields,
    ]
    content = ",".join(content_fields)
    declared_length = len(content.encode("ascii"))
    frame = f"$$dc{declared_length:04d},{content}#"
    return frame.encode("ascii")
