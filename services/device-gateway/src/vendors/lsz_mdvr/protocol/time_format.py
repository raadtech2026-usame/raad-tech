"""`YYMMDD HHMMSS` wire-timestamp parsing — the vendor document's own stated format for every
`sent_at`/event-time field, verbatim described as "current UTC time" (matching this codebase's
`.claude/rules/naming.md` UTC convention for every `_at`/`event_time` field, so no timezone
conversion is applied here beyond attaching UTC — unlike JT/T 808's own GMT+8 fields, which
`src.handlers.position_body._decode_bcd_datetime` does convert)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.vendors.lsz_mdvr.protocol.exceptions import MdvrMalformedMessageError


def parse_sent_at(raw: str) -> datetime:
    try:
        naive = datetime.strptime(raw, "%y%m%d %H%M%S")
    except ValueError as exc:
        raise MdvrMalformedMessageError(f"Invalid 'YYMMDD HHMMSS' timestamp: {raw!r}") from exc
    return naive.replace(tzinfo=timezone.utc)
