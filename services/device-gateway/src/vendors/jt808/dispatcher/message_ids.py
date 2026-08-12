"""Named message-ID constants for the handlers this phase registers — exactly the set JT808
Technical Design §7's dispatch flowchart and §8's handler table name, each cross-checked
directly against the primary JT/T 808-2013 spec's own section for that message ID: §8.1
terminal general response, §8.3 heartbeat (终端心跳), §8.5 registration (终端注册), §8.7
logout (终端注销), §8.8 authentication (终端鉴权), §8.18 location report (位置信息汇报,
`0x0200`), §8.52 multimedia data upload (多媒体数据上传, `0x0801` — matches §7's flowchart
"0x0801/alarm bits -> AlarmHandler" exactly). `BULK_LOCATION_REPORT` (`0x0704`) is JT808
Technical Design §8/§10's named backfill/buffered-position message.

**JT/T 1078 video-signaling message IDs (ADR-0024 §1/§6/§7/§8, ADR-0025 §5) — added for the
device-gateway video-signaling-forwarding phase.** Per the confirmed supplier spec
(`mdvrdocs/MDVR-808-1078-spec.pdf` §6), these reuse the exact same JT/T 808 envelope this file's
other constants already use — no second protocol stack, no new message-ID range handling.
Live/control/status-notify/resource-query/playback-request/playback-control are all
platform-→-terminal (downlink, forwarded verbatim by `commands/command_sender.py`); the resource
list report is terminal-→-platform (uplink, routed to `handlers/resource_list_handler.py`, a real
handler, not a placeholder).

Not an exhaustive list of every message ID either document mentions — only the ones named as
having a *dispatcher-routed handler* in JT808 Technical Design §7/§8, plus the JT/T 1078 video
set above. Any other message ID (there are many more in the full JT/T 808-2013 standard, e.g.
parameter query/set, terminal control) falls through to `UnknownMessageHandler` until a later
phase's approved design adds it here.
"""

from __future__ import annotations

TERMINAL_GENERAL_RESPONSE = (
    0x0001  # §8.1 / §5.1.1 — routed to CommandAckHandler, a real handler (not a placeholder)
)
HEARTBEAT = 0x0002  # §8.3
LOGOUT = 0x0003  # §8.7
REGISTRATION = 0x0100  # §8.5
AUTHENTICATION = 0x0102  # §8.8
LOCATION_REPORT = 0x0200  # §8.18
BULK_LOCATION_REPORT = 0x0704  # backfill/buffered positions
MULTIMEDIA_EVENT_UPLOAD = (
    0x0801  # §8.52 — §7's flowchart: "0x0801/alarm bits -> AlarmHandler"
)

# JT/T 1078 video signaling (spec §6.2/§6.3) — platform -> terminal (downlink), forwarded as-is.
LIVE_VIDEO_REQUEST = 0x9101  # §6.2.1 — real-time A/V transmission request
LIVE_VIDEO_CONTROL = 0x9102  # §6.2.2 — switch stream / pause / resume / close
LIVE_VIDEO_STATUS_NOTIFY = 0x9105  # §6.2.3 — periodic packet-loss-rate notify
PLAYBACK_REQUEST = 0x9201  # §6.3.3 — remote recording playback request
PLAYBACK_CONTROL = 0x9202  # §6.3.4 — playback start/pause/stop/seek control
QUERY_RESOURCE_LIST = 0x9205  # §6.3.1 — query the terminal's own recording resource list

# JT/T 1078 video signaling — terminal -> platform (uplink), a real handler.
RESOURCE_LIST_REPORT = 0x1205  # §6.3.2 — the terminal's reply to QUERY_RESOURCE_LIST
