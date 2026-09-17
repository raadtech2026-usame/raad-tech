"""The worker's `retry_av_attributes_discovery` scheduled job (2026-09-17). Proves the job is
registered at the configured interval and sends exactly one `0x9003` request per device the
application service claims — the claim/idempotency rules themselves are covered in
`test_fleet_device_application.py`'s `ClaimDueAvAttributesDiscoveryTests`."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.config.settings import Settings
from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort
from raad.core.time.clock import Clock
from raad.core.workers.scheduler import IntervalScheduler
from raad.interfaces.workers.bootstrap import _register_scheduled_jobs
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import DeviceApplicationService

_JOB_NAME = "retry_av_attributes_discovery"


class _FixedClock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 9, 17, tzinfo=timezone.utc)


class _RecordingBroker:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


class _ClaimingDeviceService:
    def __init__(self, terminal_ids: list[str]) -> None:
        self._terminal_ids = terminal_ids
        self.claim_calls = 0

    async def claim_due_av_attributes_discovery(self, *, uow) -> list[str]:
        self.claim_calls += 1
        return list(self._terminal_ids)


class RetryAvAttributesDiscoveryJobTests(unittest.IsolatedAsyncioTestCase):
    def _scheduler(self, container: Container, settings: Settings) -> IntervalScheduler:
        scheduler = IntervalScheduler(_FixedClock())
        _register_scheduled_jobs(scheduler, container, settings)
        return scheduler

    def _container(self, service: _ClaimingDeviceService, broker: _RecordingBroker | None):
        container = Container()
        container.bind_singleton(DeviceApplicationService, service)
        container.bind_factory(FleetDeviceUnitOfWork, lambda: object())
        if broker is not None:
            container.bind_singleton(BrokerPort, broker)
        return container

    def _job(self, scheduler: IntervalScheduler):
        return next(job for job in scheduler._jobs if job.name == _JOB_NAME)

    async def test_job_is_registered_at_the_configured_interval(self) -> None:
        settings = Settings()
        scheduler = self._scheduler(
            self._container(_ClaimingDeviceService([]), _RecordingBroker()), settings
        )

        job = self._job(scheduler)

        self.assertEqual(
            job.interval_seconds,
            settings.workers.av_attributes_discovery_retry_interval_seconds,
        )

    async def test_sends_one_query_per_claimed_device(self) -> None:
        service = _ClaimingDeviceService(["00000000014482607571", "00000000013800138000"])
        broker = _RecordingBroker()
        scheduler = self._scheduler(self._container(service, broker), Settings())

        await self._job(scheduler).handler()

        self.assertEqual(service.claim_calls, 1)
        self.assertEqual(
            [event.payload["terminal_id"] for event in broker.published],
            ["00000000014482607571", "00000000013800138000"],
        )
        self.assertTrue(
            all(event.payload["command"] == "query_av_attributes" for event in broker.published)
        )

    async def test_nothing_claimed_publishes_nothing(self) -> None:
        broker = _RecordingBroker()
        scheduler = self._scheduler(
            self._container(_ClaimingDeviceService([]), broker), Settings()
        )

        await self._job(scheduler).handler()

        self.assertEqual(broker.published, [])

    async def test_without_a_broker_the_job_completes_without_raising(self) -> None:
        scheduler = self._scheduler(
            self._container(_ClaimingDeviceService(["00007"]), broker=None), Settings()
        )

        await self._job(scheduler).handler()  # must not raise


if __name__ == "__main__":
    unittest.main()
