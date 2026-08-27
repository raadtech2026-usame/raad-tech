"""Unit tests for `modules.fleet_device.events.subscribers` (`docs/architecture/
post-f7-production-readiness-roadmap.md` Phase A item A3, ADR-0030). Stdlib `unittest` - no
`pytest`. Mirrors `test_tracking_subscribers.py`'s convention: fakes bound directly into a real
`core.di.container.Container`, keyed by the real types `DeviceConnectivityProcessor` resolves.

Covers: `DeviceOnline`/`DeviceOffline` both call `record_device_seen` with `event.occurred_at`
(not a payload field - neither event's payload carries a timestamp) and `SYSTEM_PRINCIPAL`; a
missing/`None` `device_id` in the payload is dropped, not passed through as `None`; ADR-0030's
automatic-discovery trigger (publishing `Jt1078SignalCommandRequested`/`query_av_attributes`
only when `record_device_seen` signals it should, and only when a broker is actually configured);
and `DeviceAvAttributesReportedProcessor`'s camera-creation loop.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.errors.exceptions import ConflictError
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.modules.fleet_device.application.commands import (
    RecordAudioCapabilityCommand,
    RecordDeviceSeenCommand,
    RegisterCameraCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.fleet_device.domain.value_objects import AudioCapability, CameraPosition
from raad.modules.fleet_device.events.subscribers import (
    SYSTEM_PRINCIPAL,
    DeviceAvAttributesReportedProcessor,
    DeviceConnectivityProcessor,
)

_OCCURRED_AT = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


class _FakeUnitOfWork:
    """`Container.resolve` is a plain type-keyed lookup with no `isinstance` enforcement (see
    `test_tracking_subscribers.py`'s identical precedent) - the fake service below never
    actually uses `uow`."""


class _RecordingBroker:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class _RecordingDeviceApplicationService:
    def __init__(self, *, discover_terminal_id: str | None = None) -> None:
        self.recorded: list[RecordDeviceSeenCommand] = []
        self.registered_cameras: list[RegisterCameraCommand] = []
        self.recorded_audio_capabilities: list[RecordAudioCapabilityCommand] = []
        self._discover_terminal_id = discover_terminal_id
        #: channel numbers to reject with ConflictError (simulates "already registered")
        self.conflicting_channels: set[int] = set()

    async def record_device_seen(
        self, command: RecordDeviceSeenCommand, *, uow
    ) -> str | None:
        self.recorded.append(command)
        return self._discover_terminal_id

    async def register_camera(self, command: RegisterCameraCommand, *, uow) -> None:
        if command.channel_no in self.conflicting_channels:
            raise ConflictError(f"channel {command.channel_no} already registered")
        self.registered_cameras.append(command)

    async def record_audio_capability(
        self, command: RecordAudioCapabilityCommand, *, uow
    ) -> None:
        self.recorded_audio_capabilities.append(command)


def _make_event(
    *, event_type: str, payload: dict, occurred_at: datetime = _OCCURRED_AT
) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=payload.get("organization_id"),
        correlation_id=None,
        payload=payload,
        aggregate_type="Device",
        aggregate_id="00007",
    )


class DeviceConnectivityProcessorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = Container()
        self.service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, self.service)
        self.container.bind_singleton(FleetDeviceUnitOfWork, _FakeUnitOfWork())

    async def test_device_online_records_seen_with_event_occurred_at(self) -> None:
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)
        event = _make_event(
            event_type="DeviceOnline",
            payload={
                "organization_id": "org-1",
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "terminal_id": "00007",
            },
        )

        await processor.process(event)

        self.assertEqual(len(self.service.recorded), 1)
        command = self.service.recorded[0]
        self.assertEqual(command.device_id, "device-1")
        self.assertEqual(command.seen_at, _OCCURRED_AT)
        self.assertTrue(command.is_online)
        self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_device_offline_also_records_seen(self) -> None:
        """A `DeviceOffline` still records the timestamp `devices.last_seen_at` should carry -
        "when was this device last seen" is true regardless of which direction the transition
        went (see this processor's own class docstring)."""
        processor = DeviceConnectivityProcessor("DeviceOffline", self.container)
        event = _make_event(
            event_type="DeviceOffline",
            payload={
                "organization_id": "org-1",
                "vehicle_id": "vehicle-1",
                "device_id": "device-1",
                "terminal_id": "00007",
                "reason": "session_expired",
            },
        )

        await processor.process(event)

        self.assertEqual(len(self.service.recorded), 1)
        self.assertEqual(self.service.recorded[0].device_id, "device-1")
        # ADR-0020 §3: DeviceOffline must record is_online=False, not just a timestamp.
        self.assertFalse(self.service.recorded[0].is_online)

    async def test_missing_device_id_is_dropped_not_passed_through(self) -> None:
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)
        event = _make_event(
            event_type="DeviceOnline",
            payload={
                "organization_id": None,
                "vehicle_id": None,
                "device_id": None,
                "terminal_id": "00007",
            },
        )

        await processor.process(event)

        self.assertEqual(self.service.recorded, [])

    async def test_event_type_matches_the_constructor_argument(self) -> None:
        online = DeviceConnectivityProcessor("DeviceOnline", self.container)
        offline = DeviceConnectivityProcessor("DeviceOffline", self.container)
        self.assertEqual(online.event_type, "DeviceOnline")
        self.assertEqual(offline.event_type, "DeviceOffline")


class DeviceConnectivityProcessorAvAttributesDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0030 — the "when" half of automatic channel discovery: publishing
    `Jt1078SignalCommandRequested`/`query_av_attributes` exactly when `record_device_seen`
    signals it should (the idempotency guard itself lives inside that service method, already
    covered by its own unit tests; this processor only decides whether to *act* on the signal)."""

    def setUp(self) -> None:
        self.container = Container()
        self.uow = _FakeUnitOfWork()
        self.container.bind_singleton(FleetDeviceUnitOfWork, self.uow)

    async def test_publishes_query_av_attributes_when_service_signals_first_online(
        self,
    ) -> None:
        service = _RecordingDeviceApplicationService(discover_terminal_id="00007")
        self.container.bind_singleton(DeviceApplicationService, service)
        broker = _RecordingBroker()
        self.container.bind_singleton(BrokerPort, broker)
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceOnline",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id=None,
            payload={"device_id": "device-1"},
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(len(broker.published), 1)
        published = broker.published[0]
        self.assertEqual(published.event_type, "Jt1078SignalCommandRequested")
        self.assertEqual(published.payload["terminal_id"], "00007")
        self.assertEqual(published.payload["command"], "query_av_attributes")
        self.assertEqual(published.payload["fields"], {})

    async def test_does_not_publish_when_service_signals_nothing(self) -> None:
        # e.g. DeviceOffline, or a device that already had discovery requested.
        service = _RecordingDeviceApplicationService(discover_terminal_id=None)
        self.container.bind_singleton(DeviceApplicationService, service)
        broker = _RecordingBroker()
        self.container.bind_singleton(BrokerPort, broker)
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceOnline",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id=None,
            payload={"device_id": "device-1"},
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(broker.published, [])

    async def test_no_broker_configured_does_not_raise(self) -> None:
        # `try_resolve` returns None when BrokerPort is unbound — a dev/test environment with
        # no broker still processes connectivity correctly, it just can't request discovery.
        service = _RecordingDeviceApplicationService(discover_terminal_id="00007")
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceConnectivityProcessor("DeviceOnline", self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceOnline",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id=None,
            payload={"device_id": "device-1"},
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)  # must not raise


class DeviceAvAttributesReportedProcessorTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0030 — the "create Camera records for every discovered channel" half. Channel
    numbers are derived from `max_video_channels` alone (`1..N`), never enumerated by the
    terminal itself — see `services/device-gateway/src/vendors/jt808/commands/
    av_attributes.py`'s own docstring for why."""

    def setUp(self) -> None:
        self.container = Container()
        self.container.bind_singleton(FleetDeviceUnitOfWork, _FakeUnitOfWork())

    async def test_registers_one_camera_per_discovered_channel_starting_at_one(self) -> None:
        service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceAvAttributesReported",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id="corr-1",
            payload={"device_id": "device-1", "max_video_channels": 4},
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(len(service.registered_cameras), 4)
        self.assertEqual(
            [c.channel_no for c in service.registered_cameras], [1, 2, 3, 4]
        )
        for command in service.registered_cameras:
            self.assertEqual(command.device_id, "device-1")
            self.assertEqual(command.position, CameraPosition.OTHER)
            self.assertEqual(command.label, f"Channel {command.channel_no}")
            self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_a_channel_already_registered_is_skipped_not_raised(self) -> None:
        # Idempotency on a replayed/duplicate 0x1003 report — ConflictError from the
        # ux_cameras__device_channel invariant is expected, not an error to propagate.
        service = _RecordingDeviceApplicationService()
        service.conflicting_channels = {2}
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceAvAttributesReported",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id="corr-1",
            payload={"device_id": "device-1", "max_video_channels": 3},
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)  # must not raise

        self.assertEqual(
            [c.channel_no for c in service.registered_cameras], [1, 3]
        )

    async def test_missing_device_id_or_channel_count_is_dropped(self) -> None:
        service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        for payload in ({"max_video_channels": 4}, {"device_id": "device-1"}):
            event = DomainEvent(
                event_id="evt-1",
                event_type="DeviceAvAttributesReported",
                version=1,
                occurred_at=_OCCURRED_AT,
                org_id="org-1",
                correlation_id="corr-1",
                payload=payload,
                aggregate_type="Device",
                aggregate_id="00007",
            )
            await processor.process(event)

        self.assertEqual(service.registered_cameras, [])


_FULL_AUDIO_PAYLOAD = {
    "device_id": "device-1",
    "max_video_channels": 1,
    "input_audio_codec": 6,
    "input_audio_channels": 1,
    "input_audio_sample_rate": 3,
    "input_audio_sample_bits": 1,
    "audio_frame_length": 320,
    "supports_audio_output": True,
    "video_codec": 2,
}


class DeviceAvAttributesReportedProcessorAudioCaptureTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0033 — the second, independent half of `DeviceAvAttributesReportedProcessor`:
    recording the terminal's own real audio capability, alongside the pre-existing
    camera-discovery loop these tests don't otherwise touch."""

    def setUp(self) -> None:
        self.container = Container()
        self.container.bind_singleton(FleetDeviceUnitOfWork, _FakeUnitOfWork())

    async def test_records_audio_capability_when_all_fields_present(self) -> None:
        service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceAvAttributesReported",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id="corr-1",
            payload=dict(_FULL_AUDIO_PAYLOAD),
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(len(service.recorded_audio_capabilities), 1)
        command = service.recorded_audio_capabilities[0]
        self.assertEqual(command.device_id, "device-1")
        self.assertEqual(
            command.audio_capability,
            AudioCapability(
                codec=6,
                channels=1,
                sample_rate=3,
                sample_bits=1,
                frame_length=320,
                supports_output=True,
                video_codec=2,
            ),
        )
        self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_falsy_but_present_fields_are_not_treated_as_missing(self) -> None:
        """`0` is a valid codec/sample/byte value and `False` is a valid
        `supports_audio_output` - the check must use `is not None`, not truthiness."""
        service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        payload = dict(_FULL_AUDIO_PAYLOAD)
        payload.update(
            {
                "input_audio_codec": 0,
                "input_audio_channels": 0,
                "supports_audio_output": False,
                "video_codec": 0,
            }
        )
        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceAvAttributesReported",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id="corr-1",
            payload=payload,
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(len(service.recorded_audio_capabilities), 1)
        capability = service.recorded_audio_capabilities[0].audio_capability
        self.assertEqual(capability.codec, 0)
        self.assertEqual(capability.channels, 0)
        self.assertFalse(capability.supports_output)
        self.assertEqual(capability.video_codec, 0)

    async def test_missing_audio_field_skips_audio_capture_not_camera_discovery(self) -> None:
        service = _RecordingDeviceApplicationService()
        self.container.bind_singleton(DeviceApplicationService, service)
        processor = DeviceAvAttributesReportedProcessor(self.container)

        payload = {"device_id": "device-1", "max_video_channels": 2}  # no audio fields at all
        event = DomainEvent(
            event_id="evt-1",
            event_type="DeviceAvAttributesReported",
            version=1,
            occurred_at=_OCCURRED_AT,
            org_id="org-1",
            correlation_id="corr-1",
            payload=payload,
            aggregate_type="Device",
            aggregate_id="00007",
        )
        await processor.process(event)

        self.assertEqual(service.recorded_audio_capabilities, [])
        self.assertEqual(len(service.registered_cameras), 2)  # unaffected


if __name__ == "__main__":
    unittest.main()
