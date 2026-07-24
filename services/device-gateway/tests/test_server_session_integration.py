"""Integration verification: `DeviceSessionManager` wired through the real `Jt808Server` /
`ConnectionManager` (Phase 9.1 transport + Phase 9.2 session management together), using real
TCP clients on loopback. No JT808 packet parsing exists yet, so `device_sessions.create()` is
called directly here (standing in for a not-yet-built `AuthHandler`) — this test's job is to
prove the transport<->session wiring itself (connection drop closes the bound device session;
superseding a duplicate terminal closes the old socket), not to simulate the JT808 protocol.
"""

import asyncio
import unittest

from src.config import ServerConfig
from src.server import Jt808Server


class ServerSessionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ServerConfig(
            host="127.0.0.1",
            port=0,
            idle_timeout_seconds=5.0,
            sweep_interval_seconds=1.0,
            device_session_timeout_seconds=0.2,
            device_session_sweep_interval_seconds=0.05,
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

    def _connection_id_for(self, remote_port: int) -> str:
        for connection_id, connection in self.server.manager._connections.items():
            if connection.remote_address.endswith(f", {remote_port})"):
                return connection_id
        raise AssertionError(f"no connection found for local port {remote_port}")

    async def test_authenticate_over_real_connection_then_disconnect_cleans_up(
        self,
    ) -> None:
        _, writer = await self._open_client()
        await asyncio.sleep(0.02)
        local_port = writer.get_extra_info("sockname")[1]
        connection_id = self._connection_id_for(local_port)

        session = await self.server.device_sessions.create(
            connection_id=connection_id, terminal_id="TERM-REAL-1"
        )
        self.assertEqual(self.server.device_session_count, 1)
        self.assertIs(self.server.device_sessions.resolve("TERM-REAL-1"), session)

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)

        self.assertEqual(self.server.manager.connection_count, 0)
        self.assertEqual(self.server.device_session_count, 0)

    async def test_duplicate_terminal_over_two_real_connections_closes_old_socket(
        self,
    ) -> None:
        reader1, writer1 = await self._open_client()
        await asyncio.sleep(0.02)
        conn1_id = self._connection_id_for(writer1.get_extra_info("sockname")[1])
        await self.server.device_sessions.create(
            connection_id=conn1_id, terminal_id="TERM-DUP"
        )
        self.assertEqual(self.server.manager.connection_count, 1)

        _, writer2 = await self._open_client()
        await asyncio.sleep(0.02)
        conn2_id = self._connection_id_for(writer2.get_extra_info("sockname")[1])
        await self.server.device_sessions.create(
            connection_id=conn2_id, terminal_id="TERM-DUP"
        )

        # The first socket must have been closed server-side by the supersede.
        data = await asyncio.wait_for(reader1.read(), timeout=1.0)
        self.assertEqual(data, b"")

        await asyncio.sleep(0.05)
        self.assertEqual(
            self.server.manager.connection_count, 1
        )  # only the new one remains
        self.assertEqual(self.server.device_session_count, 1)
        self.assertIs(
            self.server.device_sessions.resolve("TERM-DUP").connection_id, conn2_id
        )

    async def test_device_session_expires_via_real_sweep_task(self) -> None:
        _, writer = await self._open_client()
        await asyncio.sleep(0.02)
        connection_id = self._connection_id_for(writer.get_extra_info("sockname")[1])
        await self.server.device_sessions.create(
            connection_id=connection_id, terminal_id="TERM-EXPIRE"
        )
        self.assertEqual(self.server.device_session_count, 1)

        # device_session_timeout_seconds=0.2, sweep every 0.05s -> should expire well within.
        await asyncio.sleep(0.5)

        self.assertEqual(self.server.device_session_count, 0)
        # The underlying transport connection is untouched by device-session expiry alone.
        self.assertEqual(self.server.manager.connection_count, 1)

    async def test_graceful_shutdown_closes_device_sessions_too(self) -> None:
        for i in range(3):
            _, writer = await self._open_client()
            await asyncio.sleep(0.02)
            connection_id = self._connection_id_for(
                writer.get_extra_info("sockname")[1]
            )
            await self.server.device_sessions.create(
                connection_id=connection_id, terminal_id=f"TERM-{i}"
            )

        self.assertEqual(self.server.device_session_count, 3)
        self.assertEqual(self.server.manager.connection_count, 3)

        await self.server.stop()

        self.assertEqual(self.server.device_session_count, 0)
        self.assertEqual(self.server.manager.connection_count, 0)

        await self.server.start()  # so asyncTearDown's own stop() is a harmless no-op

    async def test_no_leaked_tasks_after_full_session_lifecycle(self) -> None:
        before = {t for t in asyncio.all_tasks() if not t.done()}

        _, writer = await self._open_client()
        await asyncio.sleep(0.02)
        connection_id = self._connection_id_for(writer.get_extra_info("sockname")[1])
        await self.server.device_sessions.create(
            connection_id=connection_id, terminal_id="TERM-LEAK-CHECK"
        )
        self.server.device_sessions.touch("TERM-LEAK-CHECK")
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)

        after = {t for t in asyncio.all_tasks() if not t.done()}
        leaked = after - before
        leaked = {
            t
            for t in leaked
            if "_sweep_loop" not in repr(t) and "accept_coro" not in repr(t)
        }
        self.assertEqual(leaked, set(), f"leaked tasks: {leaked}")


if __name__ == "__main__":
    unittest.main()
