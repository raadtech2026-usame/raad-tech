# Skill: JT1078 Review

## Purpose
Validate changes to the JT1078 video server against the video-privacy invariant and the
non-archival design principle.

## Workflow
1. Confirm the Parent role still has zero reachable path to a media session or viewer token after
   the change — treat any regression here as a blocking finding, not a style note.
2. Confirm no video is persisted by this service; only ephemeral Redis state and Business-DB control
   metadata (`video_sessions`, `playback_requests`) are written.
3. Confirm device signaling still originates from the Business API via JT808 downlink, not from this
   service directly.
4. Confirm concurrency ceilings (per-org and global) are still enforced and ports are reclaimed on
   teardown.
5. Confirm session open/close events are still emitted for audit purposes.

## When to use
Before merging any change to `services/jt1078/`.
