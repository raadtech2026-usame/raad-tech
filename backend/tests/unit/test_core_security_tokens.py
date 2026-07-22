"""Unit tests for `core.security.tokens.resolve_principal_from_access_token` — the single
shared "raw bearer token string -> `Principal`" resolver both `interfaces/http/middleware.
SecurityContextMiddleware` (HTTP requests) and `interfaces/http/realtime.authenticate_connection`
(`/ws/tracking`/`/ws/notifications`) call, per the WebSocket phase's "do not duplicate
authentication logic" instruction. Stdlib `unittest` — no `pytest` (not an approved dependency).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.security.claims import TokenType
from raad.core.security.tokens import JwtTokenService, resolve_principal_from_access_token
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def make_token_service(clock: Clock) -> JwtTokenService:
    return JwtTokenService(
        secret_key="test-secret-key",
        algorithm="HS256",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=1_209_600,
        clock=clock,
    )


class ResolvePrincipalFromAccessTokenTests(unittest.TestCase):
    def test_valid_access_token_resolves_matching_principal(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(
            subject="01J8Z3K9G6X8YV5T4N2R7QW3US", role=Role.ORG_ADMIN, org_id="org-1"
        )

        principal = resolve_principal_from_access_token(service, pair.access_token)

        self.assertEqual(
            principal,
            Principal(user_id="01J8Z3K9G6X8YV5T4N2R7QW3US", role=Role.ORG_ADMIN, org_id="org-1"),
        )

    def test_founder_token_has_no_org_id(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(subject="founder-1", role=Role.FOUNDER, org_id=None)

        principal = resolve_principal_from_access_token(service, pair.access_token)

        self.assertIsNotNone(principal)
        assert principal is not None
        self.assertIsNone(principal.org_id)

    def test_expired_access_token_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(subject="user-1", role=Role.PARENT, org_id="org-1")

        clock.advance(timedelta(seconds=901))  # past the 900s access TTL

        self.assertIsNone(resolve_principal_from_access_token(service, pair.access_token))

    def test_malformed_token_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)

        self.assertIsNone(resolve_principal_from_access_token(service, "not-a-jwt"))

    def test_tampered_signature_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(subject="user-1", role=Role.DRIVER, org_id="org-1")
        header, payload, signature = pair.access_token.split(".")
        tampered = f"{header}.{payload}.{signature[:-2]}xx"

        self.assertIsNone(resolve_principal_from_access_token(service, tampered))

    def test_refresh_token_presented_as_access_returns_none(self) -> None:
        """A refresh token must never resolve a `Principal` at this entry point — matching
        `TokenService.decode`'s own `expected_type=TokenType.ACCESS` contract, the same rule
        `AuthApplicationService.refresh_access_token` enforces for the HTTP `/auth/refresh`
        flow, applied identically here."""
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        service = make_token_service(clock)
        pair = service.issue_token_pair(subject="user-1", role=Role.PARENT, org_id="org-1")

        self.assertIsNone(resolve_principal_from_access_token(service, pair.refresh_token))

    def test_wrong_signing_key_returns_none(self) -> None:
        clock = FixedClock(datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc))
        issuer = JwtTokenService(
            secret_key="issuer-secret",
            algorithm="HS256",
            access_token_ttl_seconds=900,
            refresh_token_ttl_seconds=1_209_600,
            clock=clock,
        )
        verifier = JwtTokenService(
            secret_key="different-secret",
            algorithm="HS256",
            access_token_ttl_seconds=900,
            refresh_token_ttl_seconds=1_209_600,
            clock=clock,
        )
        pair = issuer.issue_token_pair(subject="user-1", role=Role.PARENT, org_id="org-1")

        self.assertIsNone(resolve_principal_from_access_token(verifier, pair.access_token))


if __name__ == "__main__":
    unittest.main()
