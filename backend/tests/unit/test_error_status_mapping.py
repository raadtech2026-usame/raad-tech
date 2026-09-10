"""`core.errors.handlers.resolve_status` — the exception → HTTP status table.

**Why this file exists.** `DomainError` was missing from the table and fell through to the `500`
default, so every business-rule refusal in the codebase answered with a server-fault status: a
correct, specific message ("Category 'Fuel' is an expense category, not an income category")
served as if the API had crashed. Live-reproduced against `POST /school-finance/income`. That
matters beyond tidiness — a 500 is logged as `unhandled_app_error`, is what an on-call alert
watches for, and tells every client the request may be retried unchanged when it never will
succeed.

The ordering assertions are the real content: the table is walked most-specific-first, so adding
a base class above its own subclasses silently reclassifies them.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.handlers import resolve_status
from raad.core.errors.exceptions import (
    AccountLockedError,
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainError,
    ExternalServiceError,
    InfrastructureError,
    NotFoundError,
    OrganizationSubscriptionInactiveError,
    ParentAccessDeniedError,
    PaymentError,
    RateLimitedError,
    RuleViolationError,
    ValidationError,
    VideoForbiddenError,
)

#: (exception, expected status). Subclasses are listed alongside their bases deliberately — the
#: point of most of these rows is that the more specific one still wins.
_CASES = [
    (DomainError("business rule refused the input"), 400),
    (ConflictError("already exists"), 409),
    (RuleViolationError("invariant violated"), 409),
    (ValidationError("bad shape"), 422),
    (AuthenticationError("no token"), 401),
    (AccountLockedError(locked_until=datetime(2026, 9, 8, tzinfo=timezone.utc)), 401),
    (AuthorizationError("not permitted"), 403),
    (
        ParentAccessDeniedError(reason="assignment ended", required_action=None),
        403,
    ),
    (VideoForbiddenError("no video grant"), 403),
    (OrganizationSubscriptionInactiveError("suspended"), 403),
    (NotFoundError("missing"), 404),
    (PaymentError("declined"), 402),
    (RateLimitedError("too many requests"), 429),
    (ExternalServiceError("provider down"), 502),
    (InfrastructureError("disk full"), 500),
]


class ResolveStatusTests(unittest.TestCase):
    def test_every_error_class_maps_to_its_documented_status(self) -> None:
        for error, expected in _CASES:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(resolve_status(error), expected)

    def test_a_plain_domain_error_is_a_client_error_not_a_server_fault(self) -> None:
        """The specific regression: a business rule refusing input is the caller's problem."""
        self.assertLess(resolve_status(DomainError("amount must not be negative")), 500)

    def test_domain_error_subclasses_keep_their_own_narrower_status(self) -> None:
        """Placing `DomainError` above these in the table would silently turn both into 400."""
        self.assertTrue(issubclass(ConflictError, DomainError))
        self.assertTrue(issubclass(RuleViolationError, DomainError))
        self.assertEqual(resolve_status(ConflictError("dup")), 409)
        self.assertEqual(resolve_status(RuleViolationError("bad")), 409)

    def test_an_unclassified_app_error_still_falls_back_to_500(self) -> None:
        """The default must stay a server fault: an error nobody classified is not understood,
        and guessing 400 for it would hide a real defect behind a client-error status."""

        class _Unclassified(AppError):
            code = "UNCLASSIFIED"

        self.assertEqual(resolve_status(_Unclassified("?")), 500)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
