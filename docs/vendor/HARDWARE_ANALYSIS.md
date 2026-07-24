# Vendor Hardware Analysis — MDVR (Shenzhen Tianyou Security Technology / "LSZ")

**Status:** Analysis only. No implementation code has been written against this document.
**Purpose:** Per `.claude/rules/documentation.md` #1, this document traces every claim below to a
specific source file in `mdvrdocs/`. Nothing here is inferred beyond what those documents state.
Where a capability is plausible but undocumented, it is explicitly marked **Not documented** rather
than assumed.

## Source documents

| File | Language | Scope |
|---|---|---|
| `mdvrdocs/mdvr网络通信协议V0.00.30_150103 - 英文.doc` | English | Primary protocol reference, v0.00.30, 124 pages, 26,933 words. Full command catalogue. |
| `mdvrdocs/mdvr网络通信协议V29.doc` | Chinese | Earlier/parallel edition (v29, 88 pages) of the same protocol family. Used here only to corroborate the primary reference — same command keywords (`$$dc`, `V101`, `V102`, `V103`, `V105`...), same framing. |
| `mdvrdocs/mdvr网络通信协议补充文档180904.docx` | Chinese | "Supplementary document based on real packet-capture analysis of v0.00.30_150608" — worked examples for registration, heartbeat, position report, video start/stop, custom alarm, alarm file upload/download, media registration, file-block download, and a full annotated "start video" / "alarm file upload" instruction-flow trace. |
| `mdvrdocs/GPS数据获取.docx` ("GPS Data Retrieval") | Chinese | Describes **the vendor's CMS (Center Monitor System) server software**, not the terminal itself: a Web Service (HTTP+JSON), a Windows SDK, a Windows ActiveX/COM control, direct database table access, and a CMS-initiated push channel to a third-party server. |
| `mdvrdocs/Usaamayuusuf Cabdullahi P.I.pdf` | — | Proforma Invoice, Shenzhen Tianyou Security Technology Co., Ltd, PI No. LSZ-2026, dated 2026-07. Confirms exact procured SKU and bundled accessories. |

---

## 1. Hardware overview

**Vendor:** Shenzhen Tianyou Security Technology Co., Ltd (brand: **LSZ**). Factory in Longhua
District, Shenzhen, Guangdong, China. Contact: Holston, `holston@bestmdvr.com`.

**Procured unit (per the Proforma Invoice):**

| Item | Model | Description |
|---|---|---|
| MDVR head unit | **LSZ-C5804DG-Q-F** | H.265 multi-stream, **4-channel** real-time 1080P recording, optional VGA. DC8-36V low-power input, full electrical protection, 12V/3A peripheral output. **Dual 512G SD card** storage, up to 24h power-off delayed recording. Auto/manual/alarm recording modes. 4 alarm inputs, 1 alarm output. Overlays vehicle data; connects fuel/OBD/temperature sensors. |
| Camera | A908CX | AHD 1920×1080P, 2.0 Megapixel |
| Microphone | AJ208C1 | 2" metal-type, audio optional |
| Two-way communication module | LSZ-M01 | Cabin↔center voice intercom hardware |
| Extension cables | LSZ-10M / LSZ-5M | 10m/5m vehicle aviation-connector extension cables |
| Storage | 256G SD card | Additional/spare SD card |

The device type field in the wire protocol itself (§9, "Commands") encodes channel count generically
(4 or 8 channels, `Hi3512`/`Hi3515` SoC family) — the procured SKU is the 4-channel variant.

**MDVR** = Mobile Digital Video Recorder. **CMS** = Center Monitor System (the vendor's own
central-monitoring server software that terminates the device protocol described below).

---

## 2. Supported protocols

**This is the single most important finding in this analysis, and it must be stated without
hedging: nothing in any of the five source documents mentions JT/T 808, JT/T 1078, or any other
named Chinese national telematics standard, by name or by wire format.**

What the documents describe instead is a **proprietary vendor protocol**, referred to in the
documents only as "mdvr网络通信协议" ("MDVR Network Communication Protocol"), current version
`0.00.30` (English reference doc) / `V29` (Chinese corroborating doc). Its defining characteristics,
directly contradicting a JT808/JT1078 assumption:

- **Framing is ASCII/CSV, not binary TLV.** Control commands are plain ASCII: `$$dc<length>,<seq>,
  <keyword>,<serial>,<workstation>,<time>,...#` — comma-separated fields terminated by `#`. JT/T 808
  is a binary protocol with `0x7e` frame delimiters, byte-stuffing/escaping, a fixed 12-byte header,
  and an XOR checksum.
- **Command identity is an ASCII keyword, not a 2-byte message ID.** Commands are named `V101`,
  `V102`, `C100`, `C508`, etc. (`V` = device-originated "vehicle", `C` = center-originated) — not
  JT/T 808's `0x0100`/`0x0200`/`0x8100`-style numeric message IDs.
- **Timestamps are ASCII `YYMMDD HHMMSS`**, not JT/T 808's 6-byte BCD encoding.
- **GPS position is ASCII degrees/minutes/seconds integers** (position report V114/V101), not JT/T
  808's signed 32-bit 1/10⁶-degree binary fields.
- **Sessions are identified by a GUID/UUID string** (`382c74c3-721d-4f34-80e5-57657b6cbc27`), a
  concept JT/T 808 does not have at all.
- **Media (video/audio) frames use a distinct `@@$$dc<4-byte-length>...####` binary envelope**
  carrying vendor-defined opcodes (`0x6000`, `0x6002`, `0x6011`, `0x6012`, `0x6013`, `0x6015`,
  `0x6102`, `0x6403` — confirmed against real captured frames in the supplementary document). This
  is not JT/T 1078's PS/RTP-style media packet format.

Confirmation this is a genuine mismatch, not a documentation gap on RAAD's side: `services/jt808/`
in this repository already implements the **real** JT/T 808-2013 standard (binary header parsing,
`0x7e` escaping, XOR checksum, BCD terminal-phone decoding, message IDs `0x0100`/`0x0102`/`0x0200`/
`0x0704`/etc. — see `services/jt808/README.md`'s own Phase 9.1–9.6 status). None of that parser
would recognize a single byte this vendor's hardware actually sends.

**No JT808 features and no JT1078 features are documented for this hardware** — see the next two
sections, which record that finding rather than fabricate a feature list to fill the expected
headings.

---

## 3. JT808 features

**Not documented. This hardware does not implement JT/T 808**, per §2 above. There is no
registration/authentication handshake matching JT/T 808 §8.5/§8.6, no `0x0200` location message, no
`0x8100`/`0x8001` general-response scheme, and no terminal-parameter (`0x8103`) or text-command
(`0x8300`) mechanism described anywhere in the source documents. The vendor's own equivalents to
"registration," "heartbeat," and "position report" are covered under §9 (Commands) and §10 (Device
registration) below, using the vendor's actual proprietary mechanism — they are named here only to
avoid a reader assuming JT/T 808 terminology applies.

---

## 4. JT1078 features

**Not documented. This hardware does not implement JT/T 1078**, per §2 above. There is no PS
(Program Stream) framing, no RTP/RTCP, and no JT/T 1078-defined logical-channel/media-type byte
layout anywhere in the source documents. The vendor's actual live-video/playback mechanism is its
own binary media-channel protocol — see §6 (Video capabilities) and §9 (Commands).

---

## 5. GPS capabilities

Position data ships embedded in two places: the recurring **"location and status"** field group
(used by registration `V101`, position report `V114`, and as a prefix on every alarm message), and
a separately-formatted field pair inside the (vendor-flagged **"unrealized"**, i.e. not implemented
in firmware) geofence alarm.

- **Fix validity:** `A` = GPS data reliable, `V` = unreliable (insufficient satellites). The flag is
  followed by a digit count of tracked satellites (e.g. `A0010` = valid fix, 10 satellites).
- **Longitude/latitude (position report path):** three ASCII integers each — degrees, minutes,
  seconds×1000 — sign indicates hemisphere (e.g. `114,3,341826000` = 114°03′341.826″ — note the
  source document's own worked examples keep the seconds field in an unusual ×1000 scale distinct
  from a clean arc-second value; taken verbatim from the spec, not normalized here).
- **Longitude/latitude (geofence alarm path):** a **different** encoding — six-decimal-place
  floating-point degrees strings (`ddd.dddddd`) — e.g. `113.483942,22.398012`. **This is an internal
  inconsistency in the vendor's own specification**, not a RAAD assumption: two different messages
  in the same protocol encode geographic coordinates two different ways.
- **Ground speed:** integer km/h (position report), or a 2-decimal float string in some alarm
  payloads (e.g. speed alarm's `130.80`).
- **Heading:** integer degrees, 0–360, clockwise from true north.
- **Mileage (odometer):** integer, scaled — `22963924` = 22,963.924 km.
- **Fuel level:** integer, scaled — `9999` = 99.99 liters (via connected analog fuel sensor).
- **Temperature sensors:** three channels (device/engine/cabin), 2-decimal float strings, °C.
- **Parking duration:** integer seconds, valid only while the vehicle is stationary.
- **32-bit "component status and alarm" bitmask** (2 groups × 32 bits), covering: GPS fix valid,
  ACC on/off, left/right turn signal, brake, forward/reverse gear, GPS antenna present, primary/
  secondary hard-disk present or powered-off, cellular signal bars (0–5), stationary flag, speeding
  flag, backfill/buffered-data flag, daily/monthly data-quota-reached/exceeded flags, 8 digital
  alarm inputs (IO1–IO8), plus a second, separate 32-bit word for geofence/entry-exit,
  in/out-of-zone speeding, in/out-of-zone parking, daily/monthly traffic warnings, power-failure/
  battery-backup, door-open, vehicle-armed, low-battery, bad-battery, and engine-related bits.
- **Reporting cadence:** position report (`V114`) carries a "drive flag" indicating why it was sent
  (0 = center-requested live poll, 1 = fixed periodic upload, 2 = center-requested current-position
  poll, 3 = sent to stay in sync with an active video stream). **The actual periodic interval/report
  frequency is not documented** in the excerpted sections — no configuration command for it was
  found.
- **Not documented:** raw NMEA sentence access, differential/RTK correction, IMU/dead-reckoning
  fusion, or a query/set command for GPS report interval.

A companion document (`GPS数据获取.docx`) separately describes how the vendor's own **CMS server
software** (not the terminal) re-exposes this same position data via a Web Service (JSON), a
Windows SDK, an ActiveX control, a direct database table (`dev_status`), and a CMS-initiated push
to a third-party ("OA") server using a distinct binary struct (`OAPacketHead_S` + `GPSVehicleState_S`,
its own bit-packed GPS time and status-word layout, again **not** JT/T 808's). See §14 (Limitations)
and the companion Integration Plan for why this matters architecturally.

---

## 6. Video capabilities

- **4 channels** (procured SKU) of H.265, "multi-stream" (main + sub stream selectable per-request
  via a `stream type` field: `0` = main, `1` = sub).
- **Resolution:** 1080P real-time recording (per PI); camera supplied is 1920×1080P 2.0MP (AHD).
- **Recording modes:** auto, manual, and alarm-triggered (per PI); "type of file" on upload/search
  distinguishes `TYPE_NORMAL` (regular) vs `TYPE_ALARM` (alarm-triggered) recordings.
- **Live streaming mechanism:** a dedicated **media channel** (separate TCP connection from the
  signaling channel), opened on demand: center sends `C508` (start/stop video upload) on the
  signaling channel → device opens a new media-channel connection and sends `V102` (media
  registration) → center replies with binary opcode `0x6000` (media registration ack) → center may
  request `0x6002` (request I-frame) → device streams `0x6011` (I-frame), `0x6012` (P-frame),
  `0x6013` (A-frame/audio) → center periodically sends `0x6403` (receive report/ack). This entire
  exchange is proprietary; there is no JT/T 1078 PS/RTP framing anywhere in it.
- **Playback/download of recorded files:** `C701` (search video files by time range/type/channel)
  → `C702` (request download, with byte-offset or time-offset resume support) → device opens a
  media channel with `V103` (download-file media registration) → file bytes stream via opcode
  `0x6102`.
- **Snapshot/still image capture:** `V107` (device-initiated, requests a media channel; supports
  BMP/JPEG/GIF, resumable by byte offset).
- **Alarm-triggered auto image/video upload:** device pre-announces via `V298` ("about to upload
  alarm image", center must explicitly permit/deny), then uploads via `V232` (alarm file upload,
  full metadata: file type, path, size, start time, duration, channel).
- **Virtual "full-channel" composite view:** channel number `99` is a reserved value meaning a
  single split-screen composite of every physical channel; `98` means "all channels" (used only for
  the "stop" direction of `C508`).
- **Two-way voice intercom:** `C550`/`C551` (center-initiated talk/listen) and `V130`
  (device-initiated call request, center must explicitly allow/reject) — audio codec selectable
  among G.711A, G.711U, several G.726 bitrates, and ADPCM.
- **Channel exclusivity (architectural constraint, stated explicitly in the vendor doc):** live
  video, file download, remote upgrade, and playback are **mutually exclusive on a given device** —
  starting one interrupts/replaces another already in progress on the same media channel.
- **Not documented:** RTSP, HLS, WebRTC, or any standards-based streaming output from the device
  itself — the device only ever speaks its own opcode-framed binary media protocol to the vendor's
  own CMS server.

---

## 7. AI capabilities

**Not documented.** None of the five source documents mention AI, ADAS (Advanced Driver
Assistance), DSM (Driver State/Fatigue Monitoring via computer vision), lane-departure detection,
collision warning, or any camera-based analytics, anywhere. The protocol does define a **"fatigue
alarm"** wire message (`V219`/`V269`, carrying only an integer "alarm level" 0–4) — but per
CLAUDE.md's own instruction not to assume undocumented hardware capability, **the existence of this
alarm message must not be read as confirmation of camera-based/AI-driven fatigue detection**. No
document states what triggers it (a driver-facing camera with vision AI, a physical
steering-pattern sensor, a simple continuous-driving timer, or something else entirely). This is
flagged as an open question for the vendor, not resolved by inference.

---

## 8. Alarm types

The protocol's own alarm-type enumeration appears verbatim inside the `V299` ("device released
alarm notification", itself marked **"(unrealized)"** in the source document) message:

| # | Alarm | Wire keyword(s) (start/end) | Notes |
|---|---|---|---|
| 0 | *(meta)* All alarms | — | Used only as a filter value in `V299`, not a real alarm. |
| 1 | Custom alarm | `V201` / `V251` | Vendor/integrator-defined; carries a "custom alarm number" 1–255. |
| 2 | Emergency button (panic) alarm | (button-press payload) | |
| 3 | Vibration alarm | | Likely accelerometer-based; sensor type not detailed. |
| 4 | Camera no-signal alarm | | Per-channel 16-bit bitmask of which channel(s) lost signal. |
| 5 | Camera tampering alarm | | Per-channel bitmask, same shape as #4. |
| 6 | Illegal door alarm | | |
| 7 | Three-password-error alarm | | Referenced only in the enumeration; no detail section captured. |
| 8 | Illegal ignition alarm | | Referenced only in the enumeration; no detail section captured. |
| 9 | Temperature alarm | `V209` / `V259` | Device/engine/cabin, with configured low/high thresholds echoed in the payload. |
| 10 | Hard disk error alarm | `V210` / `V260` | Disk number + 4-byte hex error code + free-text description. |
| 11 | Speed alarm | `V211` / `V261` | Trigger speed + configured min/max + duration echoed in payload. |
| 12 | Cross-border (geofence) alarm | `V212` / `V262` | **Explicitly marked "(unrealized)" in the vendor document** — not implemented in firmware. |
| 13 | Abnormal door switch alarm | `V213` / `V263` | Per-door bitmask (front/rear); duration in seconds. |

**Additional alarms exist in the document body but are absent from the `V299` enumeration table
above — a real internal inconsistency in the vendor's own spec, not a RAAD omission:**

| Alarm | Wire keyword(s) | Notes |
|---|---|---|
| ACC on | `V214` | No payload fields. |
| ACC off | `V215` | No payload fields. |
| Parking-too-long alarm | `V216` / `V266` | Elapsed parking duration + configured threshold. |
| Motion detection alarm | `V217` (end variant implied, not captured) | Per-channel bitmask, up to 16 channels. |
| GPS failure alarm | `V218` / `V268` | No payload fields. |
| Fatigue-driving alarm | `V219` / `V269` | Integer alarm level 0–4 (see §7 — detection method undocumented). |
| Fuel-increase alarm | `V304` | Before/after fuel level (refueling detection). |
| Fuel-decrease alarm | `V305` | Before/after fuel level (siphoning/leak detection). |
| UPS/power-cut alarm | `V220` | No payload fields — backup-battery cutover. |
| Hard-disk over-temperature alarm | `V221` / `V271` | Disk number, disk type, temperature. |
| Front-panel forced-open alarm | `V222` | No payload fields — physical tamper. |

**Alarm semantics (documented explicitly):** each alarm carries an "Alarm UID" that stays constant
across repeated transmissions of the *same* ongoing alarm condition (device retransmits every 10s
for up to 10 minutes if unacknowledged) — a new UID means a genuinely new alarm event, not a
repeat. Distinguish this from an "alarm **flag**" (a sustained bit in the 32-bit status word, cleared
only when the alarm condition is resolved), which is a different concept from the transient
"alarm **trigger**" instruction.

---

## 9. Commands

Full confirmed command catalogue (keyword → direction → purpose). `V*` = device→center, `C*` =
center→device, unless noted. This list only includes commands with a captured protocol-format
line in the source documents — it is not asserted to be exhaustive of every command the firmware
supports.

| Keyword | Direction | Purpose |
|---|---|---|
| `V100` | Device → Center | Generic device response/ack carrying a fresh position+status snapshot |
| `V101` | Device → Center | Signaling-channel device registration |
| `V102` | Device → Center | Media-channel registration (live video/audio streaming) |
| `V103` | Device → Center | Media-channel registration (file-block download) |
| `V105` | Device → Center | Media-channel registration (voice — referenced, detail not fully captured) |
| `V106` | Device → Center | Media-channel registration (remote firmware upgrade package transfer) |
| `V107` | Device → Center | Media-channel registration (snapshot/still-image capture) |
| `V109` | Device → Center | Heartbeat (also reused, confusingly, as the keyword for "profile"/config-file media registration in one section — flagged as a documentation ambiguity, not resolved by inference) |
| `V114` | Device → Center | Position report |
| `V130` | Device → Center | Device-initiated voice call request |
| `V141` | Device → Center | Device requests the list of files available for download |
| `V201` / `V251` | Device → Center | Custom alarm start / end |
| `V208`–`V222` | Device → Center | Alarm family — see §8 |
| `V231` | Device → Center | Transparent (passthrough) data upload |
| `V232` | Device → Center | Alarm file (image/video) upload |
| `V234` | Device → Center | "Upload file download complete" notice |
| `V298` | Device → Center | Pre-announce alarm-image upload (center must permit/deny) |
| `V299` | Device → Center | Device-initiated "alarm released/disarmed" notice |
| `V304` / `V305` | Device → Center | Fuel increase / decrease alarm |
| `C100` | Center → Device | Generic success/failure ack for a `V*` command |
| `C500` | Center → Device | "Device not registered" — forces device to re-run registration |
| `C501` | Center → Device | Center heartbeat (sent every 6s per the documented remark) |
| `C508` | Center → Device | Start/stop video upload on a channel |
| `C520` / `C521` | Center → Device | Push / pull a configuration ("profile") file, MD5-verified |
| `C550` / `C551` | Center → Device | Center-initiated talk / listen (voice intercom) |
| `C588` | Center → Device | Query full device status (see §10) |
| `C589` | Center → Device | Restore factory settings — **marked "(unrealized)"** |
| `C701` | Center → Device | Search recorded video files (time range, type, channel) |
| `C702` | Center → Device | Request file download (full or byte/time-offset resume) |
| `0x6000` | Center → Device | Media registration acknowledgment (binary media-channel opcode) |
| `0x6002` | Center → Device | Request I-frame (binary media-channel opcode) |
| `0x6011` / `0x6012` / `0x6013` | Device → Center | I-frame / P-frame / A-frame media data (binary) |
| `0x6015` | Device → Center | Media capability/parameter block (binary; exact field layout not specified, only shown as a captured example) |
| `0x6102` | Device ↔ Center | File-download data block (binary) |
| `0x6403` | Center → Device | Media receive report/ack (binary) |

The binary media opcodes (`0x60xx`/`0x64xx` family) are demonstrated only via captured real-traffic
examples in the supplementary document — their exact field-level layout is **not formally specified
in prose** anywhere in the two main protocol documents. This is a real documentation gap in the
vendor's own material, not a RAAD-introduced one.

---

## 10. Device registration

Registration (`V101`, signaling channel) is per-device, keyed by a **"vehicle device serial
number"**: ≤20 characters, letters/digits/underscore/space only, cannot be blank/whitespace-only,
and **must already exist in the center's own vehicle database** — an unrecognized serial number is
rejected (`C100` failure, reason code 2) and the socket is closed by the center. The same field is
echoed on every subsequent command as the device's identity. Registration also carries: protocol
version string, a device-type integer (channel count + SoC family), the *device's own configured*
signaling-server IP/port, today's power-on count, connection count since last power-on, license
plate (optional, Unicode, ≤32 chars), network type (3G/WIFI/wired/4G), WIFI SSID (if applicable),
audio codec, storage type (SD/HDD/SSD), manufacturer type/device-type codes, IMEI (optional), host
firmware version string (optional), network-library version string (optional).

Media-channel registration (`V102`/`V103`/`V106`/`V107`, etc.) is a **separate** registration on a
**separate** TCP connection per session, correlated to the signaling channel by a session GUID.

---

## 11. Authentication

**No cryptographic authentication mechanism of any kind is documented.** Registration validity is
decided purely by whether the submitted "vehicle device serial number" string is already present in
the center's own database — there is no shared secret, no challenge/response, no signed token, no
per-device key, and no mention of TLS/DTLS anywhere in any of the four protocol-related source
documents. A device (or anything impersonating one, knowing or guessing a valid serial number) can
register and submit data. This is a material, explicitly-flagged security gap relative to this
codebase's own `.claude/rules/jt808.md` #5 ("unknown/unauthenticated devices are rejected and
audited") and `.claude/rules/security.md` #9 ("device auth keys" as a named compensating control) —
see the companion Integration Plan document for how this must be addressed before production use.

---

## 12. Provisioning

Provisioning is entirely **center-side and out-of-band**: an operator must manually enter a
device's serial number (and, implicitly, its association to a vehicle/license plate) into the
center's own vehicle database *before* the physical device can ever successfully register — there
is no self-provisioning flow, no QR-code/activation-code enrollment, and no documented API for a
third-party system to programmatically provision a new device into the center's database. The
`GPS数据获取.docx` document's SDK/Web-Service/ActiveX interfaces are all **read**-oriented (querying
existing device status); none of them describe a provisioning/write path either.

---

## 13. Firmware / OTA

Two distinct, unrelated update mechanisms are documented:

1. **Firmware/"upgrade package" transfer (`V106`):** center-initiated. Device opens a media channel,
   registers with `V106` (carrying the target filename and a resume byte-offset), then the upgrade
   package streams over the media channel using the same binary opcode family as video. Resume is
   whole-file-offset only (not chunked/segmented). **No version check, no rollback, no staged/canary
   rollout, and no cryptographic signature verification are documented** — integrity is via the
   generic media-channel transfer only; no MD5/hash field is present on the `V106` registration
   itself (unlike the configuration-file push below, which does carry one).
2. **Configuration ("profile") file push/pull (`C520`/`C521`):** a separate mechanism for pushing or
   pulling a device configuration file, MD5-verified end-to-end, with distinct success codes for
   "file received," "file validated," and "configuration applied" as separate stages.

Both mechanisms are **center-initiated only** — no "check for update" pull command from the device
is documented.

---

## 14. Camera channels

Channel count is fixed by hardware SKU, encoded in the registration "device type" field (4 or 8
channels; the procured `LSZ-C5804DG-Q-F` is 4-channel). Channels are addressed 0–15 in most fields
(0 = channel 1, etc.), with two reserved values: `99` = virtual full-channel split-screen composite,
`98` = "all channels" (stop-video context only). Alarm bitmasks for camera-no-signal/tampering/
motion-detection support up to 16 channels regardless of the specific unit's physical channel count.
Stream type (main/sub) is selectable per live-video or media request, independent of channel number.

---

## 15. Storage

Storage type is a generic protocol field (`1` = SD card, `2` = HDD, `3` = SSD) — the procured unit
uses **dual 512G SD cards** (per the Proforma Invoice) with "up to 24h power-off delayed recording."
The device-status query (`C588`) reports per-disk capacity/free-space (e.g. `16023_8034` =
160.23GB total / 80.34GB free) and can enumerate multiple disks (pipe-separated serial-number list),
confirming the protocol itself is written generically across SD/HDD/SSD-based DVR SKUs even though
this specific procured unit is SD-card-only. No document describes a retention/overwrite policy,
partitioning scheme, or a command to configure retention — these are presumed on-device firmware
behavior, not exposed over the wire.

---

## 16. SIM management

**No SIM/ICCID/IMSI/APN lifecycle management is documented anywhere.** The only cellular-related
data the protocol exposes is read-only telemetry via the device-status query (`C588`): 3G/4G
connection status, network type/quality, current IP, and **cumulative KB-traffic counters "since
invoice date"** for 3G and 4G separately (implying the vendor's own back-office bills against a data
plan by billing cycle, though no document describes how that cycle/invoice date is configured). SIM
provisioning, swap, or carrier-account management is entirely outside what this protocol surface
exposes — RAAD would need to manage SIM lifecycle through the carrier/vendor directly, out of band.

---

## 17. Limitations (summary — see inline flags above for detail)

1. **Not JT/T 808 or JT/T 1078 compliant** — a wholly separate, proprietary ASCII/binary hybrid
   protocol. This is the central finding of this document (§2).
2. **No device-plane authentication or encryption** — registration trust is allow-list-by-serial-
   number only; all commands (and media) travel in plaintext.
3. **Internally inconsistent GPS coordinate encoding** across message types (integer D°M′S″ vs.
   decimal-degree float strings) — a genuine spec defect, not a RAAD assumption.
4. **No documented AI/ADAS/DSM capability** — a "fatigue alarm" wire message exists, but its
   detection mechanism is undocumented and must not be assumed to be camera/AI-based.
5. **Geofence ("cross-border") alarm is explicitly marked "(unrealized)"** in the vendor's own
   document — not implemented in firmware as shipped.
6. Several other messages (`V298`, `V299`, `C589` factory reset) are likewise marked
   **"(unrealized)"**.
7. **No firmware version-check, rollback, staged rollout, or cryptographic signing** for OTA; only
   an MD5 hash on the separate configuration-file-push path.
8. **No documented GPS report-interval or alarm-threshold configuration command** — thresholds are
   only ever *echoed back* inside each alarm's own payload, with no visible "set" command captured.
9. Channel count is fixed per hardware SKU (procured unit: 4 channels).
10. **Video streaming, file playback/download, and firmware upgrade are mutually exclusive** on a
    single device's media channel — explicitly documented as an intentional bandwidth/complexity
    tradeoff, not an oversight.
11. The binary media opcode family (`0x60xx`/`0x64xx`) is demonstrated only via worked examples,
    never formally specified field-by-field, in either main protocol document.
12. A **separate, higher-level integration surface exists via the vendor's own CMS server software**
    (Web Service/SDK/ActiveX/DB/OA-push, per `GPS数据获取.docx`) — this is not the device protocol,
    sits upstream of it, and appears designed for a single self-hosted, Windows-oriented CMS
    instance rather than a multi-tenant cloud platform. See the companion Integration Plan document
    for the architectural implications of this second surface.
13. No document in `mdvrdocs/` describes a hosted/cloud/multi-tenant deployment model for the CMS
    server at all — every integration point assumes one CMS instance, one client system.
