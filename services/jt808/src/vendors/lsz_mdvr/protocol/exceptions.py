"""Error hierarchy for the LSZ MDVR protocol adapter — mirrors `src.protocol.exceptions`'
"never a bare `Exception`" discipline so callers can catch precisely this family."""

from __future__ import annotations


class MdvrProtocolError(Exception):
    """Base for every error this vendor-protocol adapter raises."""


class MdvrFrameTooLargeError(MdvrProtocolError):
    """Buffered, unterminated bytes exceed the configured ceiling without a `$$dc`/`#` frame ever
    completing — a malformed or hostile peer, mirroring `src.protocol.framing.FrameTooLargeError`.
    """


class MdvrMalformedMessageError(MdvrProtocolError):
    """A frame was correctly delimited but its content does not have the minimum common fields
    every message shares (length, sequence number, keyword, device serial number)."""
