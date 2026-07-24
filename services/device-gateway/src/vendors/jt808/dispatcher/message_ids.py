"""Named message-ID constants for the handlers this phase registers — exactly the set JT808
Technical Design §7's dispatch flowchart and §8's handler table name, each cross-checked
directly against the primary JT/T 808-2013 spec's own section for that message ID: §8.1
terminal general response, §8.3 heartbeat (终端心跳), §8.5 registration (终端注册), §8.7
logout (终端注销), §8.8 authentication (终端鉴权), §8.18 location report (位置信息汇报,
`0x0200`), §8.52 multimedia data upload (多媒体数据上传, `0x0801` — matches §7's flowchart
"0x0801/alarm bits -> AlarmHandler" exactly). `BULK_LOCATION_REPORT` (`0x0704`) is JT808
Technical Design §8/§10's named backfill/buffered-position message.

Not an exhaustive list of every message ID either document mentions — only the ones named as
having a *dispatcher-routed handler* in JT808 Technical Design §7/§8. Any other message ID
(there are many more in the full JT/T 808-2013 standard, e.g. parameter query/set, terminal
control) falls through to `UnknownMessageHandler` until a later phase's approved design adds
it here.
"""

from __future__ import annotations

TERMINAL_GENERAL_RESPONSE = (
    0x0001  # §8.1 — routed to CommandAckHandler per §7's flowchart
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
