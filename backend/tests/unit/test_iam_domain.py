"""Domain-only tests for `iam`'s `User`/`RefreshToken` aggregates. Stdlib `unittest` — no
`pytest` (not an approved dependency, `.claude/rules/workflow.md` #1/#2), matching
`test_transport_ops_student_domain.py`'s established precedent. Covers: value-object
validation, the email-or-phone / org-scoped-role invariants, state transitions (idempotent
no-ops), and domain-event emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.tenancy.principal import Role
from raad.core.time.clock import Clock
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    OrganizationId,
    PhoneNumber,
    RefreshTokenId,
    UserId,
    UserStatus,
    validate_token_hash,
)

VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_TOKEN_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
VALID_TOKEN_HASH = "a" * 64


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


# --- Value objects ----------------------------------------------------------------------


class UserIdTests(unittest.TestCase):
    def test_rejects_non_ulid_shape(self) -> None:
        with self.assertRaises(DomainError):
            UserId("not-a-valid-ulid")

    def test_accepts_well_formed_ulid(self) -> None:
        self.assertEqual(UserId(VALID_USER_ULID).value, VALID_USER_ULID)


class EmailTests(unittest.TestCase):
    def test_rejects_malformed_address(self) -> None:
        with self.assertRaises(DomainError):
            Email("not-an-email")

    def test_normalizes_case_and_whitespace(self) -> None:
        email = Email("  Someone@Example.COM  ")
        self.assertEqual(str(email), "someone@example.com")

    def test_two_differently_cased_inputs_compare_equal(self) -> None:
        # Matters for the users.email global-uniqueness constraint (Database Design §4.3):
        # "A@B.com" and "a@b.com" must be the same value object.
        self.assertEqual(Email("Foo@Bar.com"), Email("foo@bar.com"))


class PhoneNumberTests(unittest.TestCase):
    def test_rejects_non_e164_format(self) -> None:
        with self.assertRaises(DomainError):
            PhoneNumber("0700000000")  # missing leading +country code

    def test_accepts_e164_format(self) -> None:
        self.assertEqual(str(PhoneNumber("+252700000000")), "+252700000000")


class TokenHashValidationTests(unittest.TestCase):
    def test_rejects_wrong_length(self) -> None:
        with self.assertRaises(DomainError):
            validate_token_hash("abc123")

    def test_rejects_non_hex_characters(self) -> None:
        with self.assertRaises(DomainError):
            validate_token_hash("g" * 64)  # 'g' is not hexadecimal

    def test_accepts_valid_sha256_hex_digest(self) -> None:
        validate_token_hash("a" * 64)  # must not raise


# --- User aggregate invariants -----------------------------------------------------------


class UserInvariantTests(unittest.TestCase):
    def test_rejects_user_with_neither_email_nor_phone(self) -> None:
        with self.assertRaises(DomainError):
            User(
                id=UserId(VALID_USER_ULID),
                organization_id=None,
                role=Role.FOUNDER,
                email=None,
                phone=None,
                full_name="No Contact",
                status=UserStatus.ACTIVE,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_org_scoped_role_requires_organization_id(self) -> None:
        with self.assertRaises(DomainError):
            User(
                id=UserId(VALID_USER_ULID),
                organization_id=None,
                role=Role.ORG_ADMIN,
                email=Email("admin@example.com"),
                phone=None,
                full_name="Org Admin",
                status=UserStatus.ACTIVE,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_staff_role_must_not_have_organization_id(self) -> None:
        with self.assertRaises(DomainError):
            User(
                id=UserId(VALID_USER_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                role=Role.FOUNDER,
                email=Email("founder@example.com"),
                phone=None,
                full_name="Founder",
                status=UserStatus.ACTIVE,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_staff_role_with_no_organization_id_is_valid(self) -> None:
        user = User(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.SUPPORT_STAFF,
            email=Email("support@example.com"),
            phone=None,
            full_name="Support",
            status=UserStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(user.organization_id)

    def test_org_scoped_role_with_organization_id_is_valid(self) -> None:
        user = User(
            id=UserId(VALID_USER_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            role=Role.DRIVER,
            email=None,
            phone=PhoneNumber("+252700000000"),
            full_name="Driver",
            status=UserStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(str(user.organization_id), VALID_ORG_ULID)

    def test_phone_only_user_is_valid(self) -> None:
        user = User(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=None,
            phone=PhoneNumber("+252700000000"),
            full_name="Phone Only",
            status=UserStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(user.email)


class UserInviteTests(unittest.TestCase):
    def test_invite_starts_in_invited_status(self) -> None:
        user = User.invite(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("founder@example.com"),
            phone=None,
            full_name="Founder",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(user.status, UserStatus.INVITED)
        self.assertIsNone(user.password_hash)

    def test_invite_records_user_invited_event(self) -> None:
        user = User.invite(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("founder@example.com"),
            phone=None,
            full_name="Founder",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
            actor_id="actor-1",
        )
        events = user.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "UserInvited")

    def test_pull_domain_events_clears_the_buffer(self) -> None:
        user = User.invite(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("founder@example.com"),
            phone=None,
            full_name="Founder",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        first_pull = user.pull_domain_events()
        second_pull = user.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])


class UserStateTransitionTests(unittest.TestCase):
    def make_user(self, status: UserStatus = UserStatus.ACTIVE) -> User:
        return User(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("founder@example.com"),
            phone=None,
            full_name="Founder",
            status=status,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_activate_sets_active_status_and_records_event(self) -> None:
        user = self.make_user(status=UserStatus.INVITED)
        user.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.status, UserStatus.ACTIVE)
        self.assertEqual(user.pull_domain_events()[0].event_type, "UserActivated")

    def test_activate_already_active_user_is_idempotent_no_op(self) -> None:
        user = self.make_user(status=UserStatus.ACTIVE)
        user.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.pull_domain_events(), [])

    def test_disable_sets_disabled_status_and_records_event(self) -> None:
        user = self.make_user(status=UserStatus.ACTIVE)
        user.disable(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.status, UserStatus.DISABLED)
        self.assertEqual(user.pull_domain_events()[0].event_type, "UserDisabled")

    def test_disable_already_disabled_user_is_idempotent_no_op(self) -> None:
        user = self.make_user(status=UserStatus.DISABLED)
        user.disable(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.pull_domain_events(), [])

    def test_record_login_updates_last_login_at_and_records_event(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        user.record_login(clock=FixedClock(now))
        self.assertEqual(user.last_login_at, now)
        self.assertEqual(user.pull_domain_events()[0].event_type, "UserLoggedIn")

    def test_record_login_without_is_new_device_records_only_user_logged_in(self) -> None:
        """ADR-0019: `is_new_device` defaults `False` — the ordinary case."""
        user = self.make_user()
        user.record_login(clock=FixedClock(datetime(2026, 3, 1, tzinfo=timezone.utc)))
        events = user.pull_domain_events()
        self.assertEqual([e.event_type for e in events], ["UserLoggedIn"])

    def test_record_login_with_is_new_device_also_records_suspicious_login(self) -> None:
        """ADR-0019 Decision #6. The domain method itself never determines suspiciousness (it
        has no I/O to compare against prior sessions) — `is_new_device` is resolved by the
        caller and simply controls whether this second event is recorded."""
        user = self.make_user()
        user.record_login(
            clock=FixedClock(datetime(2026, 3, 1, tzinfo=timezone.utc)),
            is_new_device=True,
            device_label="Chrome on Windows",
            ip_address="203.0.113.10",
        )
        events = user.pull_domain_events()
        self.assertEqual(
            [e.event_type for e in events], ["UserLoggedIn", "SuspiciousLoginDetected"]
        )
        suspicious = events[1]
        self.assertEqual(suspicious.payload["device_label"], "Chrome on Windows")
        self.assertEqual(suspicious.payload["ip_address"], "203.0.113.10")
        self.assertEqual(suspicious.payload["actor_id"], str(user.id))

    def test_change_password_hash_rejects_empty_hash(self) -> None:
        user = self.make_user()
        with self.assertRaises(DomainError):
            user.change_password_hash(
                "", clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
            )

    def test_change_password_hash_stores_new_hash_and_records_event(self) -> None:
        user = self.make_user()
        user.change_password_hash(
            "new-hash-value",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(user.password_hash, "new-hash-value")
        self.assertEqual(user.pull_domain_events()[0].event_type, "UserPasswordChanged")

    def test_change_password_hash_clears_password_change_required_flag(self) -> None:
        """ADR-0017: a deliberate password choice satisfies whatever forced-change gate was
        pending."""
        user = self.make_user()
        user.is_password_change_required = True
        user.change_password_hash(
            "new-hash-value",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertFalse(user.is_password_change_required)

    def test_set_temporary_password_hash_rejects_empty_hash(self) -> None:
        user = self.make_user()
        with self.assertRaises(DomainError):
            user.set_temporary_password_hash(
                "", clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
            )

    def test_set_temporary_password_hash_sets_flag_and_records_event(self) -> None:
        user = self.make_user()
        self.assertFalse(user.is_password_change_required)
        user.set_temporary_password_hash(
            "temp-hash-value",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(user.password_hash, "temp-hash-value")
        self.assertTrue(user.is_password_change_required)
        self.assertEqual(
            user.pull_domain_events()[0].event_type, "UserTemporaryPasswordSet"
        )

    def test_enable_mfa_idempotent_no_event_when_already_enabled(self) -> None:
        user = self.make_user()
        user.enable_mfa(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        user.pull_domain_events()
        user.enable_mfa(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.pull_domain_events(), [])

    def test_disable_mfa_idempotent_no_event_when_already_disabled(self) -> None:
        user = self.make_user()
        user.disable_mfa(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(user.pull_domain_events(), [])

    def test_mfa_toggle_round_trip(self) -> None:
        user = self.make_user()
        user.enable_mfa(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertTrue(user.mfa_enabled)
        user.disable_mfa(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertFalse(user.mfa_enabled)


# --- Account lockout (Priority 1 Item 3, PROJECT_STATUS.md) -------------------------------


class AccountLockoutTests(unittest.TestCase):
    def make_user(self) -> User:
        return User(
            id=UserId(VALID_USER_ULID),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("founder@example.com"),
            phone=None,
            full_name="Founder",
            status=UserStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_new_user_is_not_locked(self) -> None:
        user = self.make_user()
        self.assertFalse(user.is_locked(now=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_failed_login_below_threshold_does_not_lock(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(4):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertEqual(user.failed_login_attempts, 4)
        self.assertIsNone(user.locked_until)
        self.assertFalse(user.is_locked(now=now))

    def test_failed_login_reaching_threshold_locks_account(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertEqual(user.failed_login_attempts, 5)
        self.assertEqual(user.locked_until, now + timedelta(minutes=15))
        self.assertTrue(user.is_locked(now=now))

    def test_is_locked_false_once_window_has_elapsed(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        after_window = now + timedelta(minutes=15, seconds=1)
        self.assertFalse(user.is_locked(now=after_window))

    def test_is_locked_true_exactly_at_boundary_is_false(self) -> None:
        # `is_locked` uses a strict `>` comparison — the exact expiry instant itself counts
        # as already unlocked, not the last locked instant.
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertFalse(user.is_locked(now=user.locked_until))

    def test_failed_login_after_window_elapsed_resets_counter_before_incrementing(
        self,
    ) -> None:
        user = self.make_user()
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(start)
            )
        self.assertTrue(user.is_locked(now=start))

        # A single failed attempt long after the lockout window has elapsed must not
        # immediately re-lock the account from a stale high count — it starts a fresh episode.
        much_later = start + timedelta(hours=1)
        user.record_failed_login(
            max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(much_later)
        )
        self.assertEqual(user.failed_login_attempts, 1)
        self.assertIsNone(user.locked_until)
        self.assertFalse(user.is_locked(now=much_later))

    def test_record_failed_login_records_user_login_failed_event(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        user.record_failed_login(
            max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
        )
        events = user.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "UserLoginFailed")
        self.assertEqual(events[0].payload["failed_login_attempts"], 1)
        self.assertIsNone(events[0].payload["locked_until"])

    def test_record_failed_login_event_payload_carries_locked_until_on_lock(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(4):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        user.pull_domain_events()
        user.record_failed_login(
            max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
        )
        event = user.pull_domain_events()[0]
        self.assertEqual(event.payload["failed_login_attempts"], 5)
        self.assertEqual(
            event.payload["locked_until"], (now + timedelta(minutes=15)).isoformat()
        )

    def test_record_login_clears_lockout_state(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertTrue(user.is_locked(now=now))
        user.record_login(clock=FixedClock(now))
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)
        self.assertFalse(user.is_locked(now=now))

    def test_change_password_hash_clears_lockout_state(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertTrue(user.is_locked(now=now))
        user.change_password_hash("new-hash", clock=FixedClock(now))
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)

    def test_set_temporary_password_hash_clears_lockout_state(self) -> None:
        user = self.make_user()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for _ in range(5):
            user.record_failed_login(
                max_attempts=5, lockout_duration_minutes=15, clock=FixedClock(now)
            )
        self.assertTrue(user.is_locked(now=now))
        user.set_temporary_password_hash("temp-hash", clock=FixedClock(now))
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.locked_until)


# --- RefreshToken aggregate ---------------------------------------------------------------


class RefreshTokenTests(unittest.TestCase):
    def test_rejects_expires_at_before_issued_at(self) -> None:
        issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            RefreshToken(
                id=RefreshTokenId(VALID_TOKEN_ULID),
                user_id=UserId(VALID_USER_ULID),
                token_hash=VALID_TOKEN_HASH,
                issued_at=issued,
                expires_at=issued - timedelta(seconds=1),
            )

    def test_rejects_expires_at_equal_to_issued_at(self) -> None:
        issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            RefreshToken(
                id=RefreshTokenId(VALID_TOKEN_ULID),
                user_id=UserId(VALID_USER_ULID),
                token_hash=VALID_TOKEN_HASH,
                issued_at=issued,
                expires_at=issued,
            )

    def test_rejects_malformed_token_hash(self) -> None:
        issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(DomainError):
            RefreshToken(
                id=RefreshTokenId(VALID_TOKEN_ULID),
                user_id=UserId(VALID_USER_ULID),
                token_hash="too-short",
                issued_at=issued,
                expires_at=issued + timedelta(days=14),
            )

    def test_issue_records_refresh_token_issued_event(self) -> None:
        token = RefreshToken.issue(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            expires_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        events = token.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "RefreshTokenIssued")

    def test_issue_defaults_device_fields_to_none(self) -> None:
        token = RefreshToken.issue(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            expires_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertIsNone(token.user_agent)
        self.assertIsNone(token.ip_address)
        self.assertIsNone(token.device_label)

    def test_issue_stores_captured_device_fields(self) -> None:
        """ADR-0019: `user_agent`/`ip_address` (previously dead ORM columns) and the new
        `device_label` are captured from the issuing request for the first time."""
        token = RefreshToken.issue(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            expires_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
            user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
            ip_address="203.0.113.10",
            device_label="Chrome on Windows",
        )
        self.assertEqual(token.user_agent, "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0")
        self.assertEqual(token.ip_address, "203.0.113.10")
        self.assertEqual(token.device_label, "Chrome on Windows")

    def test_is_expired_true_after_expiry_time(self) -> None:
        token = RefreshToken(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        self.assertTrue(
            token.is_expired(
                clock=FixedClock(datetime(2026, 1, 3, tzinfo=timezone.utc))
            )
        )

    def test_is_expired_false_before_expiry_time(self) -> None:
        token = RefreshToken(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        self.assertFalse(
            token.is_expired(
                clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc))
            )
        )

    def test_revoke_sets_revoked_at_and_records_event(self) -> None:
        token = RefreshToken(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        token.revoke(clock=FixedClock(now))
        self.assertTrue(token.is_revoked)
        self.assertEqual(token.revoked_at, now)
        self.assertEqual(
            token.pull_domain_events()[0].event_type, "RefreshTokenRevoked"
        )

    def test_revoke_already_revoked_token_is_idempotent_no_op(self) -> None:
        token = RefreshToken(
            id=RefreshTokenId(VALID_TOKEN_ULID),
            user_id=UserId(VALID_USER_ULID),
            token_hash=VALID_TOKEN_HASH,
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            revoked_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        token.revoke(clock=FixedClock(datetime(2026, 1, 5, tzinfo=timezone.utc)))
        self.assertEqual(token.pull_domain_events(), [])
        # Original revocation time preserved - a second revoke() must not overwrite it.
        self.assertEqual(token.revoked_at, datetime(2026, 1, 2, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
