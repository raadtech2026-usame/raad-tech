"""JT/T 808 wire-level framing constants (Phase 3.4 §6; restated Device Plane draft §5.1
[APPROVED]). Transport-layer concern only — this is the byte that delimits frames on the
wire, not a parsed protocol field.
"""

FRAME_DELIMITER = 0x7E
