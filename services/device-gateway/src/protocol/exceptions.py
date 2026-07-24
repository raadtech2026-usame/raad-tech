"""Packet-parsing error hierarchy (Phase 9.3; Backend LLD §6: "Malformed/checksum-fail frames
are dropped + counted + logged (never crash the connection)"). Every error this layer raises
is a `ProtocolError` subclass — never a bare `Exception` — so a caller can catch precisely this
family without also swallowing genuine bugs.
"""

from __future__ import annotations


class ProtocolError(Exception):
    """Base for all Phase 9.3 packet-parsing errors."""


class UnescapeError(ProtocolError):
    """0x7d followed by anything other than 0x01/0x02 (JT/T 808-2013 §4.4.2 defines no third
    case), or a frame ending on a dangling 0x7d."""


class ChecksumError(ProtocolError):
    """The computed XOR checksum (§4.4.4) does not match the frame's trailing checksum byte."""


class MalformedFrameError(ProtocolError):
    """Header shorter than the fixed 12-byte base (or the 4-byte subpackage block when the
    subpackage bit is set, §4.4.3), or the body is shorter than the header's declared length.
    """


class ReassemblyOverflowError(ProtocolError):
    """Too many distinct incomplete subpackaged messages are pending at once — a bound against
    unbounded memory growth from a hostile/buggy peer, the same defense
    `protocol/framing.py`'s `FrameTooLargeError` applies to a single oversized frame."""
