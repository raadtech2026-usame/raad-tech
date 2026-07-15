"""HandlerRegistry tests (Phase 9.4): registration, resolution, duplicate prevention."""

import unittest

from src.dispatcher.exceptions import DuplicateHandlerError
from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.dispatcher.registry import HandlerRegistry


class _StubHandler(MessageHandler):
    async def handle(self, message, context) -> HandlerResult:
        return HandlerResult.no_response()


class HandlerRegistryTests(unittest.TestCase):
    def test_register_and_resolve(self) -> None:
        registry = HandlerRegistry()
        handler = _StubHandler()
        registry.register(0x0002, handler)
        self.assertIs(registry.resolve(0x0002), handler)

    def test_resolve_unknown_returns_none(self) -> None:
        registry = HandlerRegistry()
        self.assertIsNone(registry.resolve(0x9999))

    def test_duplicate_registration_raises(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _StubHandler())
        with self.assertRaises(DuplicateHandlerError):
            registry.register(0x0002, _StubHandler())

    def test_duplicate_registration_does_not_replace_existing_handler(self) -> None:
        registry = HandlerRegistry()
        first = _StubHandler()
        registry.register(0x0002, first)
        try:
            registry.register(0x0002, _StubHandler())
        except DuplicateHandlerError:
            pass
        self.assertIs(registry.resolve(0x0002), first)

    def test_distinct_message_ids_independent(self) -> None:
        registry = HandlerRegistry()
        h1, h2 = _StubHandler(), _StubHandler()
        registry.register(0x0002, h1)
        registry.register(0x0003, h2)
        self.assertIs(registry.resolve(0x0002), h1)
        self.assertIs(registry.resolve(0x0003), h2)

    def test_len_reflects_registered_count(self) -> None:
        registry = HandlerRegistry()
        registry.register(0x0002, _StubHandler())
        registry.register(0x0003, _StubHandler())
        self.assertEqual(len(registry), 2)


if __name__ == "__main__":
    unittest.main()
