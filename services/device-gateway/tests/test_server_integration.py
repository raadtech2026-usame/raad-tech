"""Integration verification for Phase 9.1's transport layer: a real asyncio TCP server, real
socket clients on loopback, and mocked JT/T 808 frames (0x7e-delimited bytes with placeholder
bodies — no field parsing exists yet in this phase, so bodies are arbitrary bytes).
"""

import asyncio
import unittest

from src.config import ServerConfig
from src.server import Jt808Server


class ServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ServerConfig(
            host="127.0.0.1",
            port=0,  # let the OS assign a free port
            idle_timeout_seconds=0.2,
            sweep_interval_seconds=0.05,
        )
        self.server = Jt808Server(self.config)
        await self.server.start()
        self.port = self.server.bound_port
        self._client_writers: list[asyncio.StreamWriter] = []

    async def asyncTearDown(self) -> None:
        for writer in self._client_writers:
            if not writer.is_closing():
                writer.close()
        await self.server.stop()

    async def _open_client(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._client_writers.append(writer)
        return reader, writer

    async def test_accepts_multiple_connections(self) -> None:
        for _ in range(5):
            await self._open_client()
        await asyncio.sleep(0.05)
        self.assertEqual(self.server.manager.connection_count, 5)
        self.assertEqual(self.server.session_count, 5)

    async def test_frame_boundary_detection_across_writes(self) -> None:
        received: list[bytes] = []

        async def capture(connection_id: str, frame: bytes) -> None:
            received.append(frame)

        self.server.manager._on_frame = (
            capture  # inject a capturing handler for this test
        )

        _, writer = await self._open_client()
        mock_frame = bytes([0x7E, 0x01, 0x02, 0x03, 0x7E])
        writer.write(mock_frame[:2])
        await writer.drain()
        await asyncio.sleep(0.02)
        writer.write(mock_frame[2:])
        await writer.drain()
        await asyncio.sleep(0.05)

        self.assertEqual(received, [bytes([0x01, 0x02, 0x03])])

    async def test_multiple_frames_one_client(self) -> None:
        received: list[bytes] = []

        async def capture(connection_id: str, frame: bytes) -> None:
            received.append(frame)

        self.server.manager._on_frame = capture

        _, writer = await self._open_client()
        writer.write(bytes([0x7E, 0xAA, 0x7E, 0x7E, 0xBB, 0xCC, 0x7E]))
        await writer.drain()
        await asyncio.sleep(0.05)

        self.assertEqual(received, [bytes([0xAA]), bytes([0xBB, 0xCC])])

    async def test_disconnect_cleans_up_session_and_connection(self) -> None:
        _, writer = await self._open_client()
        await asyncio.sleep(0.02)
        self.assertEqual(self.server.manager.connection_count, 1)

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)

        self.assertEqual(self.server.manager.connection_count, 0)
        self.assertEqual(self.server.session_count, 0)

    async def test_idle_timeout_closes_connection(self) -> None:
        _, writer = await self._open_client()
        await asyncio.sleep(0.02)
        self.assertEqual(self.server.manager.connection_count, 1)

        # No data sent -> idle_timeout_seconds=0.2 should trip within a couple of sweeps.
        await asyncio.sleep(0.5)

        self.assertEqual(self.server.manager.connection_count, 0)
        self.assertEqual(self.server.session_count, 0)

    async def test_activity_resets_idle_timeout(self) -> None:
        _, writer = await self._open_client()
        await asyncio.sleep(0.02)

        # Send a frame every 0.1s for 0.4s (idle_timeout=0.2s) -> should stay alive throughout.
        for _ in range(4):
            writer.write(bytes([0x7E, 0x01, 0x7E]))
            await writer.drain()
            await asyncio.sleep(0.1)

        self.assertEqual(self.server.manager.connection_count, 1)

    async def test_graceful_shutdown_closes_all_connections(self) -> None:
        for _ in range(3):
            await self._open_client()
        await asyncio.sleep(0.02)
        self.assertEqual(self.server.manager.connection_count, 3)

        await self.server.stop()
        self.assertEqual(self.server.manager.connection_count, 0)
        self.assertEqual(self.server.session_count, 0)

        # Restart so asyncTearDown's own stop() call is a harmless no-op.
        await self.server.start()

    async def test_frame_too_large_closes_connection(self) -> None:
        small_frame_server = Jt808Server(
            ServerConfig(
                host="127.0.0.1",
                port=0,
                max_frame_size=4,
                idle_timeout_seconds=5.0,
                sweep_interval_seconds=1.0,
            )
        )
        await small_frame_server.start()
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", small_frame_server.bound_port
            )
            writer.write(bytes([0x7E, 1, 2, 3, 4, 5, 6, 0x7E]))
            await writer.drain()
            data = await asyncio.wait_for(reader.read(), timeout=1.0)
            self.assertEqual(data, b"")  # server closed the connection
            writer.close()
        finally:
            await small_frame_server.stop()

    async def test_no_leaked_tasks_after_full_lifecycle(self) -> None:
        before = {t for t in asyncio.all_tasks() if not t.done()}

        _, writer = await self._open_client()
        writer.write(bytes([0x7E, 0x01, 0x7E]))
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)

        after = {t for t in asyncio.all_tasks() if not t.done()}
        leaked = after - before
        # Excluded as legitimate, not a leak: (1) the server's own sweep task, alive until
        # stop(); (2) on Windows, the Proactor event loop's IOCP accept-listener task is
        # re-created (a new Task object, same purpose) each time a connection completes —
        # asyncio's own internal "waiting for the next connection" machinery, not anything
        # `Connection`/`ConnectionManager` created or should be cleaning up.
        leaked = {
            t
            for t in leaked
            if "_sweep_loop" not in repr(t) and "accept_coro" not in repr(t)
        }
        self.assertEqual(leaked, set(), f"leaked tasks: {leaked}")


if __name__ == "__main__":
    unittest.main()
