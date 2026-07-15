"""Session abstraction and registry tests (Phase 9.1)."""

import time
import unittest

from src.session.registry import SessionRegistry
from src.session.session import ConnectionSession, SessionState


class SessionRegistryTests(unittest.TestCase):
    def test_add_get_remove(self) -> None:
        registry = SessionRegistry()
        session = ConnectionSession(connection_id="c1", remote_address="127.0.0.1:1")
        registry.add(session)
        self.assertIs(registry.get("c1"), session)
        self.assertEqual(len(registry), 1)
        registry.remove("c1")
        self.assertIsNone(registry.get("c1"))
        self.assertEqual(len(registry), 0)

    def test_remove_unknown_is_a_noop(self) -> None:
        registry = SessionRegistry()
        registry.remove("does-not-exist")  # must not raise

    def test_all_returns_every_session(self) -> None:
        registry = SessionRegistry()
        registry.add(ConnectionSession(connection_id="a", remote_address="x"))
        registry.add(ConnectionSession(connection_id="b", remote_address="y"))
        ids = {s.connection_id for s in registry.all()}
        self.assertEqual(ids, {"a", "b"})


class ConnectionSessionTests(unittest.TestCase):
    def test_touch_updates_last_activity(self) -> None:
        session = ConnectionSession(connection_id="c1", remote_address="127.0.0.1:1")
        before = session.last_activity_at
        time.sleep(0.01)
        session.touch()
        self.assertGreater(session.last_activity_at, before)

    def test_default_state_connected(self) -> None:
        session = ConnectionSession(connection_id="c1", remote_address="x")
        self.assertEqual(session.state, SessionState.CONNECTED)

    def test_mark_closed(self) -> None:
        session = ConnectionSession(connection_id="c1", remote_address="x")
        session.mark_closed()
        self.assertEqual(session.state, SessionState.CLOSED)


if __name__ == "__main__":
    unittest.main()
