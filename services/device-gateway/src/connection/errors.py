"""Shared frame-decoding error contract (device-gateway multi-vendor architecture). Every
vendor's own frame buffer/decoder raises its own `FrameTooLargeError` subclass (e.g. JT/T 808's
`vendors.jt808.protocol.framing.FrameTooLargeError`, this platform's ASCII-framed
`vendors.lsz.protocol.exceptions.MdvrFrameTooLargeError`) rather than this base class directly,
so each vendor keeps its own descriptive exception name and docstring — but `connection.
Connection`'s read loop catches only this one, shared base type, so it never needs to know (or
import) which specific vendor supplied the frame buffer it is using. Adding a new vendor under
`vendors/<name>/` only requires that vendor's own "frame too large" exception to subclass this
one; `connection.py` itself never changes.
"""

from __future__ import annotations


class FrameTooLargeError(Exception):
    """Buffered, undelimited/unterminated bytes exceed a frame decoder's configured ceiling — a
    malformed or hostile peer, regardless of which vendor's framing scheme is in use."""
