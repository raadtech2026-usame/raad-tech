"""`parse_device_label` — ADR-0019 (Account-Sharing Protection). Derives a short, human-readable
label (e.g. "Chrome on Windows") from a raw `User-Agent` header for `GET /auth/sessions`'s own
display, distinct from the raw string persisted alongside it (`refresh_tokens.user_agent`).

**No new dependency.** A full UA-parser library (e.g. `user-agents`) is unjustified for a short
display label — `.claude/rules/workflow.md` #1/#2 requires explaining and pre-approving any new
dependency, and this codebase already prefers a small hand-rolled primitive over a general-
purpose library where the actual need is narrow (`core/observability/metrics.py`'s own Prometheus
exposition format is the same call). This is a best-effort heuristic over the handful of
browser/OS tokens actually in common use — never raises, and an unrecognized string degrades to a
truncated raw value rather than `None`, so the caller's own session list is never silently blank.
"""

from __future__ import annotations

import re

_MAX_LABEL_LENGTH = 64

_BROWSERS: tuple[tuple[str, str], ...] = (
    # Order matters: Edge/Chrome/Opera all include "Safari" in their own UA string, and Edge/
    # Opera both include "Chrome" — most-specific token checked first.
    (r"Edg/", "Edge"),
    (r"OPR/|Opera", "Opera"),
    (r"Chrome/", "Chrome"),
    (r"Firefox/", "Firefox"),
    (r"Version/.*Safari/", "Safari"),
)

_OPERATING_SYSTEMS: tuple[tuple[str, str], ...] = (
    # Order matters: a real iOS UA string embeds the literal compatibility token
    # "like Mac OS X" (e.g. "CPU iPhone OS 17_0 like Mac OS X"), so iOS/Android must be checked
    # before the plain "Mac OS X"/Linux patterns they'd otherwise also match.
    (r"Windows", "Windows"),
    (r"iPhone|iPad|iOS", "iOS"),
    (r"Android", "Android"),
    (r"Mac OS X", "macOS"),
    (r"Linux", "Linux"),
)


def parse_device_label(user_agent: str | None) -> str | None:
    if not user_agent:
        return None

    browser = next(
        (name for pattern, name in _BROWSERS if re.search(pattern, user_agent)), None
    )
    os_name = next(
        (name for pattern, name in _OPERATING_SYSTEMS if re.search(pattern, user_agent)),
        None,
    )

    if browser and os_name:
        label = f"{browser} on {os_name}"
    elif browser:
        label = browser
    elif os_name:
        label = os_name
    else:
        # Unrecognized client (an API tool, a bot, a future browser not in the table above) —
        # degrade to a truncated raw value rather than losing the signal entirely.
        label = user_agent

    return label[:_MAX_LABEL_LENGTH]


__all__ = ["parse_device_label"]
