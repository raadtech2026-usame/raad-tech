"""ADR-0046 §1 — camera presence from the terminal's own video-signal-loss report.

Covers: the bit-to-channel mapping (cameras on ch1 and ch3 only, a camera later added to ch2 or
ch4), `DeviceApplicationService` enriching every camera with `video_signal` and failing open when
the store is unavailable, recording a report, the `DeviceVideoSignalStatusReported` processor, and
the Redis adapter's round trip and TTL.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.modules.fleet_device.application.commands import RegisterCameraCommand
from raad.modules.fleet_device.application.ports import CameraSignalReport, CameraSignalStatePort
from raad.modules.fleet_device.application.queries import (
    GetDeviceByIdQuery,
    ListDevicesQuery,
    camera_video_signal,
)
from raad.modules.fleet_device.application.services import DeviceApplicationService
from raad.modules.fleet_device.domain.value_objects import CameraPosition
from raad.modules.fleet_device.events.subscribers import DeviceVideoSignalStatusProcessor
from raad.modules.fleet_device.infra.adapters import RedisCameraSignalStatePort
from tests.unit.test_fleet_device_application import (
    FixedClock,
    SequentialIdGenerator,
    _register_activated_device,
    make_actor,
    make_services,
)
from raad.core.pagination import OffsetPageRequest

REPORTED_AT = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)
#: Production, 2026-09-19: cameras on ch1 and ch3, none on ch2 and ch4.
CH1_CH3_INSTALLED = 0x0000000A


def _report(mask: int) -> CameraSignalReport:
    return CameraSignalReport(loss_mask=mask, occlusion_mask=0, reported_at=REPORTED_AT)


class BitMappingTests(unittest.TestCase):
    def test_today_ch1_and_ch3_are_present_ch2_and_ch4_absent(self) -> None:
        report = _report(CH1_CH3_INSTALLED)
        self.assertEqual(
            [camera_video_signal(ch, report) for ch in (1, 2, 3, 4)],
            ["present", "absent", "present", "absent"],
        )

    def test_a_camera_later_connected_to_ch2_becomes_present(self) -> None:
        report = _report(0x00000008)  # only ch4 still without signal
        self.assertEqual(
            [camera_video_signal(ch, report) for ch in (1, 2, 3, 4)],
            ["present", "present", "present", "absent"],
        )

    def test_all_four_connected(self) -> None:
        self.assertEqual({camera_video_signal(ch, _report(0)) for ch in (1, 2, 3, 4)}, {"present"})

    def test_no_report_is_unknown(self) -> None:
        self.assertEqual(camera_video_signal(1, None), "unknown")

    def test_a_channel_outside_the_32_bit_mask_is_unknown(self) -> None:
        self.assertEqual(camera_video_signal(33, _report(0)), "unknown")


class InMemorySignalStore(CameraSignalStatePort):
    def __init__(self) -> None:
        self.reports: dict[str, CameraSignalReport] = {}
        self.fail = False

    async def save(self, device_id, report) -> None:
        self.reports[device_id] = report

    async def get_many(self, device_ids):
        if self.fail:
            raise ConnectionError("redis down")
        return {d: self.reports[d] for d in device_ids if d in self.reports}


async def _device_with_four_cameras(device_service, uow) -> str:
    device_id = await _register_activated_device(device_service, uow)
    for channel_no in (1, 2, 3, 4):
        await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=channel_no,
                position=CameraPosition.OTHER,
                label=f"Channel {channel_no}",
                actor=make_actor(),
            ),
            uow=uow,
        )
    return device_id


class ServiceEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _vehicles, plain_service, self.uow = make_services()
        self.store = InMemorySignalStore()
        self.service = DeviceApplicationService(
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
            id_generator=SequentialIdGenerator(),
            camera_signal_states=lambda: self.store,
        )
        self.device_id = await _device_with_four_cameras(self.service, self.uow)

    async def _signals(self) -> list[str]:
        dto = await self.service.get_device_by_id(
            GetDeviceByIdQuery(device_id=self.device_id), uow=self.uow
        )
        return [c.video_signal for c in sorted(dto.cameras, key=lambda c: c.channel_no)]

    async def test_cameras_are_unknown_until_the_terminal_reports(self) -> None:
        self.assertEqual(await self._signals(), ["unknown"] * 4)

    async def test_a_recorded_report_marks_ch2_and_ch4_absent(self) -> None:
        await self.service.record_video_signal_status(
            device_id=self.device_id,
            loss_mask=CH1_CH3_INSTALLED,
            occlusion_mask=0,
            reported_at=REPORTED_AT,
        )
        self.assertEqual(await self._signals(), ["present", "absent", "present", "absent"])

    async def test_a_newly_connected_camera_appears_without_any_code_change(self) -> None:
        await self.service.record_video_signal_status(
            device_id=self.device_id, loss_mask=CH1_CH3_INSTALLED, occlusion_mask=0, reported_at=REPORTED_AT
        )
        await self.service.record_video_signal_status(
            device_id=self.device_id, loss_mask=0x08, occlusion_mask=0, reported_at=REPORTED_AT
        )
        self.assertEqual(await self._signals(), ["present", "present", "present", "absent"])

    async def test_the_list_read_is_enriched_too(self) -> None:
        await self.service.record_video_signal_status(
            device_id=self.device_id, loss_mask=CH1_CH3_INSTALLED, occlusion_mask=0, reported_at=REPORTED_AT
        )
        page = await self.service.list_devices(
            ListDevicesQuery(page_request=OffsetPageRequest(page=1, page_size=20)), uow=self.uow
        )
        cameras = sorted(page.data[0].cameras, key=lambda c: c.channel_no)
        self.assertEqual([c.video_signal for c in cameras], ["present", "absent", "present", "absent"])
        self.assertEqual(cameras[0].video_signal_reported_at, REPORTED_AT)

    async def test_an_unavailable_store_fails_open_to_unknown(self) -> None:
        await self.service.record_video_signal_status(
            device_id=self.device_id, loss_mask=CH1_CH3_INSTALLED, occlusion_mask=0, reported_at=REPORTED_AT
        )
        self.store.fail = True
        self.assertEqual(await self._signals(), ["unknown"] * 4)

    async def test_no_store_configured_means_unknown_and_recording_is_a_no_op(self) -> None:
        _vehicles, service, uow = make_services()
        device_id = await _device_with_four_cameras(service, uow)
        await service.record_video_signal_status(
            device_id=device_id, loss_mask=CH1_CH3_INSTALLED, occlusion_mask=0, reported_at=REPORTED_AT
        )
        dto = await service.get_device_by_id(GetDeviceByIdQuery(device_id=device_id), uow=uow)
        self.assertEqual({c.video_signal for c in dto.cameras}, {"unknown"})


class ProcessorTests(unittest.IsolatedAsyncioTestCase):
    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def record_video_signal_status(self, **kwargs) -> None:
            self.calls.append(kwargs)

    def _event(self, payload: dict) -> DomainEvent:
        return DomainEvent(
            event_id="evt-1",
            event_type="DeviceVideoSignalStatusReported",
            version=1,
            occurred_at=REPORTED_AT,
            org_id="org-1",
            correlation_id=None,
            payload=payload,
            aggregate_type="Device",
            aggregate_id="00000000014482607571",
        )

    async def test_records_the_masks_for_the_device(self) -> None:
        container = Container()
        recorder = self._Recorder()
        container.bind_singleton(DeviceApplicationService, recorder)
        await DeviceVideoSignalStatusProcessor(container).process(
            self._event(
                {
                    "device_id": "device-1",
                    "video_signal_loss_mask": 10,
                    "video_signal_occlusion_mask": 0,
                    "event_time": "2026-09-26T04:59:40+00:00",
                }
            )
        )
        self.assertEqual(
            recorder.calls,
            [
                {
                    "device_id": "device-1",
                    "loss_mask": 10,
                    "occlusion_mask": 0,
                    "reported_at": datetime(2026, 9, 26, 4, 59, 40, tzinfo=timezone.utc),
                }
            ],
        )

    async def test_an_event_without_a_device_or_mask_is_ignored(self) -> None:
        container = Container()
        recorder = self._Recorder()
        container.bind_singleton(DeviceApplicationService, recorder)
        processor = DeviceVideoSignalStatusProcessor(container)
        await processor.process(self._event({"video_signal_loss_mask": 10}))
        await processor.process(self._event({"device_id": "device-1"}))
        self.assertEqual(recorder.calls, [])


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key, value, ex=None) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def mget(self, keys):
        return [self.values.get(k) for k in keys]


class RedisAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_with_a_ttl(self) -> None:
        redis = FakeRedis()
        port = RedisCameraSignalStatePort(redis, ttl_seconds=1800)
        await port.save("device-1", _report(CH1_CH3_INSTALLED))
        self.assertEqual(redis.ttls["fleet_device:camera_signal:device-1"], 1800)
        self.assertEqual(json.loads(redis.values["fleet_device:camera_signal:device-1"])["loss_mask"], 10)
        reports = await port.get_many(["device-1", "device-2", "device-1"])
        self.assertEqual(reports, {"device-1": _report(CH1_CH3_INSTALLED)})

    async def test_no_ids_no_round_trip(self) -> None:
        self.assertEqual(await RedisCameraSignalStatePort(FakeRedis()).get_many([]), {})


class RetentionTests(unittest.TestCase):
    def test_the_last_report_survives_an_ordinary_outage(self) -> None:
        """Audit C3 (2026-09-26): a 30-minute TTL turned a terminal back from a longer outage into
        four "unknown" cameras until its first report. Installation changes are corrected by the
        report the gateway publishes on every reconnect, so the last one is kept for 30 days."""
        from raad.modules.fleet_device.infra.adapters import DEFAULT_CAMERA_SIGNAL_TTL_SECONDS

        self.assertEqual(DEFAULT_CAMERA_SIGNAL_TTL_SECONDS, 30 * 24 * 60 * 60)
