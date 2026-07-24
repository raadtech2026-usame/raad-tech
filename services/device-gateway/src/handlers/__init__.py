"""JT808 Authentication & Registration handlers (Phase 9.5; JT808 Technical Design §4/§8).

`TerminalRegistrationHandler` (`0x0100` -> `0x8100`) and `TerminalAuthenticationHandler`
(`0x0102` -> `0x8001`) are the first *real* message handlers in this service — every handler
built in Phase 9.4 was a no-op placeholder. Both depend only on an injected
`DeviceProvisioningPort` (`provisioning_port.py`) — no SQLAlchemy, no FastAPI, no Redis, no
Fleet Device/Tracking/Organization module. No concrete port implementation exists this phase;
`server.py`'s composition root binds the fail-closed `NullDeviceProvisioningPort` by default.

The auth-code verification *mechanism* the port hides behind an opaque interface is a
documented, unresolved conflict between JT808 Technical Design §4 and the primary JT/T
808-2013 spec — confirmed with the user before implementing; see `provisioning_port.py`'s
module docstring for both sources verbatim.

`registration_body.py`/`registration_response.py` are pure JT/T 808-2013 §8.5/§8.6 wire-format
code (parse the registration request, encode the `0x8100` response) — protocol mechanics, not
business logic, the same category Phase 9.3's header parser and Phase 9.4's general-response
builder already occupy.
"""
