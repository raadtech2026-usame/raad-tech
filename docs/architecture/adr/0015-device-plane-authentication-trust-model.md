# ADR-0015: Device-Plane Authentication Trust Model — Identity + Credential Primary, Network-Layer Optional

## Status
Accepted (direct user decision). Revises the "network-layer compensating control" framing
recorded in ADR-0009's Consequences and ADR-0010's Decision §7/Consequences, and resolves
`docs/vendor/HARDWARE_INTEGRATION_PLAN.md`'s Conflict #3 (§11) and Required Refactoring item 5
(§12) — both of which explicitly left this as "its own ADR," unresolved, since Decision Point 1.

## Context
`.claude/rules/security.md` #9 lists device-plane compensating controls (device auth keys, IP/APN
allow-listing, DMZ isolation, heartbeat/traffic anomaly detection) as a flat, unranked list.
ADR-0009's Consequences section and `services/device-gateway/src/vendors/lsz/handlers/
provisioning_port.py`'s own module docstring go further and state that the LSZ vendor's missing
cryptographic assurance "must be closed at the network layer (mutual TLS / IP allow-listing / DMZ
isolation)" — implicitly treating network-layer controls as *the* compensating mechanism for the
identity gap, not one option among several.

That framing assumes a network topology — a static device IP, a private APN, or a DMZ boundary
RAAD controls end-to-end — that lets an IP-based or TLS-terminated check reliably identify a
specific device before it ever reaches the application layer. RAAD's actual device fleet is
ordinary public cellular: a SIM in an MDVR unit dialing out over the carrier's own public data
network. The norm for that topology is a dynamic, carrier-NAT'd IP that changes per session, per
tower handoff, and per carrier network policy — not a stable identifier. A static-IP or
private-APN arrangement is possible (a carrier can sell one) but is a deployment-specific choice,
not RAAD's default topology, and no approved document commits RAAD to requiring one. Building the
platform's *primary* device trust model around "the connecting IP proves the device" would work
only for a minority of hypothetical static-IP/private-APN deployments and silently degrade to no
real check at all for the ordinary-cellular majority (any IP could belong to any device on the
same carrier at any moment) — exactly the risk flagged directly by the user.

Meanwhile JT/T 808 (`src/vendors/jt808/`, dormant but kept per ADR-0009) already has the *right*
shape and needs no change here: `terminal_id` (device identity) plus `auth_key_hash`, verified via
the `0x0102` auth-code exchange (`vendors/jt808/handlers/authentication_handler.py`/
`provisioning_port.py`), is a real, cryptographically-verified identity+credential model,
independent of the connecting IP entirely. This ADR generalizes that shape into an explicit,
cross-vendor policy rather than leaving it as an unstated property of one dormant vendor
implementation.

LSZ — the vendor actually procured and running today — is the hard case this ADR must confront
honestly: its wire protocol has **zero credential surface of any kind** (Hardware Analysis §11 —
no shared secret, no challenge/response, no signed token, no per-device key, no TLS/DTLS mentioned
anywhere in any of the four vendor documents). This is a firmware/protocol fact about hardware
RAAD does not control, not a RAAD implementation gap — no wire-level "secure credential" can be
invented for a device whose firmware never sends one, per this codebase's own "trace only to the
vendor's own documentation, never invent undocumented capability" discipline.

## Decision

1. **Device identity + secure credential is RAAD's primary device-plane trust model,
   platform-wide, for every current and future vendor adapter.** Wherever a vendor's protocol
   carries a real credential (JT/T 808's auth code today; any future vendor — Teltonika/Queclink/
   Ruptela, structural placeholders per ADR-0010, when actually procured — that supports a
   pre-shared key, token, or mutual-TLS client identity), that credential is verified
   cryptographically against `fleet_device`'s own provisioning data before a session is
   authorized, exactly as `vendors/jt808/handlers/authentication_handler.py` already does. This
   never depends on the connecting IP, source port, or network topology.

2. **IP allowlisting, private-APN restriction, and DMZ isolation are demoted to optional,
   deployment-specific defense-in-depth — never a required or assumed baseline control, and
   never a substitute for a missing credential.** A specific customer/region deployment that
   genuinely has a private APN or static device IPs (a carrier-level arrangement outside RAAD's
   own control) MAY layer one of these on top of identity+credential verification. RAAD's own
   architecture and default configuration assume dynamic, public-cellular IPs and build no
   dependency on any of these being present anywhere.

3. **For LSZ specifically, since its wire protocol has no credential surface at all** (Hardware
   Analysis §11, a confirmed hardware/firmware limitation, not invented around): the best
   available, honest primary control is strict **identity** resolution — the registering serial
   number must resolve to a device that is both active and vehicle-assigned in `fleet_device`'s
   own live device-registry projection (`ProjectionBackedMdvrProvisioningPort`, already the real,
   non-interim implementation per ADR-0010 item 7). This is accepted and explicitly flagged as
   **identity-only** — deliberately *not* "secure device credential" in the cryptographic sense
   Decision §1 describes; no fake credential is invented to paper over what this hardware cannot
   do. It remains a real, open gap (anyone who learns a valid, active, vehicle-assigned serial
   number can impersonate that device over the network) until either this vendor's firmware gains
   a real credential mechanism, or a future vendor that supports one replaces it in that
   deployment.

4. **A concrete, bounded strengthening is identified but not implemented this phase.** The `V101`
   registration frame's own field list (Hardware Analysis §10) includes an *optional* IMEI field
   alongside the mandatory serial number. Cross-checking a *present* IMEI against `fleet_device`'s
   own stored `imei` (already a real, globally-unique column, Device Domain Overhaul) would raise
   the identity bar without inventing any wire-protocol capability this hardware doesn't have —
   but `docs/vendor/HARDWARE_ANALYSIS.md` gives that field only a prose-ordered position, not a
   precise indexed field table, and `services/device-gateway/src/vendors/lsz/protocol/message.py`'s
   parser today does not parse or expose any `V101` field beyond `device_serial_number`.
   Implementing this without first confirming the exact field position against the primary
   vendor source (`mdvrdocs/mdvr网络通信协议V0.00.30_150103 - 英文.doc`) risks silently misreading
   a field this codebase has not yet verified — the same "trace only to the vendor's own
   documentation, never invented" discipline `HARDWARE_ANALYSIS.md` itself follows throughout.
   Tracked as a scoped follow-up (see Consequences), not built here.

## Consequences
- `.claude/rules/security.md` #9 and `.claude/rules/jt808.md` are updated to state this
  primary/optional ordering explicitly (see those files' own diffs, same commit).
- `docs/vendor/HARDWARE_INTEGRATION_PLAN.md`'s Conflict #3 (§11) and Required Refactoring item 5
  (§12) are marked resolved, pointing here, rather than left open indefinitely.
- `services/device-gateway/src/vendors/lsz/handlers/provisioning_port.py`'s module docstring —
  which previously said the missing cryptographic assurance "must be closed at the network
  layer" — is corrected; that framing is superseded, and the module docstring now points at this
  ADR's actual identity-only-and-flagged posture instead.
- ADR-0009's Consequences / ADR-0010's Decision §7 are **not edited in place** (this codebase
  keeps ADRs as historical records of the decision made at the time) but are superseded on this
  one point by this ADR — a reader following either back to "network-layer compensating
  controls" for the LSZ gap should land here for the current, corrected framing.
- **No code changes to any wire-protocol parser or the device-registry projection are made by
  this ADR.** `ProjectionBackedMdvrProvisioningPort`'s existing serial-number-only check already
  matches Decision §3 exactly — it was already identity-based; what changes is only how it's
  *framed* (the primary, accepted control, not a stand-in awaiting a network-layer fix that was
  never actually going to close this gap for a dynamic-IP fleet). The IMEI cross-check named in
  Decision §4 remains a real, scoped, not-yet-built follow-up, blocked on confirming the exact
  `V101` field position against the primary vendor document — out of this ADR's own scope, which
  is the trust-model decision, not a parser change.
- **No IP-allowlisting code exists anywhere in this codebase today** (confirmed by grepping
  `services/device-gateway/src` before writing this ADR — `none is designed yet`, per ADR-0009/
  0010's own prior text). There is nothing to remove or demote in code; this ADR corrects the
  documented *policy* before any such code is ever built, so it is never built as a required
  baseline control in the first place.
- Every future vendor adapter (Teltonika/Queclink/Ruptela, when actually procured) inherits
  Decision §1 directly: if that vendor's protocol supports a real credential, it must be verified
  the same way JT/T 808 already is; if it doesn't, it inherits Decision §3's identity-only,
  explicitly-flagged posture — never a fabricated credential invented to look more secure than
  the hardware actually is.

## References
- `docs/vendor/HARDWARE_ANALYSIS.md` §10 (device registration fields), §11 (authentication)
- `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §11 Conflict #3, §12 Required Refactoring item 5
- `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md` (Consequences)
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md` Decision §7
- `.claude/rules/security.md` #9
- `.claude/rules/jt808.md` #1, #4, #5
- `services/device-gateway/src/vendors/jt808/handlers/authentication_handler.py`,
  `provisioning_port.py` (the already-correct target shape for a vendor with a real credential)
- `services/device-gateway/src/vendors/lsz/handlers/provisioning_port.py`,
  `src/registry/device_registry_projection.py` (today's identity-only LSZ implementation)
