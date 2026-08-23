# RAAD Video (JT1078) & Notification Systems — Architecture Review

**Status:** Review only — not an ADR, not an implementation plan commitment. No production code was
written to produce this document. Written at the user's explicit request, before any JT1078
implementation begins, per `.claude/rules/workflow.md` #7/#8 ("never violate approved architecture,"
"never implement business logic without an approved design").

**Date:** 2026-08-07
**Scope:** Video/JT1078 media architecture, and Notification channel extensibility (FCM/SMS/WhatsApp/Email).
**Sources reviewed:** `.claude/rules/{jt1078,jt808,architecture,security,backend}.md`; ADR-0008,
0009, 0010, 0012, 0013; `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §11/§13,
`RAAD_Phase3.1_Backend_LLD_v1_2.md` §4.2/§6.2/§9.2, `RAAD_Phase3.2_Database_Design_v1.md` §7.5–7.7,
`RAAD_Phase3.5_JT1078_Technical_Design_v1.md` (full); `docs/vendor/HARDWARE_ANALYSIS.md` §2/§4/§6/§11/§17,
`HARDWARE_INTEGRATION_PLAN.md` §8; `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md`
(unadopted draft, cited as informative only); `backend/raad/modules/video/` and
`backend/raad/modules/notifications/` (full domain/application/infra/api layers);
`backend/raad/modules/billing/application/ports.py` + `infra/adapters.py` (the closest in-repo
precedent); `services/jt1078/`, `services/device-gateway/` (structure + README); `docker-compose.yml`,
`docker-compose.prod.yml`, `docker-compose.coolify.yml`; `docs/runbooks/{coolify-deployment,vps-deployment}.md`;
`docs/PROJECT_STATUS.md` §3 (Video/JT1078/Notifications/CI-CD rows).

---

## Executive Summary

**Video/JT1078:** The *control plane* already matches the "no cloud video storage, ephemeral
session only" product direction almost exactly — `VideoSession` has no `stream_url`/token column
by design, D5 (zero parent access) is enforced, and the documented JT1078 rules (`.claude/rules/jt1078.md`)
already say "RAAD is not a video archive" and "media is repackaged, never passed through raw." What
does **not** exist is the media relay itself: `services/jt1078/` is an empty scaffold, `VideoProviderPort`
has zero bound adapters, and every video route deterministically fails with `NotImplementedError`
today. Separately, and more consequentially: **the actually-procured LSZ hardware is not JT/T
1078-compliant** — it has its own proprietary media-channel protocol, no RTSP/HLS/WebRTC output, no
crypto auth, and a hard constraint (live/playback/firmware-upgrade are mutually exclusive per device)
that the original JT1078 design doc never anticipated. The device-gateway/JT1078 service separation is
correct and should be kept; JT1078 should be its own container in the same Coolify VPS at MVP scale,
not folded into another service, with a real second VPS only justified by *measured* bandwidth/CPU/NAT-relay
load, not upfront. HLS is the clear right choice for playback; for live, WebRTC is the better long-term
fit but is genuinely more infrastructure to stand up (TURN/UDP) than a pragmatic WS-FLV/LL-HLS first cut —
this is a real decision fork, flagged for the eventual ADR, not decided here.

**Notifications:** Zero delivery mechanism exists in code today — `Notification.create()` only
writes a DB row and fans out over `/ws/notifications` (in-app only). This is a real, but
well-precedented, gap: the Backend LLD already named a `PushSenderPort → FcmPushSender` seam
(identically to how `PaymentProviderPort` was named), and Billing's `PaymentProviderPort` +
`StripePaymentAdapter`/stub-adapters + conditional-DI-binding pattern is a proven, ready-to-mirror
template already living in this exact codebase. The current `device_tokens` schema is FCM-specific
by column shape (`fcm_token`, `platform ENUM(android,ios)`) with no generic channel/address concept —
extending to SMS/WhatsApp/Email needs a real schema decision, not just new adapters.

---

## Part A — Video / JT1078

### A.1 Current state, with evidence

| Layer | State | Evidence |
|---|---|---|
| `VideoSession` aggregate | Real, complete, tested | `modules/video/domain/entities.py` — `request_live`/`request_playback`/`activate`/`end`/`fail`, all idempotent |
| `video_sessions` schema | Control metadata only, **no `stream_url`/token column** | Migration `65009ecd235a`; module docstring: "the actual ephemeral session/port/token state is Redis-owned by the JT1078 service itself... never a Business-DB column" |
| `VideoProviderPort` | Interface exists, **zero adapters bound** | `modules/video/application/ports.py:33-59` (`start_live`/`start_playback`/`stop`); `modules/video/infra/adapters.py` is a 17-line docstring-only file, no code |
| API routes | Real, D5-enforced, but dead-ended | `POST /video/live`, `/video/playback`, `/sessions/{id}/stop` all call `enforce_d5()` before touching `VideoApplicationService`, which raises `NotImplementedError` the instant a provider call is needed |
| `services/jt1078/` | **Empty scaffold** | `README.md` + `.gitkeep` in `src/{ingest,repackager,session,viewer}/`, `tests/`. README: "No session management, ingest, or repackaging logic is implemented yet... Language/runtime for this service is not yet decided by approved documentation." |
| Documented target design | Real, detailed, 322-line spec | `docs/business/RAAD_Phase3.5_JT1078_Technical_Design_v1.md` — standalone service, no storage, WebRTC primary/HLS-FLV fallback, JT808 command-downlink signaling, Redis-only ephemeral state |
| Actual procured hardware | **Not JT/T 1078-compliant** | `docs/vendor/HARDWARE_ANALYSIS.md` §2/§4: "nothing in any of the five source documents mentions JT/T 808, JT/T 1078... by name or by wire format... This hardware does not implement JT/T 1078" |

**The documented JT1078 design (Phase 3.5) assumes JT/T 1078-compliant hardware that RAAD does not
have.** This is the single most important finding of this review: implementing JT1078 "as documented"
against the real LSZ hardware is not possible — the same reality-vs-target gap ADR-0009/ADR-0010
already resolved for GPS/registration (JT808 → LSZ vendor adapter under `device-gateway`) has not yet
been resolved for video at all. No ADR currently addresses this.

### A.2 What the real (LSZ) hardware actually does, evidenced from vendor docs

- **Media-channel handshake** (`HARDWARE_ANALYSIS.md` §6, lines 163-169): a *separate TCP connection*
  from the GPS/signaling channel. Center sends `C508` (start/stop video) on the signaling channel →
  device opens a new media-channel connection, sends `V102` (media registration) → center ACKs
  `0x6000` → center may request `0x6002` (I-frame) → device streams `0x6011`/`0x6012`/`0x6013`
  (I-frame/P-frame/audio) → periodic `0x6403` from center. **This is entirely proprietary — no
  JT/T 1078 PS/RTP framing anywhere in it.**
- **Playback**: `C701` (search) → `C702` (request download, resumable) → device opens a media channel,
  `V103` → bytes stream via `0x6102`. "Availability depends on what the MDVR still retains" (matches
  the Phase 3.5 doc's own framing, which is otherwise written for JT/T 1078).
- **Mutual exclusivity, explicit vendor statement** (§6, lines 185-187): "live video, file download,
  remote upgrade, and playback are **mutually exclusive on a given device** — starting one
  interrupts/replaces another already in progress on the same media channel." This is a real
  constraint the current `jt1078.md` rule #4 (bounded concurrency) does not anticipate — that rule is
  about *global/per-org* ceilings across devices, not *single-device* channel exclusivity.
- **No standards-based output**: "RTSP, HLS, WebRTC... are not documented — the device only ever
  speaks its own opcode-framed binary media protocol **to the vendor's own CMS server**" (§6, lines
  188-190). The device never streams to a viewer directly, only to whatever terminates its signaling
  channel.
- **No crypto authentication of any kind** (§11, lines 328-336) — the same LSZ trust-model gap
  ADR-0015 already accepted for GPS (identity-only resolution against the device registry, no
  credential the hardware doesn't have) applies identically to the media channel.
- **Vendor CMS has no video API** — `GPS数据获取.docx` (the vendor's own CMS integration doc) "never
  mentions video" (`HARDWARE_INTEGRATION_PLAN.md` §8, confirmed by `HARDWARE_ANALYSIS.md` §17).
  There is no vendor-hosted video relay to integrate against instead of building one.

### A.3 Answers to the ten questions

---

#### Q1. Does the current architecture already support this design?

**Partially — aligned in intent and control-plane shape, not yet realized, and the documented target
protocol doesn't match the real hardware.**

- ✅ **"Not a cloud video storage platform"** — already true by construction: `video_sessions` has no
  media/URL column, and `jt1078.md` rule #2 states this in exactly the user's own words: "RAAD is not
  a video archive... the MDVR is the sole system of record."
- ✅ **"VPS never permanently stores video"** — same evidence; no persistence path for media bytes
  exists anywhere in the schema or the (unwritten) service.
- ✅ **"Live video exists only while someone is actively watching"** — matches rule #4 ("ports pooled
  and reclaimed on teardown") and the Phase 3.5 design's session lifecycle (`request_live → activate →
  end`), though nothing enforces "stops the instant the last viewer leaves" today since no viewer-count
  tracking exists yet (see A.3 Q5).
- ✅ **"VPS is responsible only for auth/session brokering"** — matches D5 enforcement
  (`enforce_d5()`, real and tested today) and the port's method shape (`start_live`/`start_playback`/`stop`
  — control operations only, no media data in the interface).
- ❌ **"Playback must stream directly from the MDVR's own storage"** — the *design intent* matches
  (Phase 3.5 §4: "device streams from its own local storage"), but nothing implements it; and the real
  vendor's playback protocol (`C701`/`C702`/`V103`/`0x6102`) is different from what Phase 3.5 assumes.
- ❌ **"When viewing stops, the stream stops"** — no code exists to observe "viewing stopped" and
  propagate a stop signal; this needs to be designed (see A.3 Q5).
- ❌ **The literal signaling mechanism won't work as documented** — Phase 3.5 assumes JT808 downlink
  commands `0x9101`/`0x9201`/`0x9205`/`0x9202`/`0x9102`; the real hardware uses `C508`/`C701`/`C702`
  and a same-media-channel exclusivity model. This needs an LSZ-specific media-signaling adapter, the
  same pattern `services/device-gateway/src/vendors/lsz/` already established for GPS.

**Bottom line:** the *shape* of the architecture (separate deployable, no storage, D5, ephemeral
Redis session state, repackage-don't-passthrough) is already correct and doesn't need to change. What's
missing is (a) the entire media-relay implementation, and (b) an LSZ-specific protocol adaptation
layer that the current JT1078 rule file and Phase 3.5 design don't yet account for — this is a real,
previously-unflagged documentation gap, structurally identical to the one ADR-0009 already resolved
for GPS.

---

#### Q2. Is `services/device-gateway` + `services/jt1078` still the correct separation?

**Yes — keep them separate.** Evidence:

- `.claude/rules/architecture.md` #2 (binding rule, verbatim): "**Device connectivity is a separate
  plane.** The device gateway (`services/device-gateway/`...) and JT1078 (`services/jt1078/`) are
  independent deployables." This already names *two* device-plane deployables, not one — the
  separation predates and is independent of the LSZ vendor-protocol question.
- Different scaling levers, both in the approved (not draft) Phase 2 doc, §13.2: "**JT808 Server:**
  shard devices across nodes (hash on device-id)... **JT1078 Media:** add media nodes; scale by
  concurrent-stream ceiling; enforce back-pressure/queueing." Connection-count-bound vs.
  bandwidth-bound are genuinely different resource profiles.
- `device-gateway`'s `DeviceProtocolAdapter` ABC (`src/adapter.py`) is shaped for exactly `name/start/
  stop/bound_port/session_count/device_session_count` — a small-frame signaling protocol interface.
  Every real and placeholder vendor under it (`jt808`, `lsz`, `teltonika`, `queclink`, `ruptela`) is a
  telematics protocol, never a media relay. Neither ADR-0009 nor ADR-0010 discusses folding video in;
  its absence from both documents is itself evidence the separation was never in question.
- Sustained media-bitrate streaming (repackaging H.265 frames, holding per-viewer WebRTC/HLS state,
  bandwidth-bound backpressure) is architecturally a different workload than JT808/LSZ's small-frame
  asyncio TCP signaling loop — merging them would make `device-gateway`'s existing, working,
  well-tested signaling path share fate with a much heavier, less predictable media workload for no
  benefit.

**One refinement the review surfaces**: the real vendor's media-channel *signaling* handshake
(`C508` on the existing GPS/signaling TCP connection) is not purely a JT1078-side concern — the
`C508` command has to be sent on the connection `device-gateway`'s own LSZ adapter already terminates.
This means **JT1078 needs a coordination path back through `device-gateway`** to trigger `C508`, the
same way the original design needed a JT808 downlink coordination path. This is a legitimate new
integration point between the two services (via the existing Redis broker, correlation-ID-tracked per
`jt808.md` rule #6 — not a new direct RPC channel), not a reason to merge them.

---

#### Q3. Should JT1078 be its own service inside the same Coolify VPS, or become part of another service?

**Its own service (own container/process), same Coolify VPS at MVP scale.**

Own service — not folded into `backend`/FastAPI (`architecture.md` #2: "FastAPI never terminates a
device socket" — a media relay is definitionally socket-terminating, in the device→relay direction and
often the relay→viewer direction too), and not folded into `device-gateway` (per Q2's reasoning: different
adapter shape, different resource profile, different failure-isolation boundary — a media-relay crash or
resource exhaustion should never be able to take down GPS ingestion).

Same VPS, for now — evidence:
- `docs/runbooks/vps-deployment.md`/`coolify-deployment.md` both size for the **entire current stack**
  on one box: "2 vCPU / 4 GB RAM / 40 GB disk — Postgres, Redis, the backend, worker, device-gateway,
  nginx, and prometheus all run on one box at MVP scale (`.claude/rules/architecture.md` #7: no
  premature microservices)." Neither runbook, nor any approved doc, provisions or even mentions a
  second VPS.
- `device-gateway` already establishes the exact precedent JT1078 should follow: an independently
  containerized process, on the same Docker Compose network, with its own published TCP ports
  (7808/7809) that bypass the HTTP-only nginx/Traefik proxy layer entirely — confirmed in
  `docker-compose.yml`, both overlay files, and `docker-compose.coolify.yml`'s own header comment:
  "`device-gateway` is deliberately NOT touched — its 7808/7809 are a raw TCP protocol... not HTTP, so
  Traefik/Coolify's routing doesn't apply to it." JT1078 would need the identical bypass pattern,
  extended to UDP if WebRTC is chosen (see Q8) — genuinely new infra work, but a well-precedented shape
  to extend, not a new pattern to invent.
- `.claude/rules/architecture.md` #7 (verbatim): "No premature microservices. Extraction from the
  monolith follows the documented roadmap (Phase 2 §13.3) and is **driven by measured load, not
  speculation**." No load has been measured yet — there is nothing to extract to a second VPS *from*.
- The event-bus half of any future split is already cheap regardless of physical placement: `raad:events`
  Redis Streams is already a proven multi-producer/multi-consumer hub (Business API's outbox relay +
  `device-gateway`'s `RedisEventPublisher` already coexist on it today, per ADR-0008/ADR-0012), and
  `services/device-gateway/src/broker_config.py` already keeps its own broker URL independently
  configurable "even though an MVP deployment will typically point both at the same Redis instance" —
  the exact same seam a JT1078 service should reuse from day one, so a *future* physical split needs no
  settings-shape change later.

**Recommendation:** ship JT1078 as its own container in the existing Coolify stack, publishing its
own ports the same way `device-gateway` does, reusing the same Redis instance/broker. Revisit VPS
separation only under the conditions in Q4.

---

#### Q4. Under what realistic conditions would another VPS actually be required?

Per `architecture.md` #7 ("driven by measured load, not speculation"), none of these are decided
in advance — they're the triggers that would justify measuring, then acting:

1. **Sustained egress bandwidth approaches the VPS's network ceiling.** The (unadopted, informative-only)
   device-plane draft estimates ~0.5–1.5 Mbps per sub-stream; even Phase 2 §13.1's own conservative
   "50 global concurrent streams" ceiling could mean 25–75 Mbps sustained, which competes directly
   with GPS ingestion, API traffic, and Postgres/Redis I/O on the same 2 vCPU/4 GB box the current
   runbooks size for.
2. **WebRTC TURN relay load, specifically.** The draft doc's own math: "TURN relay ≈ another full copy
   of the stream" — if a meaningful fraction of viewers are behind symmetric NATs/restrictive
   firewalls needing TURN (mobile carrier networks often are), bandwidth cost roughly doubles for
   those sessions. This is the single most likely first trigger if WebRTC is chosen for live.
3. **CPU load if transcoding is ever required.** The current design is explicitly "repackage, don't
   transcode" (cheap); the moment any viewer needs a different codec/bitrate than the source (e.g. a
   low-bandwidth mobile viewer), real transcoding becomes CPU-heavy and no longer shares a box
   comfortably with everything else.
4. **Device connection volume growth** competing with video for the same box's connection-handling
   capacity, once fleet size grows well beyond MVP scale (JT808/LSZ signaling is comparatively cheap
   per-connection, but a large fleet plus concurrent video is a real combined load).
5. **Security/isolation posture**: Phase 2 §11.2's own "Device DMZ subnet" concept (approved doc) —
   if RAAD later wants the raw device-facing TCP/UDP surface network-isolated from the HTTP-facing
   application tier for defense-in-depth, that's an infrastructure-driven (not load-driven) reason to
   split, independent of bandwidth.
6. **Geographic/regional latency**, at real scale (the draft doc's own "regional media POPs" framing) —
   only relevant once RAAD has fleets in genuinely distant regions from a single VPS's location.

**None of these apply today.** The concrete, honest trigger is: measure real concurrent-session
bandwidth/CPU against the deployed VPS's headroom once JT1078 is live, and split only when a specific
metric (not a guess) crosses a specific threshold.

---

#### Q5. What is the ideal live streaming flow?

Adapted from Phase 3.5 §3, corrected for the real LSZ protocol (not JT/T 1078) and the "stream stops
when viewing stops" requirement:

1. Org Admin (web dashboard only — D5, never mobile, never parent) requests live view of a camera:
   `POST /video/live`.
2. Backend: `enforce_d5()` (unconditional parent denial) + RBAC (`video.live.start`) + resolves the
   device's `organization_id` via `fleet_device` (no cross-module DB read).
3. Backend persists `VideoSession` (`REQUESTED`) in Postgres — real row, before any device signaling,
   matching the existing `VideoApplicationService.request_live_video` pattern exactly.
4. Backend calls `VideoProviderPort.start_live(...)`. The (new) JT1078 relay service allocates an
   ingest slot + a short-lived, single-use, signed viewer token, and registers ephemeral session state
   in Redis only (`device_id → {relay_node, ingest_port, token, org_id, expires_at}` — mirrors
   `jt808.md` rule #4's Redis session-state pattern).
5. Backend signals the device to start its media channel — **not** JT808 `0x9101` (doesn't exist on
   this hardware); instead, a correlation-ID-tracked command routed through `device-gateway`'s
   existing LSZ signaling connection, carrying `C508` (start video) with the relay's ingest host:port
   as the target. This command traverses the Redis broker (`raad:events`), the same
   correlation-tracked shape `jt808.md` rule #6 already mandates for JT808 downlink commands.
6. Device opens a **new** media-channel TCP connection directly to the relay's ingest port (not
   through `device-gateway` — the media channel is a separate connection per the vendor's own
   protocol), sends `V102` (media registration); relay ACKs `0x6000`, may request `0x6002` (I-frame).
7. Device streams `0x6011`/`0x6012`/`0x6013` (I/P-frame/audio) to the relay.
8. Relay demuxes the proprietary opcode frames and repackages (never transcodes when avoidable) into
   the chosen live transport (see Q8).
9. Viewer (web dashboard) connects **directly to the relay**, not through the backend, presenting the
   short-lived signed token from step 4 — the backend is out of the media path entirely from this
   point on, matching "VPS is responsible only for auth/session brokering."
10. Relay confirms first-frame delivery → publishes a `VideoSessionActivated`-shaped event on the
    broker → backend transitions `VideoSession` to `ACTIVE`.
11. **Viewer-count tracking, the piece needed to satisfy "when viewing stops, the stream stops" —
    genuinely new design, not yet specified anywhere**: the relay tracks active viewer connections per
    session; when the last viewer disconnects (or an explicit `POST /sessions/{id}/stop`), the relay
    tears down its own state, publishes a `VideoSessionEnded` event, backend transitions `VideoSession`
    to `ENDED`, and — critically — signals the device via the same `device-gateway` correlation-tracked
    path to stop its media channel (`C508` stop), so the bus's own hardware isn't left streaming to a
    now-empty relay. A short idle-timeout (no viewers for N seconds) should back this up defensively.
12. Every open/close audited with actor, device, camera, time (`jt1078.md` rule #6 — reuse the existing
    `audit_entries` write architecture, ADR-0007).

---

#### Q6. What is the ideal playback flow?

1. Org Admin specifies a device/camera + time window: `POST /video/playback`.
2. Same `enforce_d5()` + RBAC + org-resolution + `VideoSession` (`REQUESTED`) persistence as live.
3. Backend calls `VideoProviderPort.start_playback(...)`; relay allocates an ingest slot + signed
   token as before.
4. Backend signals the device via `device-gateway`'s LSZ connection: `C701` (search for footage in the
   window) → on confirmation, `C702` (request download, **resumable** — genuinely useful given
   cellular connectivity flakiness) with the relay's ingest host:port as target.
5. Device opens a media-channel connection, `V103` (playback registration), streams recorded bytes via
   `0x6102` — read live off its own local storage as bytes are requested, not pre-copied.
6. Relay repackages into a transport suited to scrubbing/seeking (HLS — see Q8) and buffers only a
   small in-memory/segment window needed for repackaging and seek support — **never a server-side
   copy of the full clip**, matching "playback must stream directly from the MDVR's own storage."
7. Viewer connects to the relay with the signed token; controls (pause/seek/resume) are proxied back
   through the same `device-gateway`-mediated channel as `C702`'s own resume semantics allow.
8. Availability is bounded by what the MDVR still retains locally — a real, disclosed limitation
   (matches Phase 3.5's own framing) that the UI should surface honestly (e.g., "footage may no longer
   be available on the device") rather than imply a guaranteed archive.
9. **Real constraint the original design didn't anticipate**: live/playback/firmware-upgrade are
   mutually exclusive *per device* on this hardware. The relay/backend must reject or queue a playback
   request if a live session is already active on that device (and vice versa) — a new validation rule
   at the `VideoApplicationService` layer, not previously needed under the JT/T 1078 assumption of
   independent logical channels.
10. Same teardown/event/audit shape as live once the viewer disconnects or the window is exhausted.

---

#### Q7. Should media be relayed by the VPS or streamed directly from the MDVR after authorization? Compare both.

**"True direct" (device → viewer, VPS entirely out of the media path) is not achievable with the
real hardware, and is not what the user's product direction actually requires once unpacked.**

Two reasons direct-to-viewer is architecturally impossible today:
- **NAT/connectivity**: `.claude/rules/security.md` #9 confirms "RAAD's device fleet runs over
  ordinary public cellular data... IPs are dynamic and carrier-NAT'd." A browser/mobile viewer cannot
  open a connection to a bus's own address — something reachable by both device and viewer must sit
  in the middle as a rendezvous point at minimum.
- **Protocol mismatch**: the device speaks a proprietary opcode-framed binary protocol
  (`0x6011`/`0x6012`/`0x6013`, §A.2 above); no browser or the Flutter apps can consume that natively.
  Something must translate it into WebRTC/HLS/etc. — this is precisely what `jt1078.md` rule #5
  already mandates ("media is repackaged, never passed through raw... clients never speak JT1078
  directly").

So the real comparison is narrower than "relay vs. direct" — it's **"does the relay buffer/store, or
does it purely pass bytes through as they arrive, with zero server-side retention?"** That's the
correct reading of the user's own bullet "playback must stream directly from the MDVR's own storage":
it means *no caching/copying server-side*, not *no network hop through the VPS*.

| | **Relay (repackage, zero retention)** | **Hypothetical "direct"** |
|---|---|---|
| Works with real (non-compliant) LSZ hardware | ✅ Yes — only viable option | ❌ Device can't speak WebRTC/HLS |
| Works through carrier NAT | ✅ Relay is the reachable rendezvous point | ❌ No path to the device's own address |
| Matches D5 (parents zero access) | ✅ Single auth chokepoint before any media flows | ⚠️ Would need per-device access control on the bus itself — doesn't exist |
| VPS cost | Bandwidth + light CPU proportional to concurrent viewers | None (not achievable, listed for completeness) |
| Matches "no cloud storage" | ✅ Yes, as long as implemented with zero server-side buffering beyond in-flight repackaging | N/A |
| Matches existing `jt1078.md` rule #5 | ✅ Exactly | ❌ Contradicts it |

**Conclusion: relay is not just the better choice, it is the only architecturally possible one** given
the real hardware — and it is already what this repository's own rules mandate. The important
implementation discipline is ensuring the relay is a true pass-through (bounded in-memory buffer for
repackaging/seek only, explicit teardown on session end, no disk writes of media ever) so the "no
cloud storage" intent is genuinely honored in the implementation, not just in the API contract.

---

#### Q8. Which streaming technology best fits RAAD (WebRTC, HLS, WS-FLV, etc.) and why?

**Playback: HLS. Not a close call.**
- Native seek/scrub, works in a plain `<video>` tag and Flutter's standard video players, no
  UDP/TURN/STUN infrastructure needed — pure HTTP, so it fits the *existing* nginx/Coolify Traefik
  HTTP-only proxying with **zero new port-exposure work** (unlike WebRTC — see below).
  Latency of several seconds is irrelevant for already-recorded footage.
- Matches Phase 3.5 §7's own "HLS/FLV offered as a fallback... for playback scrubbing" framing.

**Live: a genuine, currently-unresolved decision fork — flagged for the ADR, not decided here.**

| | **WebRTC** | **WS-FLV / LL-HLS** |
|---|---|---|
| Latency | Sub-second — best-in-class | Low-seconds — good, not best |
| Infra needed | STUN/TURN servers, UDP port range published on the host, bypassing Coolify/Traefik's HTTP-only routing (no existing precedent in this repo for UDP exposure — would need to extend `device-gateway`'s "leave a raw port published" pattern to UDP) | None new — plain WebSocket (TCP, HTTP-upgradeable) or HTTP-chunked, fits the existing all-HTTP Coolify/Traefik setup unchanged |
| Bandwidth cost under NAT | Can **double** per session needing TURN relay (draft doc's own estimate) | No relay-doubling effect — single TCP stream per viewer regardless of NAT |
| Matches `jt1078.md` rule #5's own wording | ✅ "WebRTC (primary, low-latency)" | Would be a documented deviation from the current rule text |
| Implementation complexity for a first ship | High (SDP/ICE negotiation, SFU-shaped relay logic, TURN operational burden) | Low (a WebSocket or chunked-HTTP endpoint pushing repackaged frames) |
| Matches "50 global concurrent streams" MVP ceiling | Fine either way at this scale | Fine either way at this scale |

**Recommendation (for the ADR to formally decide, not silently picked here):** ship live video with
WS-FLV or LL-HLS first — it requires no new network-exposure work, no TURN operational burden, and no
UDP handling, all genuine gaps confirmed by the infrastructure research (no STUN/TURN, no UDP
publishing pattern exists anywhere in this repo today). Treat WebRTC as the documented long-term
target (already named in `jt1078.md` #5) to add once (a) real concurrent-viewer load justifies the
latency improvement, and (b) the TURN/UDP infrastructure work is scoped and budgeted on its own. This
is explicitly a recommendation to *phase* the rule, not to change it — the eventual ADR should record
this as a deliberate, confirmed decision, not an assumption.

**WS-FLV vs LL-HLS as the first-cut choice**: WS-FLV is somewhat lower latency and simpler to
implement against opcode frames arriving in real time (push-as-you-decode); LL-HLS is more
standards-based and reuses the same packaging path as playback's own HLS output, reducing the number
of distinct media pipelines the relay needs to maintain. This specific choice is fine to leave to
implementation-phase judgment; either is a legitimate first cut and a materially smaller lift than
WebRTC.

---

#### Q9. Is the current notification architecture ready for FCM? How should Push/SMS/WhatsApp/Email fit into one NotificationChannel architecture?

**Not code-ready — zero delivery mechanism exists — but well-precedented and low-risk to build.**

Current state, evidenced:
- `Notification` aggregate has **no channel field** — `type` (`trip_started`, `approaching_stop`, etc.)
  is a category, not a delivery channel.
- `DeviceToken` is **FCM-specific by shape**: `fcm_token: FcmToken`, `platform: Platform` (`android`/
  `ios` only — no `web`), no phone number, no email address, no generic channel discriminator.
- `notifications/application/ports.py` **declares no delivery port at all** — and its own docstring
  claims "no approved document names a push-provider port interface for this module" — **this claim is
  incorrect**, evidenced by the Backend LLD naming `interface PushSenderPort # → FCM` verbatim, three
  times, in the exact same §4.2/§6.2/§9.2 sections that also name `PaymentProviderPort` (which Billing
  *did* implement as an unbound interface). This is a real, previously-unflagged discrepancy between
  the module's own self-documentation and the actual approved design record.
- `Notification.create()` only persists a DB row + fans out over `/ws/notifications` (in-app,
  already-connected sessions only). **No FCM, SMS, WhatsApp, or email send exists on any code path
  anywhere in this backend.**
- `core/config/settings.py` has an `FcmSettings` placeholder (`credentials_path` field) that is bound
  onto `Settings` but **never read anywhere** — no conditional-binding logic in `core/di/bootstrap.py`
  references it at all (unlike `PaymentSettings`, which drives real conditional adapter binding).
- Mobile: FCM is confirmed genuinely not started — no `firebase_messaging`/`firebase_core` dependency
  in `pubspec.yaml`, blocked on a real Firebase project (the identical external-account category as
  Payment's EVC Plus gap).
- The *original* architecture (Phase 2 §D2, approved) explicitly scoped SMS/WhatsApp/Email **out** of
  MVP, but explicitly named the future seam: "Notification-channel abstraction — SMS/Email/WhatsApp
  adapters can register later behind the same interface" — worded identically to how the same document
  frames Billing's own future multi-provider extension. No specific vendor (Twilio, WhatsApp Business
  API, SendGrid/SES, etc.) is named anywhere in the docs for any of the three.

**The ready-to-mirror precedent already exists in this exact codebase**: `billing.application.ports.
PaymentProviderPort` — an abstract port (`charge`/`verify_webhook_signature`/`parse_webhook_event`)
over typed request/result dataclasses, with `StripePaymentAdapter` (real) and `EvcPlusPaymentAdapter`/
`ZaadPaymentAdapter` (interface-complete stubs, `NotImplementedError`, honest about missing merchant
docs) bound conditionally in `core/di/bootstrap.py` via `RAAD_PAYMENT__PROVIDER` + a credentials-presence
check, with `BillingApplicationService` always constructible and the port resolved optionally
(`container.try_resolve(...)`). `VideoProviderPort` already follows the identical shape with zero
adapters bound. A `NotificationChannelPort` should follow the same three-part pattern: (1) one
abstract port with a `send(...)` method over a typed request/result dataclass pair, (2) one concrete
adapter per channel (`FcmPushAdapter` real once a Firebase project exists; `SmsAdapter`/
`WhatsAppAdapter`/`EmailAdapter` as honest interface-complete stubs until real provider
accounts/docs exist — mirroring `EvcPlusPaymentAdapter`'s precedent exactly, not a lesser effort), (3)
conditional DI binding per channel via env vars, allowing **more than one channel active
simultaneously** (unlike Billing, which binds exactly one provider — Notifications plausibly wants
push *and* SMS *and* email all active at once for different users/preferences, so the DI shape needs a
small, deliberate adaptation: bind a *set* of active channel adapters, not a single `try_resolve`).

**What genuinely needs a design decision (i.e., belongs in the eventual ADR, not decided here):**
1. **Schema shape for multi-channel delivery addresses.** Today's `device_tokens` table is FCM-only by
   column shape. Options: (a) generalize it into a `notification_channels` table
   (`user_id, channel ENUM(push,sms,whatsapp,email), address, verified_at, revoked_at`), or (b) keep
   `device_tokens` as the push-specific table and add separate tables per channel. Both are legitimate;
   (a) is more uniform and closer to the "one NotificationChannel architecture" framing in the user's
   own question, but is a real migration, not a trivial addition.
2. **Per-notification-type channel routing / user preference.** `notification_preferences` (Database
   Design §7.7) is documented but never built (`user_id PK, prefs_json`). This is the natural home for
   "which channels does this user want for which notification type" — needs to be built alongside the
   channel port, not as an afterthought, or the port has no way to know which channel(s) to actually
   invoke for a given notification.
3. **Delivery failure/retry semantics** — SMS/WhatsApp/Email providers fail differently than FCM
   (bounce, rate-limit, invalid-number) and may need a dead-letter/retry path; this doesn't exist for
   the in-app channel today since it can't meaningfully "fail" (it's just a DB write).
4. **`Platform` enum's missing `web` value** — a real, small gap if browser push is ever wanted
   (not asked about explicitly, flagged for completeness).

**Direct answer:** the architecture is *not* ready today (no code exists), but it is *well-positioned*
to become ready cheaply — the exact pattern needed already exists, proven, in the same codebase
(Billing), and the original design docs already anticipated this exact extension. This is a
low-architectural-risk, well-precedented gap to close — recommend a dedicated ADR (separate from the
video ADR) formalizing the schema/preference/multi-channel-binding decisions above before
implementation.

---

#### Q10. Final production architecture diagram

```mermaid
flowchart TB
    subgraph mobile["Flutter Mobile Apps"]
        ParentApp["Parent App<br/>(live GPS active-trip-only,<br/>ZERO video access — D5)"]
        DriverApp["Driver App<br/>(trip control, no video,<br/>no raw device GPS)"]
    end

    subgraph web["Web Dashboard (React)"]
        PlatformDash["Platform Dashboard<br/>(RAAD staff)"]
        OrgDash["Organization Dashboard<br/>(Org Admin — only role<br/>with video access)"]
    end

    subgraph coolify["Coolify VPS (single host, MVP scale)"]
        direction TB

        Traefik["Coolify Traefik<br/>(reverse proxy + TLS,<br/>HTTP/HTTPS only)"]

        subgraph appnet["Application containers (Docker network)"]
            Backend["Business API (FastAPI)<br/>10 bounded contexts incl.<br/>video, notifications, tracking"]
            Worker["Background Worker<br/>(Notification Worker,<br/>Report Worker, scheduled jobs)"]
            Postgres[("PostgreSQL<br/>video_sessions, notifications,<br/>device_tokens — control data only")]
            RedisCache["Redis DB 0<br/>(cache, latest position,<br/>rate limit, geofence)"]
            RedisBroker["Redis DB 1<br/>(raad:events Streams —<br/>shared multi-producer/consumer bus)"]
        end

        subgraph deviceplane["Device plane (raw TCP/UDP, bypasses Traefik — published host ports)"]
            DeviceGateway["device-gateway<br/>(JT808 dormant + LSZ active)<br/>GPS/heartbeat/registration<br/>+ media-channel C508 signaling"]
            JT1078["JT1078 / media-relay<br/>(NEW — own container)<br/>repackage-only, zero storage,<br/>ephemeral Redis session state"]
        end
    end

    subgraph devices["Bus MDVR Hardware (LSZ, cellular/dynamic IP)"]
        MDVR["LSZ MDVR<br/>GPS signaling channel +<br/>separate media channel<br/>(own local SD storage)"]
    end

    ParentApp -. "GPS/trip data + notifications only" .-> Traefik
    DriverApp -- "trip start/end, assignments" --> Traefik
    PlatformDash -- HTTPS --> Traefik
    OrgDash -- "HTTPS (video control + viewer token)" --> Traefik

    Traefik --> Backend
    Backend --> Postgres
    Backend --> RedisCache
    Backend -- "publish/consume domain events" --> RedisBroker
    Worker -- "consume events, send notifications" --> RedisBroker
    Worker --> Postgres

    Backend -- "signed viewer token (video session)" -.-> OrgDash
    OrgDash == "WebRTC/HLS/WS-FLV media<br/>(direct to relay, VPS out of media path<br/>after auth)" ==> JT1078

    Backend -- "correlation-tracked command<br/>(C508/C701/C702 via broker)" --> RedisBroker
    RedisBroker -- "command delivered" --> DeviceGateway
    DeviceGateway -- "LSZ signaling channel<br/>(GPS + video start/stop cmds)" --> MDVR
    DeviceGateway -- "DevicePositionReported/<br/>DeviceOnline/Offline events" --> RedisBroker

    MDVR == "media channel (opcode frames:<br/>0x6011/0x6012/0x6013, live/playback)<br/>NEW TCP connection per session" ==> JT1078
    JT1078 -- "session lifecycle events<br/>(activated/ended)" --> RedisBroker
    RedisBroker --> Backend

    Worker -. "FCM push (real once Firebase exists)<br/>SMS / WhatsApp / Email (stub adapters)" .-> mobile

    classDef missing stroke-dasharray: 5 5,fill:#fff3cd
    class JT1078 missing
```

**Legend / what's real today vs. new:**
- Solid boxes with no dashed border = fully implemented, tested, live-verified.
- `JT1078` (dashed border) = the one genuinely new component this review is about — everything else in
  the diagram already exists in the repository today, exactly as drawn (device-gateway containerized
  and deployed, Redis DB 0/1 split real, Postgres/notifications/video control-plane real, D5 enforced).
- The Worker's push/SMS/WhatsApp/Email arrow to mobile is dashed because **no delivery adapter exists
  yet at all** (Q9) — today that arrow terminates at `/ws/notifications` only, in-app, not shown
  separately for diagram clarity.

---

## Recommended Implementation Plan

Two independent domains, two independent ADRs — do not conflate them into one decision record, since
they have no shared design fork and different owners/timelines.

### Phase 0 — Formalize the design (ADRs, no code)

1. **ADR-video: "JT1078/Media Relay Architecture for Non-Compliant Hardware."** Must resolve, as
   explicit decisions (not silently assumed):
   - LSZ media-channel signaling adaptation (how `C508`/`C701`/`C702` get triggered through
     `device-gateway`, and the new correlation-tracked command shape needed).
   - Live transport choice for the first ship: WebRTC vs. WS-FLV/LL-HLS (this review recommends
     WS-FLV/LL-HLS first, WebRTC as a documented follow-on — but this is the ADR's call to make
     explicitly).
   - Runtime/language for `services/jt1078/` (still genuinely undecided — README says so plainly).
   - Viewer-count tracking / "stream stops when viewing stops" mechanism.
   - Single-device live/playback/firmware-upgrade mutual-exclusivity handling at the application layer.
   - Deployment: same-VPS container, ports published the same way `device-gateway` already is
     (extended for UDP if WebRTC is chosen).
2. **ADR-notifications: "Unified NotificationChannel Architecture."** Must resolve:
   - Schema shape (generalized `notification_channels` table vs. per-channel tables).
   - `notification_preferences` design (finally building the documented-but-unbuilt §7.7 table).
   - Multi-channel-simultaneously-active DI binding shape (a deliberate small deviation from
     Billing's single-provider precedent).
   - Which channels get real adapters now vs. honest stubs (FCM — blocked on a real Firebase project,
     same as Payment/Mobile M4's existing external blocker; SMS/WhatsApp/Email — no vendor named
     anywhere yet, so these should ship as stubs until a provider is chosen and approved, mirroring
     `EvcPlusPaymentAdapter`'s precedent).

### Phase 1 — Notifications (lower risk, unblocks mobile faster, no hardware dependency)

Build `NotificationChannelPort` + DI wiring + the `notification_preferences` table, following
Billing's exact pattern. Ship `FcmPushAdapter` as a real adapter the moment a Firebase project exists
(same external-account gate as today); ship SMS/WhatsApp/Email as honest stubs. This phase has zero
dependency on the video/JT1078 decision and can proceed in parallel or first.

### Phase 2 — Video foundation (the larger, hardware-coupled effort)

1. Decide `services/jt1078/`'s runtime (per the ADR).
2. Build the LSZ media-channel vendor adapter (mirrors `device-gateway/src/vendors/lsz/`'s existing
   GPS-adapter pattern, applied to the media channel instead).
3. Build the relay's ingest → repackage → deliver pipeline for the *chosen* first-cut live transport
   (WS-FLV/LL-HLS recommended) plus HLS for playback.
4. Bind `VideoProviderPort` to the new relay (mirrors `StripePaymentAdapter`'s conditional-binding
   shape).
5. Wire the `device-gateway` ↔ backend ↔ relay command/event coordination over the existing Redis
   broker (no new infrastructure needed for this part — `raad:events` already supports it).
6. Deploy as a new container in the existing Coolify Compose stack, publishing its own ports the same
   way `device-gateway` already does.

### Phase 3 — Video enhancement (only once Phase 2 is live and generating real usage data)

- Add WebRTC + TURN once real concurrent-viewer latency needs justify the added infrastructure
  (STUN/TURN servers, UDP port-range publishing).
- Revisit VPS separation only against the measured-load conditions in Q4 — not before.

### What this review deliberately does not do

No ADR was created (per instruction). No code was written. No dependency was installed or proposed
for installation. This document is evidence and analysis only, intended to inform the two ADRs named
in Phase 0 above.
