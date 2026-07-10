# JT1078 Video Server

On-demand live video and playback relay for bus MDVR cameras. RAAD is not a cloud video archive —
the MDVR remains the system of record; this service relays streams only when live monitoring or
playback is explicitly requested by an Organization Administrator. **Parents never receive live
video** (platform-wide invariant).

Source of truth: `docs/business/RAAD_Phase3.5_JT1078_Technical_Design_v1.md` and
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §5.2.

**Language/runtime for this service is not yet decided by approved documentation.** Do not assume a
stack; confirm before scaffolding build tooling.

## Structure (logical components — see `.claude/rules/jt1078.md`)

```
src/
├── session/      # Video Session Manager (VSM): allocate, bind_media, issue_viewer,
│                 # stop, enforce_limits (per-org / global concurrency ceilings)
├── ingest/       # Media Ingest — accepts the JT1078 media stream from the MDVR
├── repackager/   # Repackager/Transcoder -> WebRTC (primary) / HLS / FLV (fallback)
└── viewer/       # Viewer Edge — token-gated delivery to authorized web clients
```

## Key rules

- Authorization happens in the Business API **before** any signaling — the Parent role has no code
  path that can allocate a media session or receive a stream token.
- This service persists **no video**. Only ephemeral session/port/token state lives in Redis; control
  metadata (`video_sessions`, `playback_requests`) lives in the Business API's database.
- Signaling to the physical device happens via JT808 command downlink, issued by the Business API —
  this service only receives the resulting media stream.

See `.claude/rules/jt1078.md` and `.claude/rules/security.md`.

## Status

Structural scaffold only. No session management, ingest, or repackaging logic is implemented yet.
