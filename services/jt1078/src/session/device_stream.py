"""`DeviceStream` — one media transmission the terminal is actually running (ADR-0046 §2).

A JT/T 1078 terminal keeps one live transmission per logical channel, and `0x9102` names only the
channel: it has no notion of which platform request a stream belongs to. So the unit the relay
must own is the *device stream*, not the viewer's session. Several sessions (viewers, possibly of
different users) attach to one live stream; the terminal is told to start when the first one
arrives and to stop only when the last one has gone.

Key: `(terminal, logical channel, kind)`. Live A/V and two-way intercom on the same channel are
separate streams with separate connections (observed on the bench and in production), so kind is
part of the key. A playback stream replays one session's own time window and is never shared, so
its key also carries that session's id.

`generation` counts starts. Every device command a stream issues is stamped with the generation it
belongs to, and a stop is always queued before the next generation's start (ADR-0046 §3), which is
what makes "a late stop kills a newer start" impossible rather than merely unlikely.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from src.session.video_session import StreamType, VideoSessionKind


class DeviceStreamState(str, Enum):
    #: The current generation's start has been queued (or is waiting for the channel's start
    #: slot); no frame of this generation has arrived yet.
    STARTING = "starting"
    #: At least one frame of the current generation has arrived.
    ACTIVE = "active"


@dataclass(frozen=True)
class StreamKey:
    terminal_id: str
    logical_channel: int
    kind: VideoSessionKind
    #: Only set for exclusive (playback) streams.
    exclusive_to: str | None = None

    @property
    def channel(self) -> tuple[str, int]:
        return (self.terminal_id, self.logical_channel)


def new_stream_id() -> str:
    return uuid.uuid4().hex


@dataclass
class DeviceStream:
    stream_id: str
    key: StreamKey
    stream_type: StreamType
    #: `False` only for a stream opened by a Business API that still publishes `0x9101` itself
    #: (rolling-deploy compatibility, ADR-0046 §3): the relay then never starts or restarts it,
    #: and only signals its stop, exactly as before this ADR.
    relay_signals_device: bool
    device_id: str | None = None
    vehicle_id: str | None = None
    organization_id: str | None = None
    audio_codec: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    generation: int = 0
    state: DeviceStreamState = DeviceStreamState.STARTING
    #: Waiting for the channel's start slot (another stream on this channel is waiting for its
    #: media connection) - the start has not been queued yet.
    start_pending: bool = False
    start_requested_at: float | None = None
    #: The current generation has not received its media connection yet.
    awaiting_connection: bool = True
    open_connections: int = 0
    last_frame_at: float | None = None
    session_ids: set[str] = field(default_factory=set)
    released_at: float | None = None
    downgrade_requested_at: float | None = None
    created_at: float = field(default_factory=time.monotonic)

    @property
    def terminal_id(self) -> str:
        return self.key.terminal_id

    @property
    def logical_channel(self) -> int:
        return self.key.logical_channel

    @property
    def kind(self) -> VideoSessionKind:
        return self.key.kind

    @property
    def is_shareable(self) -> bool:
        return self.key.exclusive_to is None

    def command_correlation_id(self, *, suffix: str = "") -> str:
        return f"{self.stream_id}-g{self.generation}{suffix}"
