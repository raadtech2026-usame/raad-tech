"""JT/T 808-2013 protocol adapter. Real, tested implementation of the national standard (frame
escaping, XOR checksum, BCD header decoding, registration/authentication/position handlers) —
kept exactly as built, unaffected by the device-gateway rename/reorganization. Dormant for the
currently-integrated hardware (`docs/vendor/HARDWARE_ANALYSIS.md` §2), retained for a possible
future genuinely JT/T 808-compliant vendor (`docs/architecture/adr/
0009-mdvr-vendor-protocol-device-plane.md`).
"""
