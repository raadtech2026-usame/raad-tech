# ADR-0025: JT/T 808-2019 + JT/T 1078-2016 Native Protocol Compliance — Supersedes ADR-0009's Non-Compliance Finding

## Status

**Accepted (direct user decision, 2026-08-10 — "verification is complete... update the architecture
based on native JT/T 808-2019 + JT/T 1078-2016, not the old LSZ proprietary protocol").**
Architecture-only: this ADR records the decision and its concrete consequences for every
downstream document; it does not itself change any `.py` file. Implementation is a following,
separately-authorized phase — see "What this ADR does not do," below, and `.claude/rules/
workflow.md` #8.

**Supersedes ADR-0009's core finding** ("the procured MDVR hardware does not implement JT/T 808 or
JT/T 1078 at all... a proprietary ASCII/binary protocol") for the exact procured model,
`LSZ-C5804DG-Q-F`. **Does not reverse ADR-0009's other decisions** — the deployable-separation
architecture, the event-only device-plane/business-plane boundary, the Anti-Corruption Layer
principle, and the decision to keep the dormant `vendors/jt808/` code rather than delete it — all
of those remain correct and, in fact, are exactly what makes this reversal cheap to absorb (see
Consequences). ADR-0009 itself is **not edited in place** — this codebase keeps ADRs as historical
records of the decision made at the time, per the same convention `docs/architecture/adr/
0015-device-plane-authentication-trust-model.md`'s own Consequences already established for
partially superseding ADR-0009 once before ("ADR-0009's Consequences... are not edited in place...
but are superseded on this one point by this ADR").

**Supersedes ADR-0024's Decision §1** ("LSZ proprietary video protocol adaptation") and the parts
of §6/§7/§8/§16 built on it — ADR-0024 itself is revised in place (same commit) rather than
replaced by a new ADR, since it was never accepted or implemented ("Proposed — pending user
review," no code/migration/Dockerfile ever existed for it) — there is no prior "accepted decision"
whose historical record needs preserving untouched the way ADR-0009's does. See that file's own
diff for the specifics; this ADR does not restate them.

## Context

On 2026-08-09, a source-code-only audit (no code changes, no ADR) confirmed the state ADR-0009
originally established still held in the repository: JT/T 808's registration/authentication/
location handler stack (`services/device-gateway/src/vendors/jt808/`) was real, tested, and
running, but wired to a permanently fail-closed `NullDeviceProvisioningPort`; `services/jt1078/`
was an empty scaffold; the LSZ-proprietary media-channel opcodes ADR-0009/ADR-0024 were built
around (`C508`/`C701`/`C702`/`V102`/`V103`/`0x6000`/`0x6002`/`0x6011`-`0x6013`/`0x6102`) existed
only in documentation, never in code. A follow-up implementation turn the same day closed the
resolvable half of the JT808 identity/provisioning gap (`ProjectionBackedJt808ProvisioningPort`,
a new `HeartbeatHandler`, `touch()` wiring in `LocationHandler`) and deliberately left `0x0102`
authentication-code verification unimplemented, because the repository's own documented conflict
between JT808 Technical Design, the primary JT/T 808 spec's own text, and Backend LLD over what
that code even *is* could not be resolved without guessing.

On 2026-08-10, two new supplier documents were added to `mdvrdocs/`: a compliance letter (Ref.
`LSZ-CC-20260810-001`, Shenzhen Tianyou Security Technology Co., Ltd / brand LSZ letterhead)
explicitly confirming `LSZ-C5804DG-Q-F` supports JT/T 808-2019 and JT/T 1078-2016, with a
message-support matrix covering `0x0100`/`0x0102`/`0x0200`/`0x9101`/`0x9102`/`0x9205`/`0x9201`;
and a 70-page specification (`MDVR-808-1078-spec.pdf`, `MDVR-808-1078-SPEC V1.2`) giving
message-by-message field definitions for the full JT/T 808 core message set plus the JT/T 1078
audio/video extension chapter. A source-code-and-document review that followed (architecture-only,
no code, no ADR, per explicit instruction) found the specification's content detailed, internally
consistent, and consistent with the well-documented, public JT/T 808-2013→2019 field-width
revision delta — and also found and flagged a real, unresolved discrepancy at the time (the
specification document's own header/footer identify its publisher as "深圳元启明科技有限公司," a
company name absent from every piece of RAAD's prior vendor paper trail, distinct from "Shenzhen
Tianyou/Tiantianyou Security Technology Co., Ltd." on the compliance letter; the specification
itself never mentions the model number `LSZ-C5804DG-Q-F` anywhere in its 70 pages; the letter
itself was unsigned and dated the same day as the review).

**The user has since stated verification is complete and directed this architecture update.**
This ADR proceeds on that basis. The specific mechanism by which verification was completed (a
resolved supplier relationship clarification, a physical-device handshake test, or both) is not
independently re-confirmed by this document — this ADR records the resulting architectural
decision, not a repeat of the evidentiary review the prior conversation turn already performed in
full (`docs/architecture/adr/0024-jt1078-video-relay-architecture.md`'s own predecessor review
document, and the unrecorded review turn immediately before this ADR, are the fuller record of
that evidence).

## Decision

### 1. The procured hardware is treated as genuinely JT/T 808-2019 and JT/T 1078-2016 compliant

`LSZ-C5804DG-Q-F` is no longer treated as a proprietary-protocol device requiring a translation
adapter. It is treated as a standard, if narrower-than-full-spec, implementation of JT/T 808-2019
(core messages) and JT/T 1078-2016 (audio/video extension), per the confirmed message-support
matrix. This reverses ADR-0009 §Context/§Decision's finding for this specific model only — it
does not change the *general* posture toward *future*, still-unconfirmed vendors (Teltonika/
Queclink/Ruptela remain structural placeholders, per ADR-0010, until their own hardware is
procured and their own protocol is independently confirmed the same way this one now has been).

### 2. Confirmed wire-format facts (JT/T 808-2019, vs. the currently-implemented JT/T 808-2013 shape)

Traced directly to the specification's own field tables (§4.2, §5.1.5, §5.1.7), not assumed:

| Element | Current (`vendors/jt808/`, 2013-shape) | Confirmed (2019) |
|---|---|---|
| Message header, terminal phone | `BCD[6]` (12 digits) | `BCD[10]` (20 digits) |
| Message header, protocol-version byte | absent | present, offset 4, `0x01` for 2019 |
| Message-body-attribute bit 14 | not implemented | fixed `1` for 2019 |
| `0x0100` manufacturer ID | `BYTE[5]` | `BYTE[11]` |
| `0x0100` terminal model | `BYTE[20]` | `BYTE[30]` |
| `0x0100` terminal ID | `BYTE[7]` | `BYTE[30]` |
| `0x0102` body | auth-code string only | auth-code string **+ terminal IMEI `BYTE[15]` + software version `BYTE[20]`** |
| `0x0002` (heartbeat) → `0x8001` ack | already implemented this way | confirmed correct, unchanged |
| Framing (`0x7E`), escaping (`0x7D`), XOR checksum | already implemented this way | confirmed correct, unchanged |

Every width change above matches the well-documented, public JT/T 808-2013→2019 revision delta —
this is not a vendor-specific invention. The base `0x0200` location-report block and RAAD's
`AlarmFlags` bit mapping were **not** byte-for-byte re-diffed as part of this ADR — flagged as a
verification step for the implementation phase, not assumed identical just because it's
historically been stable across revisions.

### 3. `0x0102` authentication: wire format resolved, storage/lifecycle design decided here

The specification (§5.1.6/§5.1.7, §7.1.1/§7.1.2) confirms the **platform-issued, echoed-back**
model: registration succeeds → platform issues an auth code in `0x8100` → terminal saves it →
terminal echoes it in every subsequent `0x0102`, alongside IMEI and firmware version. This
corroborates the "primary JT/T 808 spec text" reading `provisioning_port.py`'s own docstring had
already identified as one of three previously-irreconcilable interpretations — it does not
introduce a new theory.

The **storage/lifecycle design**, which no wire-format document can dictate, is decided by this
ADR: the platform mints a cryptographically random code on `0x0100` success, hashed at rest in
`Device.auth_key_hash` (an existing column, previously always `None` — its own docstring already
named this exact purpose: *"`auth_key_hash` is stored, never verified here — device
authentication happens in the JT808 service against the device-registry projection"*), the same
hashing precedent `iam`'s own password storage already establishes (PBKDF2-HMAC-SHA256). `0x0102`
verification compares the presented code's hash against the stored one. **The code does not
time-expire** — a real device registers once and reconnects using the same code indefinitely,
matching how the specification's own §7.1.1/§7.1.2 describe the flow (no re-registration implied
by an ordinary reconnect). **The code rotates only on a fresh, successful `0x0100` registration**
(e.g., after a factory reset) — a new code is minted and the old one is invalidated, mirroring the
specification's own §3.5.3 single-session-per-identity replacement policy, generalized from
connection-replacement to credential-replacement. This is a reasoned design recommendation, not
independently re-confirmed with the user beyond this ADR's own review — flagged as such, matching
this codebase's own "flagged interpretive choice" convention (e.g. ADR-0019's identical treatment
of its own "not seen in the last N sessions" gap).

### 4. `services/device-gateway/src/vendors/jt808/` becomes the live, primary GPS adapter

The existing, previously-dormant JT/T 808 implementation (kept exactly per ADR-0009's own "kept,
untouched, dormant, for a possible future genuinely-compliant vendor" reasoning) is now that
future vendor's adapter. It requires the field-width rework in §2/§3 above — a new implementation
phase, not authorized by this ADR alone (see "What this ADR does not do"). **`services/
device-gateway/src/vendors/lsz/`** (the proprietary-protocol adapter, GPS/registration/heartbeat
only, `V101`/`V109`/`V114`-keyword framing) **is not deleted.** It becomes the dormant one,
mirroring exactly the posture `vendors/jt808/` held before this ADR — real, tested code, kept for
a scenario where a future device genuinely only speaks that proprietary dialect (e.g., a different
firmware batch, a different vendor reselling under a similar SKU). Deleting working, tested code
because it's no longer the *active* adapter would repeat the exact mistake ADR-0009 itself refused
to make in the opposite direction.

**`gateway.py`'s composition root does not need to change its shape** — it already instantiates
both `Jt808Server` and `MdvrServer` unconditionally, side by side, each on its own port (7808/
7809), sharing one `EventPublisher` and one `DeviceRegistryProjection`. What changes is which one
a real device actually connects to and completes a handshake against — an operational fact, not a
code-structure one. The `DeviceProtocolAdapter` multi-vendor architecture (ADR-0010) is exactly
the mechanism that makes this reversal cheap: no new adapter class, no new composition-root
pattern, only field-width corrections inside the adapter that was already there.

### 5. Native JT/T 1078 video signaling supersedes the LSZ-proprietary media-channel design

Confirmed by the specification's own §6 opening line: JT/T 1078 signaling "沿用 JT/T 808 的报文
封装、鉴权、流水号、应答和分包机制" (reuses JT/T 808's message envelope, auth, serial-number,
response, and segmentation mechanism) — video signaling (`0x9101`/`0x9102`/`0x9105`/`0x9201`/
`0x9202`/`0x9205`/`0x9206`/`0x9207`) is **more JT808 message types on the same already-
authenticated connection `device-gateway` already holds**, not a second connection requiring a
translated, vendor-specific handshake. `docs/architecture/adr/0024-jt1078-video-relay-
architecture.md` §1's LSZ-proprietary adapter design (`C508` → new media connection → `V102`/
`0x6000`/`0x6002` handshake → demux `0x6011`/`0x6012`/`0x6013`) is superseded by this finding —
see that ADR's own revised §1/§6/§7/§8 (same commit) for the concrete replacement design. The
media *transport* itself (the RTP-extended payload over TCP/UDP, specification §6.2.1.1) still
requires the exact same repackaging-for-browsers work ADR-0024 §4/§14 already designed and this
ADR does not change — a real device streaming standards-based RTP-extended frames is still not
something a browser's `<video>` element can consume directly, so `services/jt1078/`'s whole reason
to exist (ingest → repackage → WS-FLV/HLS/WebRTC) is unchanged in kind, only simplified in *what
it ingests from*.

### 6. `.claude/rules/jt808.md`/`.claude/rules/jt1078.md`'s "Reality check" preambles are retired

Both files' opening paragraphs existed specifically to flag "this rule file describes the *target*
architecture for a genuinely compliant vendor, not the currently-integrated hardware" — that
caveat is no longer accurate for the currently-procured hardware. Both files are updated (same
commit) to remove the disclaimer and read as direct, current architecture again, with pointers to
this ADR and ADR-0009 for the historical record of why the caveat existed at all. Rule content
itself (`jt808.md` #1-#7, `jt1078.md` #1-#6) needed **no substantive change** — every one of those
rules was already written against the compliant-vendor target this ADR now confirms is real, not
against LSZ-proprietary specifics.

## What this ADR does not do

- **No `.py` file is changed by this ADR.** The field-width rework (§2/§3), the JT1078 media relay
  build-out, and the `device-gateway` video-signaling forwarding responsibility (ADR-0024's
  revised §1/§8) are all real implementation work for a following, separately-authorized phase —
  per `.claude/rules/workflow.md` #8's "verify the corresponding architecture has already been
  approved" discipline, this document *is* that approval, not the implementation itself.
- **No migration is written.** `Device.auth_key_hash` already exists as a column (Device Domain
  Overhaul); §3's design reuses it, it does not add to the schema.
- **Does not resolve the `0x0200`/`AlarmFlags` byte-level diff** flagged as outstanding in §2 —
  that is implementation-phase verification work, not an architecture decision.
- **Does not pick a runtime/language for `services/jt1078/`** — ADR-0024's own README-cited "not
  yet decided by approved documentation" caveat is unchanged by this ADR; that remains open.
- **Does not evaluate or approve any new dependency** (e.g., an RTP/media-server library) —
  `.claude/rules/workflow.md` #1/#2 still applies in full to whatever the eventual JT1078
  implementation phase proposes.

## Consequences

- **ADR-0009 remains historically accurate and is not edited** — it correctly records what was
  known and decided in July 2026, from the documents available at the time. This ADR is the
  pointer a future reader following ADR-0009 forward should land on for the current, corrected
  finding — the same convention ADR-0015 already established once for a narrower point.
- **ADR-0024 is revised in place** (§1, Context point 3, §6, §7, §8, §14 reasoning, §16 point 1,
  Consequences, References) — see that file's own diff, same commit as this ADR.
- **`.claude/rules/jt808.md`/`.claude/rules/jt1078.md`** — "Reality check" preambles removed, same
  commit.
- **`CLAUDE.md`'s "Core Technical Domains" section and `docs/PROJECT_STATUS.md`'s JT808/JT1078/
  Video rows and Known Issue #18** are updated to reflect this decision, same commit — see those
  files' own diffs.
- **The LSZ-proprietary GPS adapter (`vendors/lsz/`) is not deprecated in the sense of being
  removed or stopped from running** — `gateway.py` continues to instantiate and start it
  unconditionally, exactly as today. It becomes the *secondary*, not the *primary*, GPS path for
  this vendor relationship, available if a specific unit or firmware batch ever turns out to need
  it after all (§4).
- **`docs/vendor/HARDWARE_ANALYSIS.md`'s §2 conclusion is superseded for this hardware**, but the
  document itself is not deleted or edited — it remains an accurate record of the July 2026
  analysis and the reasoning method used, and the old `mdvrdocs/` source files it cites remain
  necessary to understand the now-secondary `vendors/lsz/` adapter's own design. No file is deleted
  by this ADR.
- **A follow-up implementation phase is expected, not started here**, covering: the `vendors/
  jt808/` field-width rework (§2), `0x0102` auth-code hashing/storage (§3), device-gateway's new
  video-signaling-forwarding responsibility (ADR-0024's revised §8), and the JT1078 media relay
  build-out itself (`services/jt1078/`, still an empty scaffold). Each remains gated on its own
  explicit go-ahead per this codebase's established pattern.

## References

- `mdvrdocs/LSZ-C5804DG-Q-F_Compliance_Confirmation_RAAD-TECH.pdf`
- `mdvrdocs/MDVR-808-1078-spec.pdf` (`MDVR-808-1078-SPEC V1.2`) — the new primary working
  reference for JT/T 808-2019/JT/T 1078-2016 wire format, per that document's own stated
  precedence order (§2.8): law/mandatory standards, then a signed project contract/interface
  confirmation, then the official JT/T 808-2019/JT/T 1078-2016 standard text itself (which RAAD
  still does not hold a direct copy of), then this vendor document, then product defaults.
- `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md` — the finding this ADR
  supersedes for this hardware; its deployable-separation/event-contract/Anti-Corruption-Layer/
  keep-dormant-code decisions remain in effect.
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md` — the
  `DeviceProtocolAdapter` multi-vendor architecture that makes this reversal cheap to absorb.
- `docs/architecture/adr/0015-device-plane-authentication-trust-model.md` — already named JT/T
  808's identity+credential model "the *right* shape" and generalized it platform-wide; this ADR
  is that model finally getting real credential material to verify, for the vendor it was
  originally observed in.
- `docs/architecture/adr/0024-jt1078-video-relay-architecture.md` (revised, same commit) — the
  video-relay design this ADR's §5 supersedes the LSZ-proprietary half of.
- `docs/vendor/HARDWARE_ANALYSIS.md`, `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` — superseded on
  the compliance question only; kept as the historical record and as the still-accurate basis for
  the now-secondary `vendors/lsz/` adapter.
- `services/device-gateway/src/vendors/jt808/`, `services/device-gateway/src/vendors/lsz/`,
  `services/device-gateway/src/gateway.py`.
- `backend/raad/modules/fleet_device/domain/entities.py` (`Device.auth_key_hash`).
- `.claude/rules/jt808.md`, `.claude/rules/jt1078.md`, `.claude/rules/security.md` #9,
  `.claude/rules/workflow.md` #1, #2, #8.
