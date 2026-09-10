"""`IntervalScheduler` job isolation, and the `LogRecord` collision that made it matter.

**The incident these tests encode.** `run_pending()` awaited each due job's handler with no
`try`/`except`, so an exception propagated straight out of the loop. Jobs run in registration
order, and `maintain_position_partitions` is registered first — so when it raised, every job
after it was skipped for that tick: `sweep_expired_subscriptions`,
`mark_overdue_student_invoices`, `reconcile_expired_payments` and
`reconcile_stale_intercom_sessions`.

What made it raise was not database trouble but a logging call:
`logger.info(..., extra={"created": ..., "dropped": ...})`. `created` is a reserved `LogRecord`
attribute — the record's own timestamp — and `logging` raises
`KeyError: "Attempt to overwrite 'created' in LogRecord"` rather than shadowing it. Observed
live in `raad-worker` on 2026-09-09. The result was a subscription lifecycle that looked
implemented and was intermittently inert, which is precisely the state ADR-0039's grace period
cannot tolerate: access ends when grace ends, and nothing was ending it.

Two independent defects, so two independent guards: isolation here, and a codebase-wide scan for
reserved `extra` keys so the trigger cannot be reintroduced in some other job.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from raad.core.time.clock import Clock
from raad.core.workers.scheduler import IntervalScheduler, ScheduledJob


class _ManualClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def _recording_job(name: str, log: list[str], *, fails: bool = False) -> ScheduledJob:
    async def handler() -> None:
        log.append(name)
        if fails:
            raise RuntimeError(f"{name} exploded")

    return ScheduledJob(name=name, interval_seconds=60, handler=handler)


class SchedulerIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = _ManualClock(datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc))
        self.scheduler = IntervalScheduler(self.clock)
        self.ran: list[str] = []

    async def test_a_failing_job_does_not_stop_the_ones_after_it(self) -> None:
        """The exact production shape: the first-registered job raises."""
        self.scheduler.register(_recording_job("partitions", self.ran, fails=True))
        self.scheduler.register(_recording_job("subscription_sweep", self.ran))
        self.scheduler.register(_recording_job("overdue_invoices", self.ran))
        self.scheduler.register(_recording_job("reconcile_payments", self.ran))

        with self.assertLogs("raad.workers.scheduler", level="ERROR"):
            await self.scheduler.run_pending()

        self.assertEqual(
            self.ran,
            ["partitions", "subscription_sweep", "overdue_invoices", "reconcile_payments"],
        )

    async def test_every_job_can_fail_and_the_rest_still_run(self) -> None:
        """Not just the first — isolation must not depend on where the failure lands."""
        for position in range(3):
            with self.subTest(failing_index=position):
                clock = _ManualClock(datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc))
                scheduler = IntervalScheduler(clock)
                ran: list[str] = []
                for index in range(3):
                    scheduler.register(
                        _recording_job(f"job{index}", ran, fails=index == position)
                    )
                with self.assertLogs("raad.workers.scheduler", level="ERROR"):
                    await scheduler.run_pending()
                self.assertEqual(ran, ["job0", "job1", "job2"])

    async def test_the_failure_is_logged_with_the_job_name(self) -> None:
        """An isolated failure that logs nothing is just a silent failure.

        The field is `job_name` rather than `name` on purpose: `name` is itself a reserved
        `LogRecord` attribute, so logging the failure that way would raise inside the handler
        meant to contain it.
        """
        self.scheduler.register(_recording_job("subscription_sweep", self.ran, fails=True))

        with self.assertLogs("raad.workers.scheduler", level="ERROR") as captured:
            await self.scheduler.run_pending()

        record = captured.records[0]
        self.assertEqual(record.message if hasattr(record, "message") else record.msg,
                         "scheduled_job_failed")
        self.assertEqual(getattr(record, "job_name"), "subscription_sweep")
        self.assertIsNotNone(record.exc_info)

    async def test_a_failing_job_waits_out_its_interval_rather_than_retrying_every_tick(
        self,
    ) -> None:
        """`_last_run` is stamped before the handler runs, and must stay that way.

        Stamping it afterwards would leave a failing job permanently due, so the worker above
        would re-run it on every tick — turning one broken job into a hot loop against whatever
        it was failing to reach.
        """
        self.scheduler.register(_recording_job("flaky", self.ran, fails=True))

        with self.assertLogs("raad.workers.scheduler", level="ERROR"):
            await self.scheduler.run_pending()
        self.clock.advance(30)  # less than the 60s interval
        await self.scheduler.run_pending()

        self.assertEqual(self.ran, ["flaky"])

        self.clock.advance(31)  # now past it
        with self.assertLogs("raad.workers.scheduler", level="ERROR"):
            await self.scheduler.run_pending()
        self.assertEqual(self.ran, ["flaky", "flaky"])

    async def test_a_healthy_tick_logs_no_error(self) -> None:
        self.scheduler.register(_recording_job("a", self.ran))
        self.scheduler.register(_recording_job("b", self.ran))

        with self.assertNoLogs("raad.workers.scheduler", level="ERROR"):
            await self.scheduler.run_pending()

        self.assertEqual(self.ran, ["a", "b"])


# ---------------------------------------------------------------------------------------------
# The trigger: reserved `LogRecord` attribute names passed through `extra=`.
# ---------------------------------------------------------------------------------------------

#: `logging.Logger.makeRecord` raises `KeyError` for any of these, rather than shadowing them.
#: Taken from `logging.LogRecord.__init__`'s own attributes plus the two the `Formatter` adds.
_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info", "taskName",
        "thread", "threadName",
    }
)

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2] / "raad"


def _reserved_extra_keys_in(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every literal `extra={...}` key that collides with a `LogRecord` attribute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue
            for key in keyword.value.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value in _RESERVED_LOGRECORD_KEYS
                ):
                    offenders.append((key.lineno, key.value))
    return offenders


class ReservedLogRecordKeyTests(unittest.TestCase):
    def test_no_logging_call_passes_a_reserved_logrecord_key(self) -> None:
        """A codebase-wide scan, because the failure mode is invisible until the branch runs.

        `logger.info(..., extra={"created": n})` raises only when that line actually executes —
        here, only when the partition job had partitions to create. It sat dormant through every
        test run and every deploy until the day it fired.
        """
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in sorted(_BACKEND_ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            found = _reserved_extra_keys_in(path)
            if found:
                offenders[str(path.relative_to(_BACKEND_ROOT.parent))] = found

        self.assertEqual(
            offenders,
            {},
            "logging `extra=` keys collide with reserved LogRecord attributes. `logging` "
            "raises KeyError on these at call time:\n"
            + "\n".join(
                f"  {file}: " + ", ".join(f"line {line}: {key!r}" for line, key in items)
                for file, items in sorted(offenders.items())
            ),
        )

    def test_the_scan_detects_a_reserved_key(self) -> None:
        """Proves the detector fires — a gate nobody has seen fail is a gate nobody trusts."""
        source = 'logger.info("x", extra={"created": 1, "safe": 2})\n'
        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                        for key in keyword.value.keys:
                            if (
                                isinstance(key, ast.Constant)
                                and key.value in _RESERVED_LOGRECORD_KEYS
                            ):
                                found.append(key.value)
        self.assertEqual(found, ["created"])

    def test_python_logging_really_does_raise_on_a_reserved_key(self) -> None:
        """The premise, asserted rather than assumed. If a future Python stopped raising here,
        the scan above would be enforcing a rule that no longer exists."""
        logger = logging.getLogger("raad.test.reserved-key")
        with self.assertRaises(KeyError):
            logger.makeRecord(
                "raad.test", logging.INFO, "f.py", 1, "msg", None, None,
                extra={"created": 123},
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
