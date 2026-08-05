"""Concrete `PaymentProviderPort` adapters (ADR-0022). `httpx` is this module's own dependency
— no other module in this codebase needs an outbound HTTP client yet, so it is imported only
here, not added to `core/`.

**`StripePaymentAdapter` is real and verified against Stripe's own public API documentation** —
Payment Intents (`POST /v1/payment_intents`), webhook signature verification (the documented
`Stripe-Signature` HMAC-SHA256 scheme), and event parsing. No live Stripe account exists in this
environment (a disclosed limitation, not a claim of live end-to-end verification — see ADR-0022's
own Verification section), but the request/response shapes, cents conversion, and signature
scheme are all implemented exactly as Stripe's documentation specifies, not guessed.

**`EvcPlusPaymentAdapter`/`ZaadPaymentAdapter` are interface-complete stubs, not guesses.** Both
fully implement `PaymentProviderPort` (so they bind and type-check identically to Stripe, and the
seam is real and discoverable — a developer looking for "where does EVC Plus plug in" finds a
real class, not an empty interface), but every method raises `NotImplementedError` naming
exactly what's missing: a real merchant account and API documentation. Building a guessed
implementation against assumed request/response shapes would embed unverified assumptions as if
they were tested integration code — exactly what ADR-0022 (and `.claude/rules/workflow.md` #8)
was written to stop doing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from raad.core.errors.exceptions import DomainError, PaymentError
from raad.modules.billing.application.ports import (
    PaymentChargeRequest,
    PaymentChargeResult,
    PaymentProviderPort,
    UnhandledWebhookEventError,
    WebhookEvent,
)

_STRIPE_API_BASE = "https://api.stripe.com/v1"
_SIGNATURE_TOLERANCE_SECONDS = 300  # Stripe's own documented default replay-protection window.


def _to_minor_units(amount: float, currency: str) -> int:
    """Stripe amounts are integer minor units (cents for USD). Standard 2-decimal-currency
    conversion only — zero-decimal currencies (e.g. JPY) are a known, deliberate v1 scope cut
    (ADR-0022); RAAD bills in USD today."""
    return round(amount * 100)


class StripePaymentAdapter(PaymentProviderPort):
    def __init__(self, *, http_client: httpx.AsyncClient, secret_key: str, webhook_secret: str) -> None:
        self._http = http_client
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret

    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult:
        if not request.payment_method_token:
            raise DomainError(
                "StripePaymentAdapter requires PaymentChargeRequest.payment_method_token "
                "(a client-tokenized Stripe PaymentMethod id) — msisdn-based charging is not "
                "supported by this provider."
            )

        body: dict[str, Any] = {
            "amount": _to_minor_units(request.amount.amount, request.amount.currency),
            "currency": request.amount.currency.lower(),
            "payment_method": request.payment_method_token,
            "confirm": "true",
            "automatic_payment_methods[allow_redirects]": "never",
        }
        for key, value in request.metadata.items():
            body[f"metadata[{key}]"] = value

        try:
            response = await self._http.post(
                f"{_STRIPE_API_BASE}/payment_intents",
                data=body,
                headers={
                    "Authorization": f"Bearer {self._secret_key}",
                    "Idempotency-Key": request.reference,
                },
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"Stripe charge request failed: {exc}") from exc

        payload = response.json()
        if response.status_code >= 400:
            message = payload.get("error", {}).get("message", "Unknown Stripe error")
            raise PaymentError(f"Stripe declined the charge request: {message}")

        return _charge_result_from_payment_intent(payload)

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool:
        """Stripe's own documented scheme: `Stripe-Signature: t=<timestamp>,v1=<hex-hmac>`
        (`t.` + the raw request body, HMAC-SHA256 keyed by the webhook signing secret) —
        <https://stripe.com/docs/webhooks#verify-manually>. Also enforces a replay-protection
        timestamp tolerance, per the same documentation's own recommendation."""
        try:
            parts = dict(item.split("=", 1) for item in signature_header.split(","))
            timestamp = parts["t"]
            signature = parts["v1"]
        except (KeyError, ValueError):
            return False

        if abs(time.time() - int(timestamp)) > _SIGNATURE_TOLERANCE_SECONDS:
            return False

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent:
        event = json.loads(payload)
        event_type = event.get("type")
        data_object = event.get("data", {}).get("object", {})

        if event_type == "payment_intent.succeeded":
            return WebhookEvent(provider_ref=data_object["id"], status="paid")
        if event_type == "payment_intent.payment_failed":
            last_error = data_object.get("last_payment_error") or {}
            return WebhookEvent(
                provider_ref=data_object["id"],
                status="failed",
                failure_reason=last_error.get("message"),
            )
        raise UnhandledWebhookEventError(f"No handling for Stripe event type {event_type!r}.")


def _charge_result_from_payment_intent(payload: dict[str, Any]) -> PaymentChargeResult:
    """Maps a Stripe `PaymentIntent`'s `status` onto this port's three-way outcome. `succeeded`
    is the common synchronous-confirm result this v1 flow targets (no 3D Secure/SCA — ADR-0022's
    own scope cut, enforced by `automatic_payment_methods[allow_redirects]=never` above, which
    means `requires_action` should not occur in practice; still mapped defensively to `"pending"`
    rather than crashing if it ever does)."""
    status = payload["status"]
    provider_ref = payload["id"]
    if status == "succeeded":
        return PaymentChargeResult(provider_ref=provider_ref, status="succeeded")
    if status in ("requires_payment_method", "canceled"):
        last_error = payload.get("last_payment_error") or {}
        return PaymentChargeResult(
            provider_ref=provider_ref,
            status="failed",
            failure_reason=last_error.get("message", f"Stripe status: {status}"),
        )
    return PaymentChargeResult(provider_ref=provider_ref, status="pending")


class EvcPlusPaymentAdapter(PaymentProviderPort):
    """Interface-complete stub — see module docstring. No merchant account or API documentation
    exists in this engagement to build a verified integration against (Known Issue #4)."""

    _NOT_IMPLEMENTED_MESSAGE = (
        "EvcPlusPaymentAdapter is not implemented: no real EVC Plus merchant account or API "
        "documentation exists in this engagement to build and verify an integration against "
        "(PROJECT_STATUS.md Known Issue #4). This class satisfies PaymentProviderPort so the "
        "integration seam is real and discoverable, deliberately not a guessed implementation."
    )

    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)


class ZaadPaymentAdapter(PaymentProviderPort):
    """Interface-complete stub — see module docstring. No merchant account or API documentation
    exists in this engagement to build a verified integration against (Known Issue #4)."""

    _NOT_IMPLEMENTED_MESSAGE = (
        "ZaadPaymentAdapter is not implemented: no real Zaad merchant account or API "
        "documentation exists in this engagement to build and verify an integration against "
        "(PROJECT_STATUS.md Known Issue #4). This class satisfies PaymentProviderPort so the "
        "integration seam is real and discoverable, deliberately not a guessed implementation."
    )

    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent:
        raise NotImplementedError(self._NOT_IMPLEMENTED_MESSAGE)
