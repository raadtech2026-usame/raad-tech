# ADR-0024: JT1078 Video Relay Architecture

## Status

**Accepted, revised (2026-08-10, ADR-0025).** Originally written "Proposed — pending user review"
against the LSZ-proprietary-hardware premise ADR-0009 established at the time. `docs/architecture/
adr/0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` supersedes that premise — the
procured `LSZ-C5804DG-Q-F` is now treated as genuinely JT/T 1078-2016 compliant. This ADR is
revised in place (§1, Context point 3, §6, §7, §8, §14 reasoning, §16 point 1, Consequences,
References) rather than replaced, since it was never implemented — no code, migration, or
Dockerfile exists for any decision recorded here, before or after this revision. Every section not
listed above is protocol-agnostic policy (no cloud storage, stateless relay, session lifecycle,
Redis roles, why the services stay separate, VPS sizing, most of security/failure-handling/
deployment) and is unchanged by ADR-0025 — it did not depend on which wire protocol the hardware
actually speaks. **Still architecture-only: no code is authorized to begin by this revision
alone** — see ADR-0025's own "What this ADR does not do."

## Context

`docs/architecture/video-notifications-architecture-review-2026-08-07.md` ("the Review") audited the
current state of RAAD's video domain against the user's approved product direction:

> RAAD is not a cloud video storage platform. All recordings remain on the MDVR. The VPS never
> permanently stores video. Live video exists only while someone is actively watching. Playback must
> stream directly from the MDVR's own storage. The VPS is responsible only for authentication,
> authorization, session brokering, and stream coordination. When viewing stops, the stream stops. No
> cloud archive, DVR storage, or transcoding farm is planned.

The Review's findings, which this ADR formalizes into binding decisions:

1. **The control plane already matches this direction.** `VideoSession` (`backend/raad/modules/video/
   domain/entities.py`) has no `stream_url`/token column by design; D5 ("parents have zero reachable
   path to video, anywhere, ever") is enforced today via `interfaces/http/policy_guards.enforce_d5`
   on all three existing routes (`POST /video/live`, `POST /video/playback`,
   `POST /video/sessions/{id}/stop`); `.claude/rules/jt1078.md` already states "RAAD is not a video
   archive" and "media is repackaged, never passed through raw." None of this needs to change.
2. **The media relay itself does not exist.** `services/jt1078/` is a structural scaffold (README +
   `.gitkeep` placeholders in `src/{ingest,repackager,session,viewer}/`); `VideoProviderPort`
   (`video/application/ports.py`) has zero bound adapters (`video/infra/adapters.py` is a
   docstring-only file); every video route deterministically raises `NotImplementedError` after
   persisting a `REQUESTED` session row.
3. **The documented target design assumes hardware RAAD does not have — no longer true.**
   `docs/business/RAAD_Phase3.5_JT1078_Technical_Design_v1.md` designs against genuinely JT/T
   1078-compliant hardware — command downlink via JT808 `0x9101`/`0x9201`/`0x9205`/`0x9202`/
   `0x9102`. At the time this ADR was first written, the actually-procured LSZ MDVR
   (`LSZ-C5804DG-Q-F`) was believed, from vendor documentation (`docs/vendor/HARDWARE_ANALYSIS.md`
   §2/§4/§6), **not** to implement JT/T 1078 at all. **`docs/architecture/adr/
   0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` supersedes that finding**: new
   supplier documentation (`mdvrdocs/MDVR-808-1078-spec.pdf`, `mdvrdocs/
   LSZ-C5804DG-Q-F_Compliance_Confirmation_RAAD-TECH.pdf`), confirmed 2026-08-10, establishes the
   procured hardware genuinely speaks JT/T 1078-2016 — and, per that specification's own §6,
   signals it as ordinary JT/T 808 message types (`0x9101`/`0x9102`/`0x9105`/`0x9201`/`0x9202`/
   `0x9205`) on the **same already-authenticated connection** `device-gateway` holds, not a
   separately-signaled proprietary media channel. §1/§6/§7/§8 below are revised accordingly.

This ADR is deliberately scoped to **architecture only** — no dependency is chosen, no runtime
language is picked for `services/jt1078/`, and no code is written. Where the Review flagged a genuine
open fork (e.g., first-transport choice), this ADR makes the explicit decision the Review recommended
be made formally, rather than leaving it silently unresolved.

## Decision

### 1. Native JT/T 1078-2016 video signaling over the existing JT/T 808 connection (revised, ADR-0025)

RAAD implements JT/T 1078 media signaling/framing directly for its currently-procured hardware —
the LSZ-proprietary translation adapter this section originally specified is **not built**,
superseded before any implementation began. Per `mdvrdocs/MDVR-808-1078-spec.pdf` §6's own opening
line, JT/T 1078 signaling "reuses JT/T 808's message envelope, auth, serial-number, response, and
segmentation mechanism" — video signaling is **more JT808 message types on the same
already-authenticated connection** `device-gateway`'s `vendors/jt808/` adapter already holds open
for that device, not a second, separately-negotiated media channel.

The relay's/device-gateway's job, confirmed against the specification's own message tables
(§6.2/§6.3):
- **Live**: the Business API's `0x9101` request (§6.2.1) carries the relay's own ingest server IP,
  TCP port, and UDP port *directly in the message body*, addressed to a specific logical channel
  and data type (audio+video / video / two-way intercom / listen-only / broadcast / passthrough).
  `device-gateway` forwards this JT808-enveloped message on the connection it already holds — no
  opcode translation, no second signaling handshake. The device then opens a **new** connection
  directly to the relay's own published ingest host:port and streams the standard JT/T 1078
  extended-RTP payload (§6.2.1.1: `0x30316364` frame header, `V`/`P`/`X`/`CC`/`M`/`PT` bits,
  packet sequence, SIM-card number, logical channel, frame-type/data-type nibbles, timestamp,
  frame-interval fields, ≤950-byte payload) directly to the relay — the relay never needs
  `device-gateway` in the media-data path, matching this ADR's own already-established §6/§10
  design.
- **Control**: `0x9102` (§6.2.2 — close, switch stream, pause/resume, close two-way intercom) and
  `0x9105` (§6.2.3 — periodic packet-loss-rate status) travel the identical path: Business API
  issues, `device-gateway` forwards on the existing connection, no translation.
- **Playback**: `0x9201` (§6.3.3) carries the relay's ingest IP/ports plus playback mode (normal/
  fast-forward/keyframe-fast-reverse/keyframe-only/single-frame-upload) and speed directly in the
  request body — a materially **richer** control surface than the original LSZ-proprietary design
  (`C701`/`C702`) had, since it includes seek/speed/keyframe controls the old design would have
  needed to bolt on separately. `0x9202` (§6.3.4) then controls the in-progress playback session
  (start/pause/stop/fast-forward/keyframe-fast-reverse/drag-to-position/keyframe-play) — a
  dedicated control message the LSZ-proprietary design never had at all (see §7's own revision,
  below). `0x9205`/`0x1205` (§6.3.1/§6.3.2 — resource list query/response) let the platform browse
  what recordings actually exist on the device *before* requesting playback, a capability the
  original design also lacked.
- **Per-device mutual exclusivity** remains a real constraint, confirmed now by the specification
  itself rather than only the old proprietary-protocol documents (the underlying MDVR hardware
  still has one physical media pipeline regardless of which protocol addresses it) — the relay
  must still reject or queue a request that would start a second concurrent session type on a
  device already running one; this requirement is unchanged by this revision.
- **`0x0102` now provides a real, verified credential for the signaling connection itself**
  (ADR-0025 §3) — a materially stronger starting point than the "no cryptographic authentication
  exists on this channel" finding this section originally recorded for the LSZ-proprietary design.
  The **media socket** (the RTP-extended TCP/UDP connection the device opens directly to the
  relay's ingest port) still has no additional handshake of its own beyond what the specification
  documents — so the relay's own correctness anchor for *that* socket remains **identity/session
  correlation**, matching ADR-0015's already-accepted trust model exactly as originally specified
  here: the relay accepts an inbound media connection only when it correlates to a session the
  Business API genuinely requested and issued ingest coordinates for, never by trusting the
  connection's source IP alone. Unsolicited/unexpected media connections are still rejected and
  audited, mirroring `jt808.md` #5.
- **No second vendor-adapter surface is needed.** `device-gateway`'s existing `vendors/jt808/`
  package (now the live, primary adapter per ADR-0025 §4) gains a **new responsibility** —
  recognizing and forwarding the JT/T 1078 message-ID range (`0x9xxx`/`0x1xxx`) on an
  already-authenticated connection — not a second protocol stack. `vendors/lsz/` (the
  proprietary-protocol adapter) never had, and still does not have, any media-channel
  implementation of its own (its own module docstring already scopes video "out of scope here,
  tracked separately") — it remains exactly as dormant for video as it now is for GPS (ADR-0025
  §4).
- The original JT/T 1078 rule text and Phase 3.5 design were already the **target framing for a
  genuinely-compliant vendor** — this revision confirms that target is now the *actual* design,
  not a hypothetical future one; `.claude/rules/jt1078.md`'s "Reality check" preamble is retired
  accordingly (ADR-0025 §6).

### 2. Why RAAD is not a cloud video storage platform

This is a product-scope decision, not an infrastructure limitation — recorded here as a binding
architectural constraint so no future implementation drifts toward it by convenience:

- **Cost and liability.** Storing video centrally means RAAD bears unbounded storage cost that scales
  with fleet size × camera count × retention window, plus the compliance/liability burden of being the
  custodian of footage of minors (students) — a materially different risk posture than being a
  pass-through session broker.
- **The hardware already provides the archive.** The MDVR retains footage locally (confirmed by its
  own resource-list query, `0x9205`/§6.3.1 — a feature that only makes sense against existing
  on-device storage the platform can enumerate; revised, ADR-0025, supersedes this bullet's
  original `C701`/`C702` citation). Duplicating that storage centrally would be redundant
  infrastructure solving a problem the hardware already solves.
- **Matches the existing, tested invariant.** `video_sessions` has no media-bearing column today
  (§Context, point 1) — this decision doesn't change any existing code, it formalizes why that shape
  is correct and must stay that way as the relay is built.
- **Scope boundary, explicitly**: CLAUDE.md's own Product Scope section already establishes RAAD is
  "not a school ERP" and flags scope creep as the main design risk in this codebase; "not a video CDN/
  archive" is the identical discipline applied to this domain — any future feature request implying
  server-side video retention (e.g., "let admins download old footage from RAAD") must be flagged and
  independently approved, never assumed.

### 3. MDVR as the only permanent recording storage

Formalized as a hard architectural invariant, not a current-phase simplification:

- The relay (§4) **never writes video bytes to disk, object storage, or any database, ever, under any
  code path** — this is a structural property, not a configuration option (no "future setting" to
  enable recording is planned or referenced anywhere).
- All footage availability is bounded by what the MDVR itself still retains — a real, disclosed
  limitation the UI must surface honestly ("footage may no longer be available on the device"), not
  imply a guaranteed archive exists.
- The Business database (`video_sessions`, `cameras`) stores **control metadata only** — who
  requested what, when, for how long, and its outcome — never a byte of media. This table shape is
  already correct today (§Context) and this ADR fixes it as permanent, not provisional.
- No RAAD-operated backup, replication, or disaster-recovery process (Priority 1 Item 1's `pg_dump`/
  `rclone` mechanism, `docs/runbooks/backup-and-restore.md`) ever needs to account for video data,
  because none exists to back up — this is a deliberate simplification of RAAD's own operational
  surface, not an oversight.

### 4. JT1078 Relay as a stateless media forwarder

"Stateless" here means specifically: **no persistent state, no media retention** — not "no state at
all" (the relay necessarily holds brief, bounded, in-memory session/connection state for the duration
an active stream is being forwarded).

- **What the relay holds, and for how long**: per-session in-memory state (device connection, viewer
  connection(s), a small repackaging buffer bounded to what's needed for protocol translation and
  seek support — not a growing cache), for exactly the lifetime of that session. All of it is
  discarded the instant the session ends (§5). None of it survives a relay process restart, and none
  of it is meant to (a restarted relay simply has zero active sessions — correct, not a bug).
- **What the relay never holds**: any row in Postgres (that's `video_sessions`', the Business API's,
  concern — the relay is not a `video_sessions` writer, only an event *publisher* the Business API
  consumes, §8/§9), any file on local disk, any object-storage upload, any long-lived cache of a
  previously-viewed clip.
- **Repackage, never transcode, where possible** — per the Review's Q7/Q8 findings and the existing
  `jt1078.md` #5 rule, the relay translates the vendor's opcode-framed I/P-frames into the chosen
  output transport's container format without re-encoding the underlying video, keeping CPU cost low
  and avoiding a "transcoding farm" (explicitly out of scope per the user's own product direction).
- This formalizes `.claude/rules/jt1078.md` #2 ("RAAD is not a video archive... only ephemeral
  session/port/token state (Redis) and control metadata... persisted") as the binding shape for the
  relay's own internal design, not just its external contract.

### 5. Session lifecycle: start, authorization, viewer count, automatic teardown

One state machine, shared by live and playback (differing only in what "start" signals to the device):

1. **Start** — Org Admin (the only role with any video access, D5) calls `POST /video/live` or
   `POST /video/playback`. Backend enforces `enforce_d5()` + RBAC + resolves the device's
   `organization_id` (no cross-module DB read, via `fleet_device`'s own application service), then
   persists `VideoSession(REQUESTED)` — exactly the existing, tested code path, unchanged.
2. **Authorization** — the backend, and only the backend, decides whether a session may exist at all.
   The relay performs **no user authentication and no RBAC** of its own (mirroring Phase 3.5 §5's
   already-approved "JT1078 performs no user login" decision) — it trusts exactly one thing: a
   short-lived, single-use, signed viewer token minted by the backend at session-creation time,
   presented by the viewer when connecting to the relay. An expired, reused, or unsigned token is
   rejected by the relay directly, audited, with no round-trip to the backend needed for that check.
3. **Viewer count** — the relay tracks active viewer connections per session (a new mechanism the
   Review's Q5 identified as genuinely unspecified anywhere in the prior design). This is the
   mechanism that makes "when viewing stops, the stream stops" real rather than aspirational:
   - Session transitions to `ACTIVE` once the relay confirms the device's media channel is producing
     frames (regardless of whether a viewer has connected yet — matches the existing `VideoSession.
     activate()` semantics).
   - The relay decrements its own viewer count on each viewer disconnect; when it reaches zero, a
     short grace/idle timeout (bounded, on the order of seconds — the exact value is an
     implementation detail, not an architectural one) starts; if no viewer reconnects before it
     expires, teardown begins automatically.
   - A defensive idle-timeout independent of viewer count also applies (protects against a relay-side
     bug in viewer-count bookkeeping ever leaving a session stuck open) — belt-and-suspenders, not a
     substitute for real viewer-count tracking.
4. **Automatic teardown** — on last-viewer-disconnect-timeout, explicit
   `POST /video/sessions/{id}/stop`, or session-window expiry (playback), the relay: stops accepting
   new viewer connections, signals the device to stop its media channel via the same coordination path
   used to start it (§8), discards all in-memory session state, and publishes a session-ended event.
   The backend, on receiving that event, transitions `VideoSession` to `ENDED` — the existing,
   already-idempotent `VideoSession.end()` domain method, unchanged.
5. **Every transition audited** — actor, device, camera, session id, and timestamp, reusing the
   existing shared-kernel `audit_entries` write architecture (ADR-0007) exactly as `jt1078.md` #6
   already requires; no new audit mechanism is introduced.

### 6. Live streaming architecture

1. Backend persists `VideoSession(REQUESTED)`, calls `VideoProviderPort.start_live(...)`.
2. The relay allocates an ingest slot and a signed viewer token, holding both only in its own
   in-memory session state (no Postgres write from the relay — see §9/§10 for the exact Redis/Postgres
   split).
3. Backend signals the device via `device-gateway` (§8) — `0x9101` (real-time A/V transmission
   request), carrying the relay's ingest server IP, TCP port, and UDP port directly in the message
   body, addressed to a specific logical channel, correlation-ID tracked. **Revised, ADR-0025**:
   this is now a standard JT/T 808-enveloped message forwarded on the connection `device-gateway`
   already holds — no opcode translation.
4. Device opens a **new** connection directly to the relay's own published ingest host:port
   (distinct from the GPS/signaling connection `device-gateway` holds) and streams the standard
   JT/T 1078 extended-RTP payload (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.2.1.1) — no separate
   media-channel handshake message exists in this protocol; the device begins streaming directly
   once connected.
5. Device streams the extended-RTP frames (I-frame/P-frame/B-frame/audio, per the payload's own
   `数据类型` nibble) to the relay; the relay repackages into the chosen live transport (§14) and
   marks the session `ACTIVE` once the first frame is successfully repackaged.
6. Viewer connects **directly to the relay** (not proxied through the backend) with the signed token
   from step 2 — the backend's involvement ends at token issuance; it is never in the live media path.
7. Session ends per §5's teardown sequence; device is signaled to stop the same way it was signaled to
   start.

### 7. Playback architecture directly from the MDVR's local storage

Same shared state machine (§5), same non-storage discipline (§3), different device-side commands:

1. Backend validates `window_end > window_start` (existing `VideoSession.request_playback` invariant,
   unchanged) and persists the session.
2. Backend, optionally, first queries `0x9205` (resource list, §6.3.1) to let the operator browse
   what recordings actually exist on the device before requesting playback — a capability the
   original LSZ-proprietary design didn't have. Backend then signals the device via `device-gateway`:
   `0x9201` (remote playback request, §6.3.3), carrying the relay's ingest IP/ports, playback mode
   (normal/fast-forward/keyframe-fast-reverse/keyframe-only/single-frame-upload), speed, and the
   requested time window directly in the message body — a standard JT808-enveloped message,
   forwarded unchanged by `device-gateway`, same as live (§6). **Revised, ADR-0025**: supersedes
   `C701`/`C702`.
3. Device opens a connection to the relay's ingest endpoint and streams the requested window as
   extended-RTP frames (§6.2.1.1) — the relay never receives, and the device is never asked to
   send, more than what's actively being requested/played. There is no "download the whole clip,
   then serve it" step anywhere in this flow — that would silently reintroduce server-side storage
   this ADR (§3) forbids. In-progress playback (pause/resume/stop/fast-forward/keyframe-fast-
   reverse/drag-to-position/keyframe-play) is controlled via `0x9202` (§6.3.4) — a dedicated
   control message the original design lacked entirely; seeking uses this message's own
   drag-to-position control rather than re-issuing a fresh request.
4. Relay repackages into HLS (§14) for scrubbing/seek support — `0x9202`'s native drag-to-position
   control (point 3, above) is the mechanism that makes seeking work correctly rather than the
   relay caching earlier bytes to satisfy a seek locally.
5. Availability is bounded by the MDVR's own retention — a real limitation, surfaced honestly in the
   product UI (a design/frontend concern, out of this ADR's scope, but named here so it is not
   silently forgotten when that UI is built).
6. Mutual-exclusivity enforcement (§1) applies identically to playback: a playback request is
   rejected/queued if a live session is already active on that device, and vice versa.

### 8. Device Gateway ↔ JT1078 Relay coordination

The two services **never communicate directly** (no new RPC/HTTP channel between them) — they
coordinate exclusively through the existing Redis Streams event broker (ADR-0008), the same mechanism
`device-gateway` already uses to publish `DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/
`DeviceAlarmRaised` onto `raad:events` today. This is a deliberate reuse, not a new integration
pattern:

- **Command direction (Backend → device, via device-gateway)**: the backend publishes a
  correlation-ID-tracked command event (mirroring `jt808.md` #6's existing "every platform-issued
  command must be traceable back to the requesting use-case and its result" requirement, extended to
  this new command family) carrying the target device id, the JT/T 1078 message ID (`0x9101`/
  `0x9102`/`0x9201`/`0x9202`/`0x9205`, §6/§7), and its already-encoded body (including the relay's
  ingest host:port for `0x9101`/`0x9201`). **Revised, ADR-0025**: `device-gateway`'s `vendors/
  jt808/` adapter (the live, primary adapter per ADR-0025 §4 — not `vendors/lsz/`) consumes this
  event and **forwards the message as-is** on the GPS/signaling connection it already holds open
  for that device, using the same JT808 envelope/serial-number/response machinery it already uses
  for every other outbound command — no opcode translation, no vendor-specific encoding step. The
  relay itself never needs to know that connection exists or reach it directly.
- **Result/telemetry direction (device-gateway/relay → Backend)**: `device-gateway` publishes a
  command-result event (success/failure of the signaling step) the same way it already publishes
  `DeviceOnline`/`DeviceOffline`; the relay independently publishes its own session-lifecycle events
  (activated/ended/failed) once it has real signal from the media channel itself. The backend consumes
  both to drive `VideoSession`'s own state transitions — it does not need to correlate device-signaling
  success with media-channel success itself; each service reports its own observed truth.
- **Why not a direct connection between the two services**: this would create a new point-to-point
  dependency neither service currently has on the other, duplicate the correlation/audit machinery the
  broker already provides for free, and reintroduce exactly the kind of tight coupling `.claude/rules/
  architecture.md` #3 ("device plane communicates with the business plane exclusively through
  asynchronous domain events... never direct DB writes, never synchronous RPC") already forbids between
  device-plane and business-plane services — a principle this ADR extends to apply between the two
  device-plane services themselves, for the same reasons (independent failure domains, no shared
  deploy/version coupling, one proven integration pattern reused instead of a second one invented).

### 9. Redis responsibilities

Two distinct roles, using the existing DB 0 (cache) / DB 1 (broker) split (Priority 1 Item 4,
`docker-compose.yml`) — no new Redis instance, no new logical database number:

- **DB 1 (broker, `raad:events`)** — carries the command/result/lifecycle events described in §8. The
  relay becomes a **third participant** on this stream, alongside the Business API's outbox relay and
  `device-gateway`'s own `RedisEventPublisher`/`RedisDeviceRegistryConsumer` — the Review's
  infrastructure findings already confirm this stream is a proven multi-producer/multi-consumer hub, so
  this is not new broker capability, just a new named participant.
- **DB 0 (cache) or a relay-owned Redis key namespace** — holds the relay's own ephemeral per-session
  state as a durable-enough-for-lookup cache (device id, ingest port, viewer token, org id, expiry) —
  matching `jt808.md` #4's existing "session state lives in Redis" pattern applied to media sessions
  instead of device connections. This is a performance/observability convenience (e.g., allowing an
  admin tool or a restarted relay process to see what sessions *were* active), not a source of truth —
  the relay's own in-process memory is authoritative for an actively-forwarding session; Redis holds a
  recoverable *record* of session metadata, never the media itself, and is never required for the
  media path to function.
- **Redis is not a video buffer.** No design decision in this ADR uses Redis to hold frame data,
  segments, or any media byte, at any point — consistent with §3/§4.
- **DB numbering, connection settings, and password reuse** the exact conventions already established
  by Priority 1 Item 4 (`RedisConnectionSettings`, `--requirepass`, `AOF`, `noeviction`) — no new
  Redis-hardening decision is needed, only a new consumer/producer application on the existing,
  already-hardened instance.

### 10. Backend responsibilities

Unchanged from what already exists and is already tested — this ADR does not expand the Business
API's own responsibilities, it confirms they stay exactly this narrow:

- **Authentication/authorization**: RBAC (`video.live.start`/`video.playback.start`/
  `video.sessions.stop` permissions) + D5 (`enforce_d5`), exactly as implemented today.
- **Session-record persistence**: `VideoSession` lifecycle in Postgres — control metadata only, never
  media, never a relay implementation detail beyond what's needed for control (§3).
- **Session brokering**: issuing the signed viewer token and (via `device-gateway`, §8) the device
  start/stop signal — the backend never opens a media socket itself and never proxies media bytes.
- **What the backend explicitly does *not* do**: it is never in the live/playback media data path
  (confirmed already true today, since `VideoProviderPort`'s own method signatures — `start_live`/
  `start_playback`/`stop` — carry no media data, only control parameters and return an opaque
  `reference` string); it does not retry or compensate for relay-side media failures beyond
  transitioning `VideoSession` to `FAILED` (the existing, already-implemented `VideoSession.fail()`
  method) and surfacing that state to the caller.

### 11. Why `services/device-gateway` and `services/jt1078` remain separate

Confirmed by the Review (Q2) and formalized here as binding, not merely observed:

- `.claude/rules/architecture.md` #2 already names them as two independent deployables — this
  predates and is independent of the LSZ-vendor-protocol question this ADR resolves.
- **Different scaling levers** (Phase 2 §13.2, approved): device-gateway shards by device-id/connection
  count; the relay scales by concurrent-stream/bandwidth ceiling. Coupling them would force one
  workload's scaling decisions onto the other for no benefit.
- **Different failure-isolation boundary**: a media-relay resource exhaustion event (e.g., bandwidth
  saturation from too many concurrent viewers) must never be able to degrade GPS ingestion, which is a
  safety-relevant data path (live tracking, geofencing) that has no acceptable downtime budget tied to
  video's own, materially less critical, availability needs.
- **Different adapter shape**: `device-gateway`'s `DeviceProtocolAdapter` ABC (`name`/`start`/`stop`/
  `bound_port`/`session_count`/`device_session_count`) is designed around small-frame TCP signaling
  loops; every real and placeholder vendor under it is a telematics protocol. Media relaying is a
  categorically different workload (sustained bandwidth, per-viewer fan-out, repackaging pipelines) that
  does not fit this interface and was never intended to.
- **The one integration point between them is deliberately narrow** (§8) — an existing, proven,
  loosely-coupled event mechanism, not a reason to merge the processes that use it.

### 12. Why a single Coolify VPS is the default deployment

- Both existing deployment runbooks (`docs/runbooks/vps-deployment.md`, `docs/runbooks/
  coolify-deployment.md`) size for the **entire current stack** — Postgres, Redis, backend, worker,
  device-gateway, nginx/nginx-replaced-by-Traefik, prometheus — on one 2 vCPU / 4 GB RAM / 40 GB disk
  box. No approved document provisions, or even mentions, a second VPS.
- `.claude/rules/architecture.md` #7: "No premature microservices. Extraction from the monolith
  follows the documented roadmap... and is driven by measured load, not speculation." No video load has
  ever been measured (nothing has run yet) — there is nothing to extract *from*.
- `services/device-gateway` already establishes the exact precedent the relay should follow:
  independently containerized, own published host ports (7808/7809), same Docker Compose network, same
  Redis instance, bypassing the HTTP-only Traefik/nginx proxy layer entirely (confirmed in
  `docker-compose.coolify.yml`'s own header comment: "`device-gateway` is deliberately NOT touched —
  its 7808/7809 are a raw TCP protocol... not HTTP, so Traefik/Coolify's routing doesn't apply to it").
  The relay follows the identical shape: its own container in the same Compose stack, its own published
  port(s), added to — not replacing — the existing topology.
- The event-bus half of the integration (§8/§9) is already location-independent by design (ADR-0008's
  own "`broker.url` deliberately a separate setting from `redis.url`... preserves the option to run the
  broker on its own instance later without a settings-shape change") — colocating today creates no
  lock-in that would make a future split harder.

### 13. Measurable conditions that would justify a second VPS

None of the following are decided in advance — they are the specific, measured triggers (per rule #7
above) that would justify provisioning a second VPS, evaluated against real telemetry once the relay is
live, not speculated about now:

1. **Sustained egress bandwidth** for concurrent video sessions approaches the VPS's network ceiling,
   measured against actual headroom after accounting for GPS ingestion, API traffic, and database I/O
   on the same box.
2. **TURN relay load**, specifically if/when WebRTC is adopted (§14) — TURN roughly doubles bandwidth
   for NAT'd viewers; if a meaningful share of viewers need it, this is the single most likely first
   trigger.
3. **CPU load from transcoding**, if a future requirement ever forces re-encoding (different codec/
   bitrate per viewer) rather than pure repackaging — a materially heavier workload than what this ADR
   scopes for.
4. **Device-connection volume** growing enough that device-gateway's own resource needs begin
   contending with the relay's for the same box's capacity, independent of video-specific load.
5. **A deliberate network-isolation decision** (Phase 2 §11.2's "Device DMZ subnet" concept) — an
   infrastructure/security-driven reason to split, independent of load.
6. **Genuine multi-region latency needs**, only relevant once RAAD operates fleets far enough apart
   that a single VPS's location measurably degrades live-video latency for some regions.

The concrete operational trigger: instrument the relay's own bandwidth/CPU usage from day one (reusing
the existing `/metrics` Prometheus mechanism, Priority 1 Item 5 — no new observability tooling needed),
and revisit this decision only when a specific measured metric crosses a specific threshold against the
deployed VPS's actual headroom.

### 14. Recommended first implementation transport

**Unaffected by ADR-0025's native-protocol revision.** The relay now *ingests* standards-based
JT/T 1078 extended-RTP (§1, above) instead of an LSZ-proprietary opcode stream — but a browser's
`<video>` element or a WebSocket client still cannot consume that ingest format directly either
way, so the repackaging need, and the reasoning below for what to repackage *into*, is unchanged.

**Playback: HLS.** Not a close call, per the Review's Q8 — native seek/scrub support, works in a plain
`<video>` element and Flutter's standard players, pure HTTP (zero new network-exposure work on top of
the existing Coolify/Traefik or nginx setup), and several-second latency is irrelevant for already-
recorded footage. This matches Phase 3.5 §7's own "HLS/FLV... for playback scrubbing" framing exactly.

**Live: WS-FLV or LL-HLS for the first implementation; WebRTC as the deliberate, documented follow-on.**
This is the one place the Review flagged as a genuine, previously-unresolved fork, and this ADR now
resolves it explicitly:

- `jt1078.md` #5 currently reads "WebRTC (primary, low-latency)... HLS/FLV (fallback)." This ADR
  **amends the practical rollout order, not the rule's long-term target**: WebRTC remains the
  documented eventual choice for live video; WS-FLV/LL-HLS ships *first* as a deliberate, justified
  phasing decision, not a silent downgrade.
- **Why not WebRTC first**: it requires STUN/TURN infrastructure and UDP port publishing that exist
  nowhere in this repository today (confirmed by the Review's infrastructure research — no
  precedent for UDP exposure anywhere in the Docker/Coolify setup, only TCP, via device-gateway's
  existing pattern), plus real operational burden (TURN credential rotation, relay capacity planning)
  disproportionate to an MVP with a "50 global concurrent streams" ceiling (Phase 2 §13.1). TURN's own
  bandwidth-doubling effect for NAT'd viewers (§13.2) makes it the more expensive choice to stand up
  first, not just the more complex one.
- **Why WS-FLV/LL-HLS is the correct first cut**: needs no new network-exposure work at all — a plain
  WebSocket (TCP, HTTP-upgradeable) or HTTP-chunked/LL-HLS endpoint fits the *existing* all-HTTP
  Coolify/Traefik or nginx proxying unchanged, meaning §12's single-VPS deployment needs zero new
  infrastructure to ship this. Latency (low seconds) is an acceptable, disclosed trade-off for a first
  release, not silently hidden — this should be stated plainly in any user-facing "live" indicator
  copy once built (a frontend concern, out of this ADR's own scope, noted so it isn't forgotten).
- **Migration path**: WebRTC is added later, behind the same `VideoProviderPort` abstraction (already
  transport-agnostic by its own method signatures — `start_live` returns an opaque `reference`, never a
  transport-specific detail), once real concurrent-viewer usage data justifies the TURN/UDP investment
  (§13). No `VideoSession`/API contract change is anticipated to be needed for this future addition —
  the transport is an internal relay implementation detail the existing control-plane contract already
  abstracts away correctly.

### 15. Security considerations

- **D5 remains absolute and is not weakened anywhere in this design.** Parents have no reachable code
  path to any video capability — not the control-plane API (already enforced), and, by this ADR's own
  §5 (only a backend-issued, backend-authorized token reaches the relay) and §2's Product Scope
  reasoning (no archive for anyone, parent or otherwise, to eventually be granted access to), not the
  relay either.
- **No credential the hardware doesn't have is invented.** Per ADR-0015 (already accepted for GPS,
  extended here to the media channel): identity resolution against a known, expected session
  correlation is the primary control; no fabricated device secret, no assumed TLS/mTLS the hardware
  cannot perform.
- **Viewer tokens are short-lived, single-use, and session-scoped** — matching Phase 3.5 §5's already-
  approved design ("single-session, non-transferable, revoked on teardown"), minted only by the backend
  after full RBAC/D5 evaluation, never derivable or guessable by the relay or a client.
- **Unsolicited media-channel connections are rejected and audited**, mirroring `jt808.md` #5's existing
  device-authentication posture, extended to this second channel (§1).
- **The relay's own exposed ports are a new public attack surface** — unlike the Business API (behind
  Traefik/nginx, HTTP-only, TLS-terminated), the relay's ingest/viewer ports are raw TCP (and
  eventually UDP for WebRTC), the same trust boundary `device-gateway`'s existing 7808/7809 already
  establishes. This ADR does not invent a new network-hardening mechanism beyond what device-gateway
  already operates under — firewall/exposure posture should be reviewed alongside device-gateway's own
  (a known, already-flagged gap: the Review's infrastructure research found `vps-deployment.md`'s
  firewall step doesn't actually open 7808/7809 as written, an existing inconsistency worth fixing
  regardless of this ADR, tracked separately, not silently absorbed into this decision).
- **No video data is ever at rest**, so there is no video-specific encryption-at-rest requirement to
  design for (§3) — `.claude/rules/security.md` #7's "encryption at rest for the database and backups"
  requirement is unaffected, since no video byte ever reaches either.
- **Audit coverage** (§5, point 5) extends the existing `audit_entries` mechanism — no new audit store,
  no new retention policy, matching `.claude/rules/security.md` #8 ("every important action is audit-
  logged, append-only, tamper-evident") without inventing a parallel mechanism.

### 16. Failure handling

- **Device-signaling failure** (the `0x9101`/`0x9201` command — revised, ADR-0025, supersedes
  `C508`/`C701`/`C702` — never reaches the device, or the device rejects it — e.g., it's offline,
  or a mutual-exclusivity conflict per §1): `device-gateway` publishes a failure result event; the
  backend transitions `VideoSession` to `FAILED` (the existing, already-implemented method) and
  surfaces this to the caller. No retry is automatic — a human re-requests if appropriate, matching
  the existing "no `retry()`, a retry is a brand-new request" posture this codebase already applies
  elsewhere (e.g., `Payment.initiate`).
- **Media-channel connection never arrives** (device accepted the signal but never opens the expected
  connection — e.g., network drop mid-handshake): the relay's own allocation times out (a bounded
  wait, not indefinite), publishes a failure event, same `FAILED` transition.
- **Media channel drops mid-session** (bus loses connectivity while streaming): the relay detects the
  disconnect, ends the session (§5's teardown path), publishes a session-ended-with-reason event; the
  backend records this as `ENDED` (not `FAILED` — the session *did* run, it simply stopped, matching
  `VideoSession.end()`'s existing idempotent semantics) with the reason available in the event payload
  for audit/troubleshooting. The viewer's client is expected to show a clear "connection lost" state
  (a frontend concern) rather than a silent stall — mirroring `.claude/rules/flutter.md` #6's existing
  "offline/safety UI never fails silently" principle, extended to video.
- **Relay process crash/restart**: because no state survives beyond an active session by design (§4),
  a relay restart simply means every session it was holding ends uncleanly from the device's
  perspective (it keeps streaming to a now-closed ingest port until its own send fails or a
  keepalive/timeout on the device side gives up) and from the backend's perspective (no further
  lifecycle events arrive for those sessions). The backend must apply a defensive timeout on any
  `VideoSession` stuck in `REQUESTED`/`ACTIVE` with no recent lifecycle event, transitioning it to
  `FAILED`/`ENDED` after a bounded window — a reconciliation safety net, not a primary mechanism, the
  same "belt-and-suspenders" posture already applied to viewer-count idle timeouts (§5).
- **Redis (broker) unreachable**: video session start/stop requests fail loudly (the existing
  `NotImplementedError`-on-unbound-port posture this codebase already applies everywhere a Redis-backed
  port is required but unavailable — `LatestPositionPort`, the login rate limiter, etc.) — never a
  silent, un-auditable partial success.
- **Concurrent conflicting request** (a second live/playback request for a device already running one,
  §1's mutual-exclusivity constraint): rejected with a clear, specific error at request time — this is
  a validation failure, not a "failure handling" recovery case, but named here since it's a hardware
  constraint (one physical media pipeline per device) this ADR's own design must still account for
  even though the wire protocol addressing it is now standard JT/T 1078.

### 17. Deployment architecture

- **One new container**, added to the existing Docker Compose stack (`docker/docker-compose.yml`) —
  not a new Compose file, not a new Coolify project. Mirrors `device-gateway`'s exact existing service
  block shape: its own Dockerfile, `depends_on: redis (healthy)`, environment carrying its own
  broker/Redis connection settings (reusing `DEVICE_GATEWAY_BROKER_URL`'s established pattern of an
  independently-configurable-but-typically-coincident setting, per ADR-0008/ADR-0012's own precedent).
- **Ports**: the relay's ingest port (device-facing) and viewer-facing port(s) are published directly
  on the host, bypassing Traefik/nginx — extending device-gateway's already-established "raw
  TCP/(eventually UDP), not HTTP, so the HTTP-only proxy doesn't apply" precedent
  (`docker-compose.coolify.yml`'s own header comment already states this reasoning for device-gateway;
  this ADR applies the identical reasoning to the relay). If/when WebRTC (§14) is added later, this
  is the point where a UDP port range (and any STUN/TURN service) would need genuinely new
  infrastructure work — explicitly deferred, not designed here, since it is out of scope for the
  WS-FLV/LL-HLS first cut this ADR recommends.
- **No `nginx`/Coolify-Traefik routing changes are needed for the WS-FLV/LL-HLS first cut** specifically
  *because* it can be reached over plain WebSocket/HTTP — worth stating explicitly since it's a real,
  concrete reason (not just a preference) this ADR's §14 recommendation minimizes deployment risk for
  the initial release.
- **Same Redis instance, same Postgres instance** as the rest of the stack (§9/§10) — no new managed
  service, no new connection-pooling concern beyond what already exists.
- **Coolify's own management scope is unaffected**: Coolify continues to manage exactly `frontend`/
  `backend` (the two HTTP-routed services) per `docs/runbooks/coolify-deployment.md`; the relay, like
  `device-gateway`, sits outside Coolify's Traefik routing entirely, reachable only via its own
  published host ports — no change to that runbook's own documented scope is needed.
- **Sizing**: no changes to the documented 2 vCPU / 4 GB RAM / 40 GB disk minimum are prescribed by
  this ADR — actual sizing validation is explicitly deferred to real measured load (§13), consistent
  with `.claude/rules/architecture.md` #7.

## Consequences

- **`services/jt1078/`'s empty scaffold gets a concrete architectural target** to implement against —
  this ADR does not pick its runtime/language (still explicitly open, matching the README's own
  "not yet decided by approved documentation" caveat), but every other structural decision
  (ingest/repackager/session/viewer responsibilities already named in that scaffold's own folder
  layout) now has a justified design behind it — the relay ingests standards-based JT/T 1078
  extended-RTP (§1, revised) rather than an LSZ-proprietary opcode stream.
- **No new LSZ media-channel vendor adapter is needed** (superseded, ADR-0025 §5) — the relay's
  ingest side is a standard extended-RTP demuxer; no vendor-specific media-protocol translation
  layer exists to write.
- **`device-gateway` gains a new responsibility on its existing `vendors/jt808/` adapter** (not
  `vendors/lsz/` — ADR-0025 §4): recognizing and forwarding the JT/T 1078 message-ID range
  (`0x9xxx`/`0x1xxx`, §1) on its already-open, already-authenticated signaling connection. This is
  an *addition* to that adapter, not a redesign of it — the existing GPS/registration/heartbeat
  handling is unaffected, and no opcode-translation step is needed (revised, ADR-0025 — supersedes
  this bullet's original "issuing `C508`/`C701`/`C702`" framing).
- **`.claude/rules/jt1078.md`'s "Reality check" preamble is retired** (ADR-0025 §6, same commit as
  this revision) — the rule file's JT808-signaling wording is no longer a hypothetical future
  target, it is what device-gateway's `vendors/jt808/` adapter is now expected to actually forward.
- **No changes to any other bounded context, RBAC matrix, or tenant-isolation code** are anticipated —
  this ADR's scope is entirely the `video` module's own provider implementation plus a new
  device-gateway responsibility and a new standalone service; D5/RBAC enforcement, `VideoSession`'s
  own domain shape, and every other module remain untouched by this decision.
- **The Notifications channel-architecture question (Q9 of the Review) is explicitly out of scope for
  this ADR** — a separate ADR, per the Review's own Phase 0 recommendation, covers it independently.

## Verification (deferred to implementation phase — recorded here so the eventual implementation is held to it)

- Unit: the extended-RTP payload demux logic (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.2.1.1), in
  isolation, mirroring `services/device-gateway/tests/`'s existing coverage style for the GPS
  adapter (checksum, framing, escaping, encoder/decoder tests already exist there as a direct
  precedent) — revised, ADR-0025, supersedes this bullet's original "LSZ media-adapter opcode"
  framing.
- Integration: a live end-to-end proof mirroring `services/device-gateway/scripts/verify_redis_e2e.py`'s
  existing precedent — a real (or faithfully simulated) `0x9101`/extended-RTP handshake, through a
  real relay process, publishing real events onto a real Redis broker, consumed by the real
  Business API.
- Architecture-gate: confirm the relay never imports Business API `domain`/`infra` code and vice versa
  (extending `tests/architecture/test_module_boundaries.py`'s existing cross-deployable discipline,
  the same posture already applied to `device-gateway`'s own independence from `backend/raad`).
- Security regression test: an unsolicited/unexpected media-channel connection is rejected and
  audited, not silently accepted — mirroring `jt808.md` #5's existing test coverage for the GPS
  channel, extended to media.
- A live-verified proof that no video byte is ever written to disk or Postgres under any code path
  exercised by the test suite — the single most safety-critical invariant this ADR establishes,
  deserving explicit, deliberate test coverage per `.claude/rules/testing.md` #3's "safety-critical
  invariants require explicit regression tests, not incidental coverage."

## References

- `docs/architecture/adr/0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` — supersedes
  this ADR's original §1/Context-point-3 LSZ-proprietary premise; see that ADR for the full
  evidentiary record of the 2026-08-10 supplier documents and the reversal they establish.
- `mdvrdocs/MDVR-808-1078-spec.pdf` §6 — the JT/T 1078 signaling/media specification this ADR's §1
  now implements directly.
- `docs/architecture/video-notifications-architecture-review-2026-08-07.md` — the review this ADR
  originally formalized; §2/§4/§6/§9/§11 (the LSZ-proprietary findings) are superseded by
  ADR-0025, the rest (product-scope reasoning, session-lifecycle design, Redis/deployment
  architecture) is unaffected.
- `docs/vendor/HARDWARE_ANALYSIS.md` — historical record of the July 2026 analysis; its
  media-channel findings are superseded by ADR-0025 for this hardware, the document itself is not
  deleted.
- `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §8 — video-workflow implications, Option A/B analysis
  (Option A, RAAD terminates the protocol directly, remains the chosen option — only *which*
  protocol is terminated changes, per ADR-0025).
- `docs/business/RAAD_Phase3.5_JT1078_Technical_Design_v1.md` — the target design for a genuinely
  JT/T 1078-compliant vendor; this ADR's §1 now implements that target directly, not as a
  hypothetical future case.
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §11 (deployment topology), §13
  (NFR targets, scaling levers, evolution roadmap).
- `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md` — the original GPS-side
  vendor-protocol-termination precedent this ADR extended to video; its compliance finding is
  superseded by ADR-0025, its deployable-separation/event-contract decisions are not.
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md` — the `DeviceProtocolAdapter`
  pattern and multi-vendor/multi-adapter service shape referenced throughout.
- `docs/architecture/adr/0008-redis-streams-event-broker.md`, `0012-development-redis-environment.md` —
  the shared broker mechanism §8/§9 reuse verbatim.
- `docs/architecture/adr/0015-device-plane-authentication-trust-model.md` — the identity-only trust
  model §1/§15 extend to the media channel.
- `.claude/rules/jt1078.md`, `.claude/rules/jt808.md`, `.claude/rules/architecture.md` #2/#3/#7,
  `.claude/rules/security.md` #9, `.claude/rules/flutter.md` #6.
- `backend/raad/modules/video/` (domain/application/infra/api — the existing, unchanged-by-this-ADR
  control plane).
- `services/device-gateway/` (the multi-vendor precedent and the existing Redis/broker integration
  §8/§9 reuse).
- `docker/docker-compose.yml`, `docker/docker-compose.coolify.yml`, `docs/runbooks/
  coolify-deployment.md`, `docs/runbooks/vps-deployment.md` — the deployment precedent §12/§17 extend.
