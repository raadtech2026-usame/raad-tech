"""ADR-0022: `PaymentProviderPort` adapters. `StripePaymentAdapter`'s HTTP calls are mocked
(`unittest.mock.AsyncMock` standing in for `httpx.AsyncClient` — no real network call, no
`pytest-httpx`/similar dependency needed for this) since no live Stripe account exists in this
environment; the signature-verification tests below construct their own valid/tampered
signatures rather than relying on an external test vector, so they're still a real, independent
check of the implementation, not just "it returns what I told it to."
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from raad.core.errors.exceptions import DomainError, PaymentError
from raad.modules.billing.application.ports import (
    PaymentChargeRequest,
    UnhandledWebhookEventError,
)
from raad.modules.billing.domain.value_objects import Money
from raad.modules.billing.infra.adapters import (
    EvcPlusPaymentAdapter,
    StripePaymentAdapter,
    ZaadPaymentAdapter,
    _to_minor_units,
)

_WEBHOOK_SECRET = "whsec_test_secret"


def _sign(payload: bytes, *, secret: str = _WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _make_adapter(http_client=None) -> StripePaymentAdapter:
    return StripePaymentAdapter(
        http_client=http_client or AsyncMock(),
        secret_key="sk_test_x",
        webhook_secret=_WEBHOOK_SECRET,
    )


class CentsConversionTests(unittest.TestCase):
    def test_converts_standard_two_decimal_amount(self) -> None:
        self.assertEqual(_to_minor_units(19.99, "USD"), 1999)

    def test_rounds_floating_point_noise(self) -> None:
        self.assertEqual(_to_minor_units(10.10, "USD"), 1010)

    def test_zero_amount(self) -> None:
        self.assertEqual(_to_minor_units(0.0, "USD"), 0)


class WebhookSignatureVerificationTests(unittest.TestCase):
    def test_accepts_a_correctly_signed_payload(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        header = _sign(payload)
        self.assertTrue(adapter.verify_webhook_signature(payload=payload, signature_header=header))

    def test_rejects_a_tampered_signature(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        ts = str(int(time.time()))
        header = f"t={ts},v1=" + "0" * 64
        self.assertFalse(adapter.verify_webhook_signature(payload=payload, signature_header=header))

    def test_rejects_a_payload_signed_with_a_different_secret(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        header = _sign(payload, secret="whsec_wrong_secret")
        self.assertFalse(adapter.verify_webhook_signature(payload=payload, signature_header=header))

    def test_rejects_a_stale_timestamp(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        header = _sign(payload, timestamp=int(time.time()) - 1000)
        self.assertFalse(adapter.verify_webhook_signature(payload=payload, signature_header=header))

    def test_rejects_a_malformed_header(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1"}'
        self.assertFalse(
            adapter.verify_webhook_signature(payload=payload, signature_header="not-a-real-header")
        )

    def test_rejects_an_empty_header(self) -> None:
        adapter = _make_adapter()
        payload = b'{"id":"evt_1"}'
        self.assertFalse(adapter.verify_webhook_signature(payload=payload, signature_header=""))


class WebhookEventParsingTests(unittest.TestCase):
    def test_parses_a_succeeded_event(self) -> None:
        adapter = _make_adapter()
        payload = json.dumps(
            {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_123"}}}
        ).encode()
        event = adapter.parse_webhook_event(payload=payload)
        self.assertEqual(event.provider_ref, "pi_123")
        self.assertEqual(event.status, "paid")
        self.assertIsNone(event.failure_reason)

    def test_parses_a_failed_event_with_its_decline_message(self) -> None:
        adapter = _make_adapter()
        payload = json.dumps(
            {
                "type": "payment_intent.payment_failed",
                "data": {
                    "object": {
                        "id": "pi_456",
                        "last_payment_error": {"message": "Your card was declined."},
                    }
                },
            }
        ).encode()
        event = adapter.parse_webhook_event(payload=payload)
        self.assertEqual(event.provider_ref, "pi_456")
        self.assertEqual(event.status, "failed")
        self.assertEqual(event.failure_reason, "Your card was declined.")

    def test_raises_for_an_event_type_with_no_handling(self) -> None:
        adapter = _make_adapter()
        payload = json.dumps(
            {"type": "payment_intent.created", "data": {"object": {"id": "pi_789"}}}
        ).encode()
        with self.assertRaises(UnhandledWebhookEventError):
            adapter.parse_webhook_event(payload=payload)


def _mock_response(status_code: int, payload: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class StripeChargeTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_a_payment_method_token(self) -> None:
        adapter = _make_adapter()
        request = PaymentChargeRequest(amount=Money(10.0, "USD"), reference="ref-1")
        with self.assertRaises(DomainError):
            await adapter.charge(request)

    async def test_maps_a_succeeded_payment_intent(self) -> None:
        http_client = AsyncMock()
        http_client.post.return_value = _mock_response(200, {"id": "pi_ok", "status": "succeeded"})
        adapter = _make_adapter(http_client)

        result = await adapter.charge(
            PaymentChargeRequest(
                amount=Money(19.99, "USD"), reference="ref-2", payment_method_token="pm_123"
            )
        )

        self.assertEqual(result.provider_ref, "pi_ok")
        self.assertEqual(result.status, "succeeded")
        call_kwargs = http_client.post.call_args.kwargs
        self.assertEqual(call_kwargs["data"]["amount"], 1999)
        self.assertEqual(call_kwargs["data"]["currency"], "usd")
        self.assertEqual(call_kwargs["data"]["payment_method"], "pm_123")
        self.assertEqual(call_kwargs["headers"]["Idempotency-Key"], "ref-2")

    async def test_maps_a_declined_payment_intent_to_failed(self) -> None:
        http_client = AsyncMock()
        http_client.post.return_value = _mock_response(
            200,
            {
                "id": "pi_declined",
                "status": "requires_payment_method",
                "last_payment_error": {"message": "Insufficient funds."},
            },
        )
        adapter = _make_adapter(http_client)

        result = await adapter.charge(
            PaymentChargeRequest(
                amount=Money(19.99, "USD"), reference="ref-3", payment_method_token="pm_123"
            )
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_reason, "Insufficient funds.")

    async def test_raises_payment_error_on_a_stripe_error_response(self) -> None:
        http_client = AsyncMock()
        http_client.post.return_value = _mock_response(
            402, {"error": {"message": "Your card was declined."}}
        )
        adapter = _make_adapter(http_client)

        with self.assertRaises(PaymentError):
            await adapter.charge(
                PaymentChargeRequest(
                    amount=Money(19.99, "USD"), reference="ref-4", payment_method_token="pm_123"
                )
            )


class StubAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Confirms both stubs raise their documented error rather than silently succeeding —
    ADR-0022's own explicit requirement, not a guessed implementation dressed up as real."""

    async def test_evc_plus_charge_raises(self) -> None:
        adapter = EvcPlusPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            await adapter.charge(
                PaymentChargeRequest(amount=Money(10.0, "USD"), reference="ref-1", msisdn="+252600000")
            )

    def test_evc_plus_verify_webhook_signature_raises(self) -> None:
        adapter = EvcPlusPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.verify_webhook_signature(payload=b"{}", signature_header="x")

    def test_evc_plus_parse_webhook_event_raises(self) -> None:
        adapter = EvcPlusPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.parse_webhook_event(payload=b"{}")

    async def test_zaad_charge_raises(self) -> None:
        adapter = ZaadPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            await adapter.charge(
                PaymentChargeRequest(amount=Money(10.0, "USD"), reference="ref-1", msisdn="+252600000")
            )

    def test_zaad_verify_webhook_signature_raises(self) -> None:
        adapter = ZaadPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.verify_webhook_signature(payload=b"{}", signature_header="x")

    def test_zaad_parse_webhook_event_raises(self) -> None:
        adapter = ZaadPaymentAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.parse_webhook_event(payload=b"{}")


if __name__ == "__main__":
    unittest.main()
