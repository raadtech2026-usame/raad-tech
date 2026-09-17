# Live Tracking, MDVR and Device-Plane Investigation — 2026-09-17

**Scope:** Live Tracking (GPS), live video and intercom only. Covers the MDVR, JT/T 808, JT/T 1078,
`device-gateway`, `jt1078-relay`, the backend realtime path, the frontend Live Tracking views, and
the Coolify/Hostinger deployment. Nothing outside that scope was looked at or changed.

**How to read the labels:**

| Label | Meaning |
|---|---|
| **PROVEN** | Read directly in code, config or the supplier spec, or reproduced by running the real code in this pass |
| **EVIDENCED** | Comes from production-log facts recorded in commit messages `04c176c` and `8c55a82` (2026-09-15) |
| **HYPOTHESIS** | Fits the evidence but needs the diagnostic step named next to it before you act on it |

**Limits of this pass:** I had no shell on the VPS, no view of Coolify's environment variables, no
device-gateway/relay/backend logs, no packet capture, and no access to the MDVR settings screen. The
local stack wasn't running either (the Docker Desktop daemon was down). Part D exists to collect the
missing evidence, step by step.

---

## 1. Executive summary

The device reaches the VPS. What fails is the step **between registration and a stable,
authenticated session**. Nothing downstream can work until that step does: position ingest,
`is_online`, the live map, camera discovery, video and intercom all depend on it. On top of that,
some video and intercom settings on the Coolify path point at `localhost` or can't be routed, so
video would still fail after the session problem is fixed.

| # | Finding | Label | Affects |
|---|---|---|---|
| 1 | **Auth-code regression (`8c55a82`, 2026-09-15).** A code is deleted after it's used once, but the spec says the terminal keeps its code and sends it again on every reconnect. Reproduced: accepted on the 1st and 2nd connection, rejected on the 3rd. | PROVEN | Localhost and VPS |
| 2 | **`0x0200`/`0x0704` location reports are never acknowledged.** The spec says the terminal waits for `0x8001` and, after its maximum retries, treats the link as broken and reconnects. Heartbeats are acknowledged; positions never have been. | PROVEN (spec + code) | Mostly the VPS/4G link |
| 3 | **RAAD is set on MDVR "Server 3".** Per spec §3.4.1/§7.5, a terminal only runs downlink commands from its *main* platform. If Server 3 is a secondary centre, GPS can arrive but camera discovery (`0x9003`), live video (`0x9101`), playback and intercom are ignored. If more than one slot points at `187.7.22.79:7808`, the slots knock each other offline in a loop. | HYPOTHESIS (check D14) | VPS video/intercom, session churn |
| 4 | **Localhost gets no device traffic.** The only setup ever verified locally is the MDVR on the LAN or its own Wi-Fi AP, dialing `192.168.100.63:7808` through a Windows Firewall rule. An MDVR on 4G pointed at `187.7.22.79` can't reach a private LAN address. | HYPOTHESIS (check D16) | Localhost |
| 5 | **Since `faedc85` (2026-09-13), a report without a GPS fix never moves the marker and never writes the snapshot.** An indoor bench unit now shows "No Fix" and no marker, where it used to show a marker at a stale (wrong) location. | PROVEN (intended behaviour change) | Looks like "Localhost broke" |
| 6 | **The Coolify path has no route for the video viewer, and both JT1078 defaults are wrong in production.** `JT1078_SIGNALING_URL` defaults to `ws://localhost:7911`. `JT1078_RELAY_PUBLIC_INGEST_HOST` defaults to empty, which becomes `0.0.0.0`. Neither is checked at startup. The `/jt1078/` route from audit B1 exists only in nginx configs that Coolify never runs. | PROVEN (defaults); real Coolify values unknown (D2) | VPS video/intercom |
| 7 | **Camera discovery runs once per device, ever** (`av_attributes_requested_at`). If that one `0x9003` was ignored or lost, the device never gets cameras and nothing retries. | PROVEN | VPS video/intercom |
| 8 | **The production logging is blind.** `DEVICE_GATEWAY_LOG_LEVEL` is never passed by any compose file, so setting it in Coolify does nothing. `response_frame_sent`, `position_report_published` and `frame_received` log at DEBUG, so the lines added on 2026-09-15 can't appear in production. | PROVEN | Diagnosis |
| 9 | **Redis has a 256 MB `noeviction` limit and an unbounded `raad:events` stream** (Known Issue #25). About 700 B per position works out to ~3.3 MB/day per bus at a 20 s report interval. When Redis is full, the write before `0x8100`, the session write before `0x8001`, the snapshot and the outbox relay all fail, which takes down the whole device plane. | PROVEN (arithmetic); current memory unknown (D8) | Both, eventually |

**What is known to work in production (EVIDENCED, `04c176c`/`8c55a82`):** the MDVR reaches
`187.7.22.79:7808` over 4G. `0x0100` frames parse, the terminal ID resolves in the registry, and
registration succeeds. Then *"10 of 11 observed device connections never proceed past it, and the
one that did send 0x0102 produced no authentication_succeeded/authentication_failed/handler_error"*.
Separately: *"19 registrations for one terminal in a 2-hour window, only 1 ever reached 0x0102"*.
So the TCP port, Docker publishing, the firewall for 7808, the parser, the outbox relay and the
registry projection all work. **Failure point: registration → authentication → session.**

---

## 2. Evidence base

**Code read in full or in the relevant part:**

- `device-gateway`: `gateway.py`, `vendors/jt808/server.py`, dispatcher, the registration,
  authentication, heartbeat, location and bulk-location handlers, `provisioning_port.py`,
  `auth_code_hashing.py`, `encoder.py`, `registration_response.py`, `position_body.py`,
  `registry/*`, `session/*`, `connection/*`, `commands/command_sender.py`,
  `commands/redis_video_signaling_consumer.py`, `latest_position/*`, `cache_config.py`,
  `broker_config.py`, `logging_setup.py`
- `jt1078-relay`: `config.py`, `viewer/websocket_server.py`, `viewer/viewer_server.py`
- Backend: `main.py` realtime lifecycle, `tracking/api/ws.py`,
  `interfaces/http/realtime.py`, `policy_guards.resolve_tracking_decision`,
  `core/events/redis_streams.py`, `tracking/events/subscribers.py`, worker `bootstrap.py`,
  `video/infra/adapters.py`, `core/di/bootstrap.py` (video binding),
  `fleet_device/application/services.py` (`record_device_seen`, `update_device_details`),
  `fleet_device/domain` (`TerminalId`, `update_terminal_id`), `core/config/settings.py`
- Frontend: `config/env.ts`, `shared/hooks/useWebSocket.ts`,
  `features/live-monitoring/useVehiclePosition.ts`
- Deployment: `docker-compose.yml`, `.coolify.yml`, `.coolify.full.yml`, `.prod.yml`,
  `.dev.yml`, `docker/.env.example`, the local `docker/.env` (non-secret keys only), both device
  Dockerfiles, `frontend.Dockerfile`, `infrastructure/nginx/conf.d/{dev,frontend}.conf`,
  `prometheus.yml`, `docs/runbooks/coolify-deployment.md`
- Supplier spec `mdvrdocs/MDVR-808-1078-spec.pdf`: §3.4, §3.5, §5.1, §5.2.1, §5.3.1, §7.1, §7.5, §7.8
- Git history of every device-plane path since 2026-08-18, including the full diffs of `8c55a82`,
  `04c176c`, `a5b4bde`, `faedc85` and `21f0868`

**Checks run in this pass:**

1. **Auth-code reproduction.** Ran the real `ProjectionBackedJt808ProvisioningPort` against a real
   `DeviceRegistryProjection` (§5, C1).
2. **Coolify file drift check.** Regenerated `docker-compose.coolify.full.yml` with the command in
   its own header and applied its three documented patches. The result is **byte-identical** to the
   committed file, so the Coolify file has not drifted from its sources.
3. **Stream sizing.** Measured the size of a real `DevicePositionReported` stream entry with the
   real `RedisEventPublisher` (~700 B).

---

## 3. Reference architecture vs the actual implementation

### 3.1 Hop-by-hop comparison

| Reference hop | Actual implementation | Status |
|---|---|---|
| MDVR → 4G → `187.7.22.79:7808` | Compose `ports: 7808:7808` on `raad-device-gateway`, not reset by the Coolify overlay | ✅ Reachable (EVIDENCED) |
| Device Gateway (`gateway.py`) | One process runs `Jt808Server` (7808) and the dormant LSZ `MdvrServer` (7809), plus two Redis consumers: registry and video commands | ✅ The healthcheck probes **7809**, not 7808 (minor) |
| JT808 Protocol Server (`server.py`) | `ConnectionManager` → `FrameBuffer` → `PacketParser` → `MessageDispatcher` → handlers | ⚠ Findings 1 and 2 |
| Device Event Publisher | `RedisEventPublisher`: `XADD raad:events` on **Redis DB 1** | ✅ |
| GPS Processing / Redis latest position | **Split in two.** Snapshot: `LocationHandler` → `RedisLatestPositionWriter`, `SET vehicle:{id}:last` on **DB 0**, valid live fixes only, inside the gateway. History: the **worker** (`notification-worker` consumer group) → `DevicePositionReportedProcessor` → `vehicle_positions` | ⚠ Different from the diagram |
| JT1078 Media Service (`relay.py`) | **A separate container**, `raad-jt1078-relay`, **not** hosted by the device gateway. Ports 7910 (device ingest) and 7911 (viewer WS-FLV) | ⚠ Different from the diagram |
| Media ingest & FLV (`flv_muxer.py`) | Inside the relay, plus ffmpeg G.711A→AAC | ✅ |
| API layer → services → UoW → outbox → outbox relay | Exists, but **device positions never go through the outbox.** The outbox only carries backend-originated events: `DeviceRegistered`, `DeviceActivated`, `DeviceAssignedToVehicle`, `DeviceTerminalIdChanged`. Those flow to the gateway's registry, so the worker's outbox relay is a hard dependency for device authentication | ⚠ Different from the diagram |
| JT1078 Relay Adapter | Backend `Jt1078RelayAdapter`: Redis-list RPC `raad:jt1078:session_requests` (DB 1) → relay; then a **direct** `XADD Jt1078SignalCommandRequested` (not through the outbox) → gateway video consumer → `0x9101` on the JT808 socket | ✅ |
| Realtime API (`ws.py`) | Inside the **backend** process. `BrokerFanOutWorker`, consumer group `ws-tracking`, 10 events per ~1 s tick. Endpoint at the root: `/ws/tracking` (not under `/api/v1`) | ✅ Throughput ceiling at scale |
| PostgreSQL | ✅ | ✅ |
| Redis Streams & cache | One Redis. DB 0 = cache/snapshot, DB 1 = broker, device sessions and JT1078 RPC. `noeviction`, 256 MB | ⚠ Finding 9 |
| Prometheus/Grafana | Prometheus scrapes **only** `backend:8000/metrics`. Neither `device-gateway` nor the relay exposes metrics. **No Grafana container** | ⚠ Not in the deployment |
| NGINX (TLS, routing) | **Not running on the Coolify path** (gated behind the `gateway` profile). Traefik does TLS and routing. `frontend.conf` only serves the SPA: **no `/api`, `/ws` or `/jt1078` proxy** | ❌ Different from the diagram. The viewer route only exists in nginx |
| React dashboard / Flutter | `env.wsBaseUrl` + path. `VITE_*` values are **baked in at build time** | ⚠ Must be `wss://` in production |

### 3.2 Actual GPS path

```
MDVR ──TCP/4G──▶ 187.7.22.79:7808 ──DNAT──▶ raad-device-gateway : Jt808Server
  0x0100 ─▶ TerminalRegistrationHandler
             ├─ ProjectionBackedJt808ProvisioningPort.authorize_registration
             │    (in-memory DeviceRegistryProjection, rebuilt from raad:events on start)
             ├─ XADD DeviceAuthCodeIssued ............ (Redis DB1)   ◀── must succeed first
             └─ reply 0x8100 {serial, result, auth_code}
  0x0102 ─▶ TerminalAuthenticationHandler
             ├─ verify_auth_code  ◀── FINDING 1
             ├─ RedisDeviceSessionRegistry.add_exclusive  (SET device_session:{terminal}, DB1)
             │    └─ another connection already holds the terminal → close it ("superseded")
             └─ reply 0x8001
  0x0002 ─▶ HeartbeatHandler → touch() → first touch: XADD DeviceOnline → reply 0x8001
  0x0200 ─▶ LocationHandler → session lookup BY TERMINAL ID → touch()
             ├─ SET vehicle:{id}:last (DB0) only when is_gps_valid
             ├─ XADD DevicePositionReported (DB1)
             └─ NO REPLY  ◀── FINDING 2

raad:events ─(group ws-tracking)──────▶ raad-backend  → ws.py → resolve_tracking_decision → WS {"type":"position"}
raad:events ─(group notification-worker)▶ raad-worker → vehicle_positions; devices.is_online/last_seen_at;
                                                        first online → publish 0x9003 request (once, ever)
Browser: GET /api/v1/tracking/vehicles/{id}/latest (DB0 snapshot) + WSS /ws/tracking (subscribe)
         GET /api/v1/tracking/vehicles/online     (devices.is_online + MGET snapshots)
```

### 3.3 Registry path (a hard dependency for authentication)

```
Org Admin: create → activate → assign device ─▶ fleet_device ─▶ outbox table
  ─▶ raad-worker OutboxRelayWorker (5 s / 100 rows) ─▶ XADD raad:events
  ─▶ device-gateway RedisDeviceRegistryConsumer (group device-gateway-registry) ─▶ DeviceRegistryProjection
Without every step: 0x0100 → result terminal_not_found → socket closed.
```

### 3.4 Video and intercom path

```
Browser POST /api/v1/video/live ─▶ enforce_d5 ─▶ VideoApplicationService ─▶ Jt1078RelayAdapter
  ─▶ RPUSH raad:jt1078:session_requests (DB1) ─▶ raad-jt1078-relay SessionRequestServer
       returns ingest_host = JT1078_RELAY_PUBLIC_INGEST_HOST (empty → "0.0.0.0"), ingest_port 7910, viewer token
  ─▶ XADD Jt1078SignalCommandRequested ─▶ device-gateway RedisVideoSignalingConsumer
  ─▶ CommandSender: 0x9101 on the terminal's JT808 socket  ◀── ignored by a secondary centre (FINDING 3)
  ─▶ MDVR dials server_ip:7910 ─▶ relay ingest ─▶ FLV (+AAC) ─▶ viewer :7911
Browser opens stream_url = JT1078_SIGNALING_URL + "/viewer?token=…"   ◀── FINDING 6
  (the camera_id comes from `cameras` rows that only 0x9003 discovery creates  ◀── FINDING 7)
```

---

## 4. Part A — Localhost: what changed

The known-good local state: live tracking and video were verified against the physical unit
(terminal `00000000014482607571`) on 2026-08-19, and again on 2026-09-01/-02. The GPS path was last
confirmed with live data on 2026-09-13 (in `faedc85`'s own investigation). The ranking below is by
likelihood.

### A1. The MDVR no longer dials the dev PC — HYPOTHESIS, environmental

- **What the working setup was:** the MDVR in `WorkMode=AP` or on the same LAN as the PC. The
  device dialed the PC's LAN address (`JT1078_RELAY_PUBLIC_INGEST_HOST=192.168.100.63` in the local
  `docker/.env`). Inbound 7808 needed a manually added Windows Firewall rule, "RAAD JT808 7808"
  (Known Issue #20).
- **What it is now:** "Server 3 → `187.7.22.79:7808`" over 3G/4G. A 4G modem can't route to
  `192.168.100.63`. Even if another slot still holds the LAN address, the device only uses it while
  it's on that Wi-Fi.
- **The PC's IP is DHCP-assigned and has changed before.** It moved from `192.168.10.210` to
  `192.168.100.63` (ADR-0036), and a stale value broke video until it was corrected.
- **Impact:** zero `connection_accepted` lines from a non-`127.0.0.1` address in the local
  device-gateway log. No code change can fix this; the device has to be able to reach the PC.
- **Check:** D16.

### A2. Auth codes are deleted after use — PROVEN code regression, `8c55a82`

- `services/device-gateway/src/vendors/jt808/handlers/provisioning_port.py:219`:
  `record.auth_key_hashes.remove(matched_hash)` runs on every successful `0x0102`.
- **Spec §7.1.1:** *"未取得有效鉴权码的终端，应先发送终端注册消息"* — only a terminal *without* a
  valid code registers. *"终端应安全保存鉴权码"* — the terminal stores the code. §7.1.2/§7.1.3: on
  every reconnect it sends `0x0102` straight away. **The code is a long-lived credential, not a
  one-time token.**
- **Reproduced with the real classes:**

  ```
  0x0100 -> success
  0x0102 attempt 1 (same stored code) -> valid=True
  0x0102 attempt 2 (same stored code) -> valid=True    <- only because of the duplicate below
  0x0102 attempt 3 (same stored code) -> valid=False
  ```

  The 2nd attempt passes only by accident. The gateway reads back its own `DeviceAuthCodeIssued`
  from `raad:events` through its registry consumer, and `add_auth_key_hash` appends the same hash a
  second time (`device_registry_projection.py:95`, which doesn't deduplicate).
- `tests/test_projection_backed_jt808_provisioning_port.py:282`,
  `test_a_verified_code_cannot_be_replayed`, **tests for the spec-violating behaviour**, so the
  suite stays green.
- **Impact:** every reconnect after the 2nd fails with `authentication_failed` and the connection
  closes. Positions in that window are dropped (`position_report_dropped_unauthenticated`). The
  device recovers only if its firmware falls back to `0x0100`, and each recovery mints another code.
  The duplicates also halve the 8-slot buffer, so older codes get evicted sooner.

### A3. No GPS fix → no marker — PROVEN, intended behaviour change, `faedc85` (2026-09-13)

- Before 09-13, the JT808 adapter **never** wrote `vehicle:{id}:last` at all. The map moved only on
  `/ws/tracking` frames, and it drew any coordinate, including the unit's cached Shenzhen factory fix.
- After 09-13:
  - `is_gps_valid = status bit 1 AND plausible coordinate` (`position_body.py:77`, bit decoding
    checked and correct).
  - Invalid reports never write the snapshot (`redis_latest_position_writer.py`).
  - The frontend never moves `livePosition` for them (`useVehiclePosition.ts`) and shows "No Fix".
- **Indoor bench unit:** there's no marker and `GET /tracking/vehicles/{id}/latest` returns 404,
  which looks exactly like "Live Tracking broke". The pipeline is working; the device has no fix.
- **Check:** in `vehicle_positions` (D9), rows arriving with `is_gps_valid = false`. In the browser,
  WS frames with `"is_gps_valid": false`.

### A4. Redis full with `noeviction` — HYPOTHESIS, check D8

The local Redis has held `raad:events` since July and the stream is never trimmed (Known Issue #25).
Once `used_memory` reaches `maxmemory` (256 MB), every write fails:

- The `XADD DeviceAuthCodeIssued` before `0x8100` fails → `handler_error`, **no `0x8100` sent** →
  the device keeps re-registering.
- `SET device_session:*` before `0x8001` fails, so authentication can't complete.
- The snapshot `SET`s and the outbox relay fail.

The symptoms are the same as A2, so check memory before assuming a code cause.

### A5. Local video only — HYPOTHESIS

- `JT1078_RELAY_PUBLIC_INGEST_HOST=192.168.100.63` must still match the PC's current IP.
- Inbound 7910 needs its own Windows Firewall allow rule; the documented rule covers 7808 only.

### A6. Stale containers — check D1 locally

- The `dev` overlay bind-mounts source for `device-gateway`/`jt1078-relay`, but code changes only
  apply after `docker compose restart <service>`.
- Without the dev overlay, images must be rebuilt (`up -d --build`).
- `DEVICE_GATEWAY_REDIS_URL` (added 09-13) only takes effect after the gateway container is
  **recreated**.

---

## 5. Part B — The VPS: where it fails

### B0. What is already proven (EVIDENCED)

TCP 7808 reaches the container, `0x0100` parses, the terminal resolves (the registration result is
`success`), and the outbox → broker → registry chain works. **Don't start with the firewall or DNS
for GPS.** Start at the registration → authentication handoff (D5/D6).

### B1. The device doesn't continue after `0x8100` — EVIDENCED symptom; the causes below need D5 + D14

Candidate causes, and how D5/D14 separate them:

| Cause | What the pcap/logs will show |
|---|---|
| **a. Several MDVR slots point at the same server**, or the M3/multi-centre mode opens parallel links. Spec §7.5: *"终端可按配置向多个中心上报…并分别维护连接和在线状态"* | Two or more **simultaneous** TCP streams from the device IP; alternating `session_superseded`; each stream registers |
| **b. `0x8100` not sent** (Redis write failure before the reply, see A4) or not delivered | `registration_processed result=success` followed by `handler_error`, or no `81 00` frame leaving in the pcap |
| **c. The device rejects the `0x8100` format for the protocol mode set on Server 3** ("JT808-2019-**M3**" — the meaning of "M3" isn't documented anywhere in this repository or the supplier spec) | `81 00` leaves; the device answers with `FIN`/`RST` or a new `0x0100` instead of `01 02` on the same stream |
| **d. Retransmission and reconnect caused by unacknowledged `0x0200`** (finding 2) | The same `0x0200` serial number sent several times, then a new connection |
| **e. A mid-handler close** (process restart during a Coolify redeploy, or a supersede from a sibling stream) | `handler_cancelled` (since `04c176c`) or `connection_closing reason=server_shutdown/superseded` |

### B2. Auth-code regression

Same as A2. It hits the VPS harder: 4G links drop, NAT rebinding forces reconnects, and every Coolify
redeploy restarts the gateway.

### B3. `0x0200` and `0x0704` get no reply — PROVEN

- `location_handler.py:117,154` and `bulk_location_handler.py:74,109` return
  `HandlerResult.no_response()`.
- **Spec §7.8.1:** *"除消息定义明确标注无需应答外，发送方应等待通用应答或特定应答"*. §5.2.1 doesn't
  mark `0x0200` as no-reply (compare §5.1.3, where `0x0003` explicitly says *"该消息不需要应答"*).
- **Spec §3.5.3:** *"消息达到最大重传次数仍未收到有效应答时，按链路异常流程处理"*.
- On a LAN this may have been tolerated, or masked by frequent heartbeats. On 4G it's a
  standing cause of retransmissions, duplicate positions and reconnects.

### B4. RAAD is probably a secondary centre ("Server 3") — HYPOTHESIS, D14

- **Spec §3.4.1:** *"从平台：用于多中心数据汇聚。除项目另有书面约定外，终端仅响应主平台下发的业务指令"*.
- **Spec §7.5:** *"除书面约定外，终端仅执行主平台的下行指令；从平台下发的控制类消息应拒绝或忽略"*.
- **If Server 3 is a secondary centre:**
  - `0x9003` (camera discovery) is ignored or rejected → **no cameras**.
  - `0x9101`/`0x9201` (video) and `0x9101 data_type=2` (intercom) are ignored.
  - GPS can still flow.
  - **Result:** "GPS might appear, video and intercom never work."
- Logs: `device_command_result` with `reason=timed_out` or `terminal_rejected` for every downlink.

### B5. One-shot camera discovery — PROVEN

- `fleet_device/application/services.py:467-469` sets `av_attributes_requested_at` **before**
  anything is sent, and only when it was `NULL`.
- If that single `0x9003` was lost, you get no retry. Causes include: the device was a secondary
  centre (B4), the session was superseded or offline at that moment (B1/B2), or the command timed
  out.
- **Workaround after fixing B1–B4:** reset the column (D9) and make the device reconnect.

### B6. Video and intercom configuration on Coolify — PROVEN defaults

| Setting | Default in `docker-compose.coolify.full.yml` | Effect if it isn't set in Coolify | What it must be |
|---|---|---|---|
| `JT1078_RELAY_PUBLIC_INGEST_HOST` | `""` → `effective_public_ingest_host` = `0.0.0.0` (`jt1078/src/config.py:117,123`) | `0x9101` tells the MDVR to stream to `0.0.0.0`. The device acknowledges, then can't connect; the session fails after ~30 s | `187.7.22.79` |
| `JT1078_SIGNALING_URL` → `RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL` | `ws://localhost:7911` | `stream_url = ws://localhost:7911/viewer?token=…`. The browser tries **its own** localhost, and `ws://` from an `https://` page throws a SecurityError (mixed content) | `wss://<relay domain>`, e.g. `wss://video.raadsystems.tech` |
| Route to relay :7911 | none (`frontend.conf` only serves the SPA; nginx isn't running) | There's no HTTPS route to the viewer socket | A Coolify domain on service `jt1078-relay`, port **7911** |
| Firewall / hPanel for TCP **7910** | not managed by Coolify | The device can't open the media connection | Allow inbound TCP 7910 |
| `JT1078_RELAY_ENVIRONMENT` | `dev` | If set to `prod` with a secret shorter than 32 characters or a placeholder, the relay **refuses to start** (`d9a4c0b`) → the RPC times out | `prod` **plus** a ≥32-character secret |

Neither the backend nor the relay validates the first two values at startup (`settings.py`
`validate_on_startup` checks CORS, not the signaling URL). `docs/runbooks/coolify-deployment.md`
Step 3's variable table doesn't list any `JT1078_*` variable.

### B7. Frontend realtime on Coolify — check D11/D12

- **`VITE_WS_BASE_URL`** is a build argument with **no default** in the Coolify file. It must be
  `wss://api.raadsystems.tech`, the backend's domain, because `frontend.conf` doesn't proxy `/ws`.
  - Left empty: a modern browser resolves `/ws/tracking` against `app.raadsystems.tech`. The
    frontend container answers with `index.html` (the SPA fallback), the upgrade fails, and the
    client reconnects every 2 s forever.
  - Set to `ws://…`: the `WebSocket` constructor throws a SecurityError that nothing catches
    (`useWebSocket.ts:66`).
  - Changing it only takes effect after a **frontend rebuild**.
- **Close code 4402** (`SUBSCRIPTION_INACTIVE`) isn't treated as terminal
  (`useWebSocket.ts:86-88`). An organization without an active subscription reconnects every 2 s
  with no message on screen.
- **Mapbox:** the token is baked in at build time. If it has URL restrictions,
  `https://app.raadsystems.tech` must be allowed, or the map shows nothing even with data flowing.
- **Traefik (Coolify's proxy):** if WebSockets drop at exactly ~60 s, check the entrypoint's
  `respondingTimeouts.readTimeout` (Traefik v3 has a non-zero default). Not verified against this
  Coolify version; only act on it if D11 shows that pattern.

### B8. Terminal ID has to match exactly — PROVEN risk; it already happened

- `TerminalId` only checks for non-empty and ≤64 characters (`fleet_device/domain/value_objects.py:118`).
  The gateway compares strings exactly. The wire value for this unit is the 20-digit
  `00000000014482607571`.
- The VPS record was once entered as 21 digits (`a5b4bde`'s tests use exactly that value).
- **If the correction was a direct DB edit**, the registry projection still resolves the original
  value, because replay reuses the original `DeviceRegistered` payload. A later PATCH with the
  now-identical value is a **no-op** (`services.py:398`, `entities.py:468`): no event is emitted,
  and the projection stays wrong.
  - **Fix:** PATCH to a temporary value, then back.
  - **Or:** retire the device and re-register it.

### B9. Worker dependency

`raad-worker` carries all of these; it being unhealthy or lagging breaks each one:

- the outbox relay (device registration reaching the gateway)
- `devices.is_online` (the fleet map)
- `vehicle_positions` (history)
- camera discovery
- video session status

---

## 6. Part C — Code-level findings, regressions and fixes

### 6.1 Past changes that broke or weakened the pipeline

| Commit / change | What it broke | Label |
|---|---|---|
| `8c55a82` (09-15) — "keep multiple pending auth codes" | Added single-use consumption; breaks the persistent-credential rule in spec §7.1.1 | PROVEN regression |
| `faedc85` (09-13) — GPS fix-validity | Correct, but makes an indoor bench look dead (A3) | Behaviour change |
| ADR-0030 (2026-08-18) — `av_attributes_requested_at` guard | Turns one lost `0x9003` into permanently missing cameras (B5) | PROVEN design flaw |
| `bb00225` (08-27) — Redis session registry | Sessions survive gateway restarts. `LocationHandler` (`location_handler.py:103`) and `CommandSender` look sessions up **by terminal ID only**, never checking `connection_id`. After a restart, a stale session can accept positions from a connection that hasn't authenticated, and commands can target a dead connection ID. The monotonic timestamps also don't expire correctly after a host reboot | PROVEN (security and correctness) |
| `44c66fd` (09-04, B1/B14) — viewer route | Added only to nginx `dev.conf`/`prod*.conf`, which the Coolify path never runs (B6) | PROVEN deployment gap |
| `04c176c` (09-15) — observability | The new lines log at DEBUG, and `DEVICE_GATEWAY_LOG_LEVEL` isn't wired, so they're invisible in production (finding 8) | PROVEN |
| 2026-07-15 Phase 9.6 — location handler | `0x0200` never acknowledged (B3) | PROVEN latent spec violation |
| 2026-09-02 stream trimming (reverted) | Evicted the registry's founding events. The same failure class returns if Redis fills (A4) | Recorded, Known Issue #25 |

### 6.2 Fixes needed, in priority order

None of these are implemented yet. Each needs approval under `.claude/rules/workflow.md`.

**P0 — without these, a stable session isn't possible**

| ID | Where | Change | Tests |
|---|---|---|---|
| **C1** | `provisioning_port.py:204-225`, `device_registry_projection.py:95` | Stop removing the hash when a code verifies. Move it to most-recently-used so the 8-slot eviction drops the least-recently-used code. Make `add_auth_key_hash` skip a hash that's already stored (this removes the self-read duplicate). The protection comes from the code's 192 random bits and rotation on re-registration, not from consumption, which the spec doesn't allow | Replace `test_a_verified_code_cannot_be_replayed` with "the same code authenticates on N consecutive reconnects". Add "a self-published `DeviceAuthCodeIssued` doesn't duplicate the hash" |
| **C2** | `location_handler.py`, `bulk_location_handler.py` | Return `0x8001` (`build_general_response_body(serial, msg_id, RESULT_SUCCESS)`) after processing. For a report dropped as unauthenticated, return `RESULT_FAILURE` | Handler tests asserting `response_message_id == 0x8001` |
| **C3** | `fleet_device` `record_device_seen` + a `DeviceCommandResult` subscriber | Retry discovery: if the `0x9003` result is `timed_out`, `device_offline` or `terminal_rejected`, clear `av_attributes_requested_at`. Also run discovery whenever an online device has **zero cameras** | Unit tests for both paths |

**P1 — needed for video and intercom on the VPS, and for diagnosis**

| ID | Where | Change |
|---|---|---|
| **C4** | `docker/docker-compose.yml` → regenerate `.coolify.full.yml` (keep its 3 patches) | Add `DEVICE_GATEWAY_LOG_LEVEL: ${DEVICE_GATEWAY_LOG_LEVEL:-INFO}` to `device-gateway`. Log `response_frame_sent` for `0x8100`, and for `0x8001` replying to `0x0102`, at INFO |
| **C5** | Backend `Settings.validate_on_startup`; relay `RelayConfig.validate_on_startup` | In prod, refuse a `jt1078_signaling_url` that contains `localhost`/`127.0.0.1` or starts with `ws://`. Refuse an empty `JT1078_RELAY_PUBLIC_INGEST_HOST`, `0.0.0.0`, or an RFC 1918 address |
| **C6** | Coolify UI + `docs/runbooks/coolify-deployment.md` Step 3/4b | A domain for `jt1078-relay:7911`; `JT1078_SIGNALING_URL=wss://…`; `JT1078_RELAY_PUBLIC_INGEST_HOST=187.7.22.79`; `JT1078_RELAY_ENVIRONMENT=prod` plus a real secret; firewall 7910. Add all of them to the runbook table |
| **C7** | `frontend/src/shared/hooks/useWebSocket.ts` | Treat 4402 as terminal and show a message. Wrap `new WebSocket()` in try/catch and show the error instead of throwing |
| **C8** | `location_handler.py`, `bulk_location_handler.py`, `av_attributes_handler.py`, `resource_list_handler.py` | Accept a message only if `session.connection_id == context.connection_id`. Clear `device_session:*` at gateway start (single node) or store wall-clock timestamps |

**P2 — hardening**

| ID | Change |
|---|---|
| **C9** | Validate the JT808 terminal ID format at registration and edit (20 decimal digits for 2019 devices), with a UI hint. Add an admin "resync device to gateway" action that re-emits the registry event |
| **C10** | Raise `REDIS_MAXMEMORY` on the VPS now (for example 1–2 GB, sized to RAM). Schedule the registry-persistence redesign so `raad:events` can be trimmed (Known Issue #25) |
| **C11** | Realtime fan-out: batch size 10 per ~1 s tick caps `/ws/tracking` at ~10 events/s across **all** event types. Raise the batch size before fleets grow |
| **C12** | Stale comments: `device-gateway.Dockerfile:33` says 7808 is "dormant" (it's the live adapter); `.coolify.full.yml` note 2 about the frontend healthcheck is outdated |

---

## 7. Part D — Diagnostic procedure (Coolify / VPS)

Run on the VPS as root, over SSH or the Coolify server terminal. Every command is read-only unless
it says otherwise. Container names are the compose `container_name`s. If Coolify renamed them,
list them first with `docker ps --format '{{.Names}}'` and substitute.

Set these once:

```bash
TERM_ID=00000000014482607571
API=https://api.raadsystems.tech        # replace with the backend's actual Coolify domain
rc() { docker exec raad-redis sh -c "redis-cli -a \"\$REDIS_PASSWORD\" --no-auth-warning $*"; }
pg() { docker exec raad-postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -P pager=off -c \"$*\""; }
```

### D1. Containers, restarts, deployed code

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep raad-
for c in raad-device-gateway raad-jt1078-relay raad-backend raad-worker raad-redis raad-postgres raad-frontend; do
  printf '%-22s restarts=%s started=%s health=%s\n' "$c" \
    "$(docker inspect -f '{{.RestartCount}}' $c)" "$(docker inspect -f '{{.State.StartedAt}}' $c)" \
    "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' $c)"
done
# Which device-gateway code is actually running (1 = present):
docker exec raad-device-gateway sh -c 'grep -c auth_key_hashes.remove /app/src/vendors/jt808/handlers/provisioning_port.py; grep -c _apply_terminal_id_changed /app/src/registry/device_registry_projection.py; grep -c response_frame_sent /app/src/vendors/jt808/dispatcher/dispatcher.py'
docker logs --tail 50 raad-jt1078-relay 2>&1 | grep -iE 'refusing|error|relay_started'
```

**Pass:** every service `Up`, restart counts not climbing, relay logs `relay_started`. The first
`grep` returning `1` means the C1 regression is deployed.

### D2. Effective configuration inside the containers (secrets not printed)

```bash
docker exec raad-device-gateway sh -c 'echo broker_db=${DEVICE_GATEWAY_BROKER_URL##*/} cache_db=${DEVICE_GATEWAY_REDIS_URL##*/} log_level=${DEVICE_GATEWAY_LOG_LEVEL:-unset}'
docker exec raad-backend sh -c 'echo env=$RAAD_ENVIRONMENT broker_db=${RAAD_BROKER__URL##*/} cache_db=${RAAD_REDIS__URL##*/} signaling=$RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL'
docker exec raad-worker  sh -c 'echo broker_db=${RAAD_BROKER__URL##*/} signaling=$RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL'
docker exec raad-jt1078-relay sh -c 'echo public_ingest_host=[$JT1078_RELAY_PUBLIC_INGEST_HOST] env=$JT1078_RELAY_ENVIRONMENT secret_len=${#JT1078_RELAY_VIEWER_TOKEN_SECRET} max_org=$JT1078_RELAY_MAX_SESSIONS_PER_ORGANIZATION'
# URLs baked into the frontend bundle at build time:
docker exec raad-frontend sh -c "grep -ohE '(wss?|https?)://[A-Za-z0-9.:-]+' /usr/share/nginx/html/assets/*.js | sort | uniq -c | sort -rn | head"
```

**Pass:**

- Both broker DBs are `1`; both cache DBs are `0`.
- `signaling` starts with `wss://` and isn't localhost.
- `public_ingest_host=[187.7.22.79]`.
- The bundle contains `https://api.…` **and** `wss://api.…`, with no `ws://localhost`.

### D3. Host port exposure and firewall

```bash
ss -ltnp | grep -E ':(7808|7809|7910|7911)\b'
docker port raad-device-gateway; docker port raad-jt1078-relay
iptables -t nat -S DOCKER | grep -E 'dport (7808|7910|7911)'
ufw status verbose     # Docker-published ports bypass ufw INPUT rules; the Hostinger hPanel firewall does not
```

Also check Hostinger hPanel → VPS → **Firewall**. If it's enabled, it must allow inbound TCP
**7808** and **7910**. Allow 7911 only if you deliberately expose the viewer without Traefik; the
recommended setup routes it over 443.

### D4. External reachability, from a machine off the VPS network (e.g. a laptop on a phone hotspot)

```bash
nc -vz -w 5 187.7.22.79 7808
nc -vz -w 5 187.7.22.79 7910
```

In PowerShell: `Test-NetConnection 187.7.22.79 -Port 7808` (and `-Port 7910`).

Then on the VPS:

```bash
docker logs --since 5m raad-device-gateway 2>&1 | grep connection_accepted
```

It should show **your** IP. `7910` has no log line for a bare probe; the check is that the TCP
connect itself succeeds.

### D5. Packet capture of the MDVR session (the most important step)

```bash
timeout 900 tcpdump -ni any -s0 -w /root/mdvr-$(date +%Y%m%d%H%M).pcap 'tcp port 7808 or tcp port 7910' &
# Power-cycle the MDVR (or wait for a reconnect), then after ~10 minutes:
tcpdump -nr /root/mdvr-*.pcap 'tcp[tcpflags] & (tcp-syn|tcp-fin|tcp-rst) != 0'     # connection lifecycle
tcpdump -nr /root/mdvr-*.pcap -X 'tcp port 7808 and (tcp[tcpflags] & tcp-push != 0)' | less
```

**How to read a JT/T 808-2019 frame:**
`7e | msg-id(2) | props(2) | version(1) | terminal BCD(10) | serial(2) | body | checksum | 7e`.
The first two bytes after `7e` are the message ID:

| Bytes | Message |
|---|---|
| `01 00` | register |
| `81 00` | register response |
| `01 02` | authenticate |
| `80 01` | general response |
| `00 02` | heartbeat |
| `02 00` | location |
| `91 01` | live video command |
| `00 01` | terminal ack |
| `90 03` / `10 03` | A/V attribute query / report |

**Questions to answer from the capture:**

1. How many **simultaneous** TCP streams come from the MDVR IP? More than one means B1a/B4: fix
   the slots in D14.
2. On each stream, after `81 00` goes out, does the **same stream** carry `01 02`? If it gets a FIN
   or RST instead, or a new stream sends `01 00` again, that's B1c (tell the vendor which mode is set).
3. Does every `01 02` get `80 01`, and with which result byte (the last body byte: `00` = OK,
   `01` = fail)?
4. Is the same `02 00` serial repeated? Then the device is retransmitting unacknowledged reports (B3).
5. After a `91 01`, does a SYN to **7910** arrive from the MDVR? If not: secondary centre (B4),
   wrong `server_ip` (B6), or the firewall.

### D6. Device-gateway logs: the connection timeline

```bash
docker logs --since 2h raad-device-gateway 2>&1 | grep -E '"message": "(connection_accepted|message_parsed|registration_processed|authentication_succeeded|authentication_failed|device_authenticated|session_superseded|device_online|device_offline|position_report_dropped_unauthenticated|handler_error|handler_cancelled|response_frame_send_failed|connection_idle_timeout|connection_closing|frame_parse_error|unknown_message_dispatched|device_registry_replay_completed|device_registry_poll_failed|video_signaling_poll_failed|command_acknowledged|device_command_result|av_attributes_dropped_unauthenticated)"' > /root/gw.log
# Timeline for one connection:
CID=$(grep registration_processed /root/gw.log | tail -1 | grep -oE '"connection_id": "[^"]+"' | cut -d'"' -f4)
grep "$CID" /root/gw.log
# Message mix per terminal:
grep '"message": "message_parsed"' /root/gw.log | grep -oE '"message_id": "0x[0-9a-f]+"' | sort | uniq -c
```

| Pattern | Meaning | Go to |
|---|---|---|
| `registration_processed result=terminal_not_found` | The terminal ID doesn't match the registry, or the device isn't activated or assigned | D7, D9, B8 |
| `registration_processed result=success`, then `handler_error` | The Redis write failed before `0x8100` | D8 (memory) |
| `result=success`, then `connection_closing reason=peer_disconnected` with no `0x0102` | The device didn't accept or receive `0x8100` | D5, B1c, D14 |
| `authentication_failed` on connections that didn't register first | Consumed or evicted code | C1 |
| `session_superseded` alternating between two connection IDs | Two device links for one terminal | D14 |
| `connection_closing reason=idle_timeout` | Heartbeat interval ≥ 90 s | D14 (heartbeat parameter) |
| `device_command_result reason=timed_out/terminal_rejected` for `0x9003`/`0x9101` | Secondary centre or device busy | B4, D14 |
| `device_command_result reason=device_offline` | No session when the command was sent | B1, B2 |
| **`device_position_reported`**, `device_online` from logger `events` | **No broker configured**: events go to the log only | D2 |

For DEBUG detail you must first add `DEVICE_GATEWAY_LOG_LEVEL` to the compose file (C4). Setting it
in Coolify alone does nothing.

### D7. Registry projection state

```bash
docker logs raad-device-gateway 2>&1 | grep device_registry_replay_completed | tail -3        # events_applied must be > 0
DEV_ID=<devices.id from D9>
rc -n 1 XRANGE raad:events - + | grep -E "$DEV_ID|$TERM_ID" | grep -oE 'Device[A-Za-z]+' | sort | uniq -c
```

**Pass:** `DeviceRegistered` ≥ 1, `DeviceActivated` ≥ 1, `DeviceAssignedToVehicle` ≥ 1, with no
later `DeviceSuspended`/`DeviceRetired`/`DeviceUnassignedFromVehicle`. If `DeviceRegistered` carries
a different terminal ID than the device sends, see B8.

### D8. Redis: memory, stream, groups, sessions, snapshot

```bash
rc INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'
rc -n 1 XLEN raad:events
rc -n 1 XINFO GROUPS raad:events          # per group: pending and lag should stay near 0
rc -n 1 GET device_session:$TERM_ID       # connection_id, state ONLINE/AUTHENTICATED
rc -n 1 SMEMBERS device_session:index
rc -n 0 GET vehicle:<VEHICLE_ID>:last     # present only once a valid fix has arrived
rc -n 1 LLEN raad:jt1078:session_requests # should be 0 (relay consuming)
rc -n 1 XREVRANGE raad:events + - COUNT 500 | grep -oE 'Device[A-Za-z]+|Jt1078[A-Za-z]+|VideoSession[A-Za-z]+' | sort | uniq -c
```

**Groups to find:** `device-gateway-registry`, `device-gateway-video-commands`, `ws-tracking`,
`ws-notifications`, `notification-worker`. A large or growing `lag` means that consumer is behind or
dead. **Stop and fix memory first if `used_memory` is near `maxmemory`.**

### D9. PostgreSQL

```bash
pg "select id, organization_id, terminal_id, length(terminal_id) as len, lifecycle_state, is_online, last_seen_at, av_attributes_requested_at, auth_key_hash is not null as has_hash from devices where deleted_at is null order by updated_at desc limit 10;"
pg "select d.terminal_id, a.vehicle_id, a.assigned_at from device_assignments a join devices d on d.id = a.device_id where a.unassigned_at is null;"
pg "select device_id, channel_no from cameras order by device_id, channel_no;"
pg "select vehicle_id, event_time, latitude, longitude, is_gps_valid from vehicle_positions order by event_time desc limit 10;"
pg "select event_type, count(*), min(created_at) from outbox where published_at is null group by 1 order by 2 desc;"
pg "select id, purpose, status, created_at, started_at, ended_at from video_sessions order by created_at desc limit 10;"
```

**Pass:**

- `len = 20`, lifecycle `assigned`, one active assignment.
- `last_seen_at` is recent and `is_online` is true while the bus is on.
- `cameras` has rows.
- `vehicle_positions` is moving, with some `is_gps_valid = true`.
- The outbox has no old unpublished rows.

**Camera discovery reset (a write — only after D14 and C1/C2 are fixed):**

```bash
pg "update devices set av_attributes_requested_at = null where terminal_id = '$TERM_ID';"
```

Then power-cycle the MDVR. The next `DeviceOnline` sends `0x9003`.

### D10. Worker

```bash
docker logs --since 1h raad-worker 2>&1 | grep -iE 'outbox|DevicePositionReported|DeviceOnline|dead_letter|error' | tail -40
```

### D11. Browser (Chrome DevTools → Network → WS, on the Live Tracking page)

- **`/ws/tracking` request URL** must be `wss://api.…/ws/tracking`. Status must be **101**.
  - Status 200 means you hit the frontend container: wrong `VITE_WS_BASE_URL`.
- **Messages:** outgoing `{"type":"auth"…}` then `{"type":"subscribe","channel":"vehicle","vehicle_id":…}`.
  Incoming `{"type":"position"…}` should arrive at the device's report interval.
- **Close codes:**

  | Code | Meaning |
  |---|---|
  | 4401 | Token invalid or expired |
  | 4402 | Organization subscription inactive |
  | 4403 | Not allowed to see this vehicle |
  | 4400 | Subscribe failed server-side (check backend logs) |
  | 1006 at ~60 s | Proxy timeout (B7 Traefik note) |

- **Console:** a "Mixed Content" or `SecurityError: … insecure WebSocket` error means a `ws://` URL
  was used from HTTPS.
- **Mapbox:** 401/403 on `api.mapbox.com` means a token or URL-restriction problem.

### D12. Command-line API checks

Copy an access token from DevTools: the `Authorization` header of any `/api/v1` request.

```bash
TOKEN='<access token>'; VEH=<vehicle id>
curl -s $API/health/ready
curl -s -H "Authorization: Bearer $TOKEN" $API/api/v1/vehicles/$VEH/device-assignment
curl -s -H "Authorization: Bearer $TOKEN" $API/api/v1/tracking/vehicles/$VEH/latest
curl -s -H "Authorization: Bearer $TOKEN" $API/api/v1/tracking/vehicles/online
curl --http1.1 -si -N --max-time 5 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
     -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' $API/ws/tracking | head -3                 # expect HTTP/1.1 101
curl --http1.1 -si -N --max-time 5 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
     -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' 'https://<relay domain>/viewer?token=x' | head -3   # expect 101, proves the Traefik route to 7911
```

For a full WS test with `websocat`: `websocat wss://api.…/ws/tracking`, then paste the auth and
subscribe frames from D11.

### D13. Video end to end (only after D6 shows a stable session and D9 shows cameras)

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"device_id":"<DEVICE_ID>","camera_id":"<CAMERA_ID>"}' $API/api/v1/video/live      # check stream_url host and scheme
docker logs --since 5m raad-device-gateway 2>&1 | grep -E 'command_acknowledged|device_command_result'
docker logs --since 5m raad-jt1078-relay   2>&1 | grep -E 'session_event|ingest_connection_accepted|ingest_connection_correlated|unsolicited_ingest_connection_rejected|viewer_connected'
timeout 60 tcpdump -ni any 'tcp port 7910 and tcp[tcpflags] & tcp-syn != 0'             # MDVR SYN within ~2 s of 0x9101
```

**Expected sequence:** `0x9101` acknowledged (result 0) → a SYN from the MDVR to 7910 →
`ingest_connection_correlated` → `viewer_connected` → `video_sessions.status = active`.

### D14. MDVR configuration (on the device menu or the vendor tool)

Record every server slot: enabled, IP, port, protocol mode, and main or secondary role.

1. **Exactly one** enabled slot → `187.7.22.79:7808`, and it must be the **main** centre (Server 1
   on most units). Disable any other slot that points at the same host.
2. Protocol mode: record exactly what "JT808-2019-M3" is and ask the vendor what "M3" changes.
   Prefer the plain JT/T 808-2019 mode that matches the working bench configuration.
3. Terminal phone / device ID = `00000000014482607571`.
4. Heartbeat interval (parameter `0x0001`) ≤ 60 s. The gateway closes a connection idle for 90 s
   and expires a session after 120 s.
5. TCP response timeout and retry count (parameters `0x0002`/`0x0003`).
6. GPS antenna connected; outdoors, the status shows a fix.
7. APN and data working; signal strength.
8. After changing slots, power-cycle. If the device keeps presenting an old code, clear or reset its
   registration so it sends `0x0100`.

### D15. Decision tree

```
No connection_accepted from the MDVR IP ─▶ D14 slot/IP/APN, D3 hPanel firewall
Connected, registration_processed terminal_not_found ─▶ D7/D9 terminal ID, lifecycle, assignment; B8
Registration success, no 0x0102 on the same stream ─▶ D5 (multiple streams? FIN after 81 00?) ─▶ D14; D8 memory
0x0102 → authentication_failed ─▶ C1 (deploy the fix), D14 duplicate slots
Authenticated but repeated reconnects ─▶ D5 repeated 02 00 serials (C2), idle_timeout (heartbeat), superseded (slots)
Positions flowing, no map marker ─▶ is_gps_valid=false (antenna/indoor); D11 WS URL, close codes, Mapbox
Map works, no cameras ─▶ D6 0x9003 result ─▶ D14 main centre ─▶ D9 reset av_attributes_requested_at
Cameras, video fails ─▶ D2 signaling URL and ingest host ─▶ D12 relay route ─▶ D3/D4 port 7910 ─▶ D13
```

### D16. Localhost checks (Windows dev PC)

Run in PowerShell from the repo root.

```powershell
docker compose -f docker/docker-compose.yml ps
ipconfig | Select-String IPv4                     # must equal the MDVR slot IP and JT1078_RELAY_PUBLIC_INGEST_HOST
Get-NetFirewallRule -DisplayName "*7808*","*7910*" | Select DisplayName,Enabled,Profile,Direction,Action
docker logs --since 30m raad-device-gateway 2>&1 | Select-String connection_accepted
docker exec raad-redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning INFO memory' | Select-String "used_memory_human|maxmemory_human"
```

If no non-loopback `connection_accepted` appears, the MDVR isn't dialing this PC (A1). To test
locally again, pick **one**:

- **Back on the LAN or AP:** put the MDVR back on the bench Wi-Fi or LAN, with the **main** slot
  pointed at the PC's current LAN IP. Allow 7808 and 7910 inbound on the Private profile.
- **Stay on 4G:** give the PC a public route (router port-forward 7808/7910 plus the public IP in
  the slot and in `JT1078_RELAY_PUBLIC_INGEST_HOST`).

Don't run the local stack and the VPS as main and secondary centres for the same unit at the same
time. Each platform mints its own auth codes, and only the main centre can command video.

---

## 8. Recommended order of work

1. **Device (no code):** D14. One enabled slot, the main centre, pointed at `187.7.22.79:7808`.
   Heartbeat ≤ 60 s.
2. **Collect evidence:** D1–D8, plus a 10-minute D5 capture across a power-cycle.
3. **Code:** C1 (auth-code persistence), C2 (`0x0200`/`0x0704` acknowledgements), C4 (log-level
   wiring). Redeploy `device-gateway`.
4. **Verify GPS:**
   1. D6 shows register → authenticate → heartbeat → location on one connection, staying up past
      several heartbeat intervals.
   2. D9 `is_online` / `vehicle_positions`, and D8 snapshot.
   3. D11 WS position frames.
5. **Video prerequisites:** C6 (relay domain, `JT1078_SIGNALING_URL`,
   `JT1078_RELAY_PUBLIC_INGEST_HOST`, relay env/secret, firewall 7910). Redeploy relay, backend,
   worker.
6. **Cameras:** C3, or the D9 reset plus a power-cycle. Confirm `cameras` rows.
7. **Video, then intercom:** D13.
8. **Hardening:** C5, C7, C8, C10 (Redis memory now), C9, C11, C12.
