"""Teltonika protocol adapter — **not yet implemented.** Structural placeholder only, reserving
this vendor's place in the plugin-based `vendors/<name>/` layout (device-gateway multi-vendor
architecture). No Teltonika hardware has been procured and no vendor protocol documentation for
it exists anywhere in this repository — per this project's own "do not assume undocumented
hardware capability" discipline (mirroring `docs/vendor/HARDWARE_ANALYSIS.md`'s treatment of the
actually-procured LSZ hardware), no protocol/dispatcher/handlers code is invented here ahead of
real vendor documentation. Implementing this adapter means: obtaining Teltonika's own protocol
specification, writing `docs/vendor/HARDWARE_ANALYSIS.md`-equivalent analysis for it, then
building a `protocol/`/`dispatcher/`/`handlers/`/`server.py` stack here implementing the shared
`src.adapter.DeviceProtocolAdapter` interface — exactly the same process `vendors/jt808/` and
`vendors/lsz/` already went through, touching no other vendor's code.
"""
