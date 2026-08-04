"""`mask_ip_address` — ADR-0019. `GET /auth/sessions` shows enough of a session's origin IP for
a user to recognize ("is this my house?"/"is this my phone's carrier?") without exposing the
full address in a response body. IPv4: the last octet is masked (`192.168.1.42` ->
`192.168.1.xxx`). IPv6: everything after the first two groups is masked (`2001:db8::1` ->
`2001:db8::xxxx`) — coarser than IPv4's "last octet only" since a IPv6 /64 prefix alone already
identifies a household/organization network, the commonly-cited granularity for "this narrow is
still meaningfully anonymizing." Anything that isn't recognizably IPv4/IPv6 (a test double, a
malformed value) is masked in full rather than risking a partial leak of an unexpected shape.
"""

from __future__ import annotations

import ipaddress

_MASK = "xxx"
_IPV6_MASK = "xxxx"


def mask_ip_address(ip_address: str | None) -> str | None:
    if not ip_address:
        return None

    try:
        parsed = ipaddress.ip_address(ip_address)
    except ValueError:
        return _MASK

    if parsed.version == 4:
        octets = ip_address.split(".")
        return ".".join(octets[:3] + [_MASK])

    groups = ip_address.split(":")
    return ":".join(groups[:2] + [_IPV6_MASK])


__all__ = ["mask_ip_address"]
