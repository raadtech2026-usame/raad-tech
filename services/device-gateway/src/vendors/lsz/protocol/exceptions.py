"""Error hierarchy for the LSZ MDVR protocol adapter — mirrors the sibling `vendors/jt808/`
adapter's "never a bare `Exception`" discipline so callers can catch precisely this family."""

from __future__ import annotations

from src.connection.errors import FrameTooLargeError as _SharedFrameTooLargeError


class MdvrProtocolError(Exception):
    """Base for every error this vendor-protocol adapter raises."""


class MdvrFrameTooLargeError(MdvrProtocolError, _SharedFrameTooLargeError):
    """Buffered, unterminated bytes exceed the configured ceiling without a `$$dc`/`#` frame ever
    completing — a malformed or hostile peer, mirroring `vendors.jt808.protocol.framing.
    FrameTooLargeError`. Also subclasses the shared `connection.errors.FrameTooLargeError`
    (device-gateway multi-vendor architecture) so `connection.Connection`'s read loop can catch
    it without importing this vendor's own protocol package."""


class MdvrMalformedMessageError(MdvrProtocolError):
    """A frame was correctly delimited but its content does not have the minimum common fields
    every message shares (length, sequence number, keyword, device serial number)."""
