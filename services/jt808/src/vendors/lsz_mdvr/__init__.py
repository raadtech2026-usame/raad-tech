"""Shenzhen Tianyou Security Technology Co., Ltd ("LSZ") MDVR protocol adapter (ADR-0009).

The procured hardware (model `LSZ-C5804DG-Q-F`) speaks a proprietary ASCII/binary protocol,
confirmed against the vendor's own documentation (`mdvrdocs/`, analyzed in `docs/vendor/
HARDWARE_ANALYSIS.md`) to be unrelated to JT/T 808 or JT/T 1078 at the wire level: ASCII
`$$dc<content>#`-framed commands identified by keyword (`V101`, `C100`, ...) rather than a binary
message ID, no checksum/escaping, and GUID-based sessions. This package implements the signaling-
channel subset of that protocol needed for device registration and GPS position reporting
(roadmap tracks B1/B2) — the binary media-channel protocol (live video, file transfer, firmware
upgrade) is out of scope here, tracked separately under B3.
"""
