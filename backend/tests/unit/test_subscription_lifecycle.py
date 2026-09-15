"""ADR-0039 — organization subscription lifecycle and tenant-wide access enforcement.

Covers the requirement-39U scenario list. Grouped by the layer each scenario actually exercises,
because that is what determines what a failure means:

- `OrganizationAccessPolicyTests` — the pure decision table (no I/O, no DI, no HTTP).
- `SubscriptionLifecycleTransitionTests` — the domain aggregate's own guards and idempotency.
- `AdvanceSubscriptionLifecycleTests` — the scheduled job, against in-memory repositories.
- `SubscriptionGuardTests` — the HTTP/WebSocket enforcement seam, against a fake container.

Reuses `test_billing_application`'s existing in-memory repositories and fake UoW rather than
building a second, parallel set of doubles — a second set would be free to drift from the real
repository contract in exactly the way the fake-vs-real gaps this codebase has already been
bitten by (CLAUDE.md's own "a fake can't catch a real wiring gap" lesson) tend to appear.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import (
    DomainError,
    OrganizationSubscriptionInactiveError,
)
from raad.core.policies.organization_access import (
    ORGANIZATION_SUBSCRIPTION_INACTIVE,
    ORGANIZATION_SUBSCRIPTION_MISSING,
    OrganizationAccessPolicy,
    OrganizationSubscriptionState,
)
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.subscription_guard import (
    _EXEMPT_PATH_PREFIXES,
    _PLATFORM_ROLES,
    enforce_organization_subscription,
    is_organization_access_allowed,
)
from raad.modules.billing.application.commands import (
    ExtendGracePeriodCommand,
    ReactivateSubscriptionCommand,
)
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.entities import Invoice, Plan, Subscription
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId,
    PlanId,
    SubscriptionId,
    SubscriptionStatus,
)

from tests.unit.test_billing_application import (
    CLOCK,
    FixedClock,
    SequentialIdGenerator,
    make_uow,
)

ORG_A = "01J8Z3K9G6X8YV5T4N2RAAAAA1"
ORG_B = "01J8Z3K9G6X8YV5T4N2RBBBBB2"
PLAN_ID = "01J8Z3K9G6X8YV5T4N2RPPPPP3"
SUB_ID = "01J8Z3K9G6X8YV5T4N2RSSSSS4"


def _principal(role: Role, org_id: str | None = ORG_A) -> Principal:
    return Principal(
        user_id="01J8Z3K9G6X8YV5T4N2REEEEE5",
        role=role,
        org_id=org_id,
    )


def _plan(clock=CLOCK) -> Plan:
    return Plan.create(
        id=PlanId(PLAN_ID),
        name="Standard",
        billing_scope=BillingScope.ORGANIZATION,
        price=Money(100.0, "USD"),
        billing_cycle=BillingCycle.MONTHLY,
        vehicle_limit=10,
        clock=clock,
    )


def _subscription(
    *,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    period_end: datetime | None = None,
    auto_renew: bool = True,
    grace_period_ends_at: datetime | None = None,
    organization_id: str = ORG_A,
    subscription_id: str = SUB_ID,
    clock=CLOCK,
) -> Subscription:
    now = clock.now()
    return Subscription(
        id=SubscriptionId(subscription_id),
        organization_id=OrganizationId(organization_id),
        plan_id=PlanId(PLAN_ID),
        status=status,
        current_period_start=now - timedelta(days=30),
        current_period_end=period_end,
        auto_renew=auto_renew,
        created_at=now,
        updated_at=now,
        grace_period_ends_at=grace_period_ends_at,
    )


# =============================================================================================
# The pure decision table (requirement 39D)
# =============================================================================================


class OrganizationAccessPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OrganizationAccessPolicy()

    def test_granting_states_allow_a_tenant_user(self) -> None:
        """TRIAL/ACTIVE/GRACE_PERIOD grant (amended 2026-09-09).

        `GRACE_PERIOD` still grants and that is deliberate: a grace period that does not grant
        access is not a grace period, it is a slower suspension, and the lifecycle would have no
        state left meaning "we know you are late, keep working while you sort it out". Access
        ends when grace *ends*. `PAST_DUE` moved to the denying set — see the test below.
        """
        for state in (
            OrganizationSubscriptionState.TRIAL,
            OrganizationSubscriptionState.ACTIVE,
            OrganizationSubscriptionState.GRACE_PERIOD,
        ):
            with self.subTest(state=state):
                decision = self.policy.evaluate(
                    subscription_state=state, is_platform_role=False
                )
                self.assertTrue(decision.allowed)

    def test_past_due_denies(self) -> None:
        """Amended 2026-09-09 (direct user directive): an unpaid invoice closes the dashboard.

        This was the widest hole in the enforcement — `past_due` literally means unpaid and past
        the due date, yet it granted full access, and nothing escalated it without the scheduled
        sweep completing. A tenant could simply stop paying and keep working indefinitely.
        """
        decision = self.policy.evaluate(
            subscription_state=OrganizationSubscriptionState.PAST_DUE,
            is_platform_role=False,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, ORGANIZATION_SUBSCRIPTION_INACTIVE)
        self.assertEqual(decision.required_action, "REDIRECT_TO_PAYMENT")

    def test_terminal_states_deny_a_tenant_user(self) -> None:
        """Scenarios 4 and 14: SUSPENDED and EXPIRED both block. CANCELLED too."""
        for state in (
            OrganizationSubscriptionState.SUSPENDED,
            OrganizationSubscriptionState.EXPIRED,
            OrganizationSubscriptionState.CANCELLED,
        ):
            with self.subTest(state=state):
                decision = self.policy.evaluate(
                    subscription_state=state, is_platform_role=False
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, ORGANIZATION_SUBSCRIPTION_INACTIVE)
                self.assertEqual(decision.required_action, "REDIRECT_TO_PAYMENT")

    def test_platform_role_is_allowed_in_every_state(self) -> None:
        """Scenario 10: Platform Admin keeps access to a suspended organization. Without this,
        suspension would be irreversible — nobody could inspect or reactivate a tenant."""
        for state in list(OrganizationSubscriptionState) + [None]:
            with self.subTest(state=state):
                self.assertTrue(
                    self.policy.evaluate(
                        subscription_state=state, is_platform_role=True
                    ).allowed
                )

    def test_no_subscription_row_denies_with_its_own_reason(self) -> None:
        """Amended 2026-09-09: `None` denies, and says so distinctly.

        It used to grant, reasoning that a never-subscribed organization is un-onboarded rather
        than delinquent and that denying would turn a provisioning bug into a total outage. The
        reasoning was sound and the outcome was still wrong: a provisioning bug is exactly what
        happened — subscription creation failed on every call for the life of the feature — and
        this fail-open is what made it invisible. Every organization had unrestricted access with
        no subscription and nothing reported it.

        The reason code is deliberately *not* the lapsed-subscription one: "nobody ever sold this
        school a plan" is a provisioning problem and "they stopped paying" is a billing one, and
        the operator action differs.
        """
        decision = self.policy.evaluate(subscription_state=None, is_platform_role=False)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, ORGANIZATION_SUBSCRIPTION_MISSING)
        self.assertEqual(decision.required_action, "REDIRECT_TO_PAYMENT")

    def test_no_subscription_but_trialing_grants(self) -> None:
        """Organization Lifecycle / Trial workflow: a trial defers subscription/plan selection
        entirely, so the common trialing organization has no `Subscription` row yet at all —
        `is_trialing=True` re-admits exactly this legitimate case, distinguishable from the
        provisioning-bug case the test above covers."""
        decision = self.policy.evaluate(
            subscription_state=None, is_platform_role=False, is_trialing=True
        )
        self.assertTrue(decision.allowed)

    def test_is_trialing_is_ignored_once_a_real_subscription_exists(self) -> None:
        """A trialing organization that also has a real (e.g. suspended) subscription is judged
        by that subscription alone — `is_trialing` must never reopen access for an unrelated,
        stale trial flag left set from an earlier phase of the same organization's life."""
        decision = self.policy.evaluate(
            subscription_state=OrganizationSubscriptionState.SUSPENDED,
            is_platform_role=False,
            is_trialing=True,
        )
        self.assertFalse(decision.allowed)

    def test_only_the_three_documented_states_grant(self) -> None:
        """Exhaustive: every state not explicitly granted must deny.

        Written as a closed sweep over the enum rather than a list of cases, so adding a new
        subscription state fails here until someone decides, on purpose, which side it belongs
        on — the alternative is a new state silently defaulting to whichever branch it hits.
        """
        granting = {
            OrganizationSubscriptionState.TRIAL,
            OrganizationSubscriptionState.ACTIVE,
            OrganizationSubscriptionState.GRACE_PERIOD,
        }
        for state in OrganizationSubscriptionState:
            with self.subTest(state=state):
                allowed = self.policy.evaluate(
                    subscription_state=state, is_platform_role=False
                ).allowed
                self.assertEqual(allowed, state in granting)


# =============================================================================================
# Domain transitions (requirements 39C/39D)
# =============================================================================================


class SubscriptionLifecycleTransitionTests(unittest.TestCase):
    def test_mark_past_due_sets_the_grace_clock_once_and_only_once(self) -> None:
        """The grace deadline must not move on a repeat call. If it did, a job ticking every
        minute would push the deadline forward every minute and the organization would never
        actually suspend — the lifecycle would look implemented while being inert."""
        subscription = _subscription()
        first_deadline = CLOCK.now() + timedelta(days=7)
        subscription.mark_past_due(
            grace_period_ends_at=first_deadline, clock=CLOCK, actor_id="system"
        )
        self.assertEqual(subscription.status, SubscriptionStatus.PAST_DUE)
        self.assertEqual(subscription.grace_period_ends_at, first_deadline)
        subscription.pull_domain_events()

        subscription.mark_past_due(
            grace_period_ends_at=CLOCK.now() + timedelta(days=99),
            clock=CLOCK,
            actor_id="system",
        )
        self.assertEqual(subscription.grace_period_ends_at, first_deadline)
        self.assertEqual(subscription.pull_domain_events(), [])

    def test_extend_grace_period_moves_to_granted_state_and_is_repeatable(self) -> None:
        subscription = _subscription(status=SubscriptionStatus.PAST_DUE)
        first = CLOCK.now() + timedelta(days=3)
        second = CLOCK.now() + timedelta(days=10)
        subscription.extend_grace_period(
            grace_period_ends_at=first, clock=CLOCK, actor_id="founder"
        )
        self.assertEqual(subscription.status, SubscriptionStatus.GRACE_PERIOD)
        subscription.extend_grace_period(
            grace_period_ends_at=second, clock=CLOCK, actor_id="founder"
        )
        self.assertEqual(subscription.grace_period_ends_at, second)
        events = [e.event_type for e in subscription.pull_domain_events()]
        self.assertEqual(events.count("SubscriptionGracePeriodExtended"), 2)

    def test_extend_grace_period_refuses_terminal_states(self) -> None:
        for status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
            with self.subTest(status=status):
                with self.assertRaises(DomainError):
                    _subscription(status=status).extend_grace_period(
                        grace_period_ends_at=CLOCK.now() + timedelta(days=1),
                        clock=CLOCK,
                        actor_id="founder",
                    )

    def test_reactivate_restores_active_and_clears_the_delinquency_clocks(self) -> None:
        """Scenario 13. `grace_period_ends_at` must be cleared, or the next lifecycle tick
        would immediately re-suspend the organization that was just reactivated."""
        subscription = _subscription(
            status=SubscriptionStatus.SUSPENDED,
            grace_period_ends_at=CLOCK.now() - timedelta(days=1),
        )
        subscription.suspended_at = CLOCK.now()
        subscription.reactivate(clock=CLOCK, actor_id="founder")
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertIsNone(subscription.grace_period_ends_at)
        self.assertIsNone(subscription.past_due_since)
        self.assertIsNone(subscription.suspended_at)

    def test_reactivate_refuses_terminal_states(self) -> None:
        for status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
            with self.subTest(status=status):
                with self.assertRaises(DomainError):
                    _subscription(status=status).reactivate(
                        clock=CLOCK, actor_id="founder"
                    )

    def test_renew_clears_the_delinquency_clocks(self) -> None:
        """Scenario 15. A subscription that was past-due and then genuinely pays must be fully
        rehabilitated — a stale `grace_period_ends_at` would suspend a paying customer."""
        subscription = _subscription(
            status=SubscriptionStatus.PAST_DUE,
            grace_period_ends_at=CLOCK.now() - timedelta(days=1),
        )
        subscription.past_due_since = CLOCK.now() - timedelta(days=8)
        subscription.renew(
            period_start=CLOCK.now(),
            period_end=CLOCK.now() + timedelta(days=30),
            clock=CLOCK,
        )
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertIsNone(subscription.grace_period_ends_at)
        self.assertIsNone(subscription.past_due_since)

    def test_suspend_and_expire_record_their_timestamps(self) -> None:
        suspended = _subscription()
        suspended.suspend(clock=CLOCK, actor_id="system")
        self.assertEqual(suspended.suspended_at, CLOCK.now())

        expired = _subscription()
        expired.expire(clock=CLOCK, actor_id="system")
        self.assertEqual(expired.expired_at, CLOCK.now())


# =============================================================================================
# The scheduled lifecycle job (requirements 39F/39J)
# =============================================================================================


def _service(clock=CLOCK) -> BillingApplicationService:
    return BillingApplicationService(
        clock=clock, id_generator=SequentialIdGenerator(), payment_provider=None
    )


def _seed(uow, subscription: Subscription, *, with_unpaid_invoice: bool = False) -> None:
    uow.plans.add(_plan())
    uow.subscriptions.add(subscription)
    if with_unpaid_invoice:
        uow.invoices.add(
            Invoice.issue(
                id=InvoiceId("01J8Z3K9G6X8YV5T4N2RNNNNN8"),
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                amount=Money(100.0, "USD"),
                period_start=(CLOCK.now() - timedelta(days=30)).date(),
                period_end=CLOCK.now().date(),
                due_at=None,
                clock=CLOCK,
            )
        )


class AdvanceSubscriptionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_period_ended_with_an_unpaid_invoice_goes_past_due(self) -> None:
        """Scenario 2. The organization keeps working — this is the start of grace, not the
        end of access."""
        uow = make_uow()
        subscription = _subscription(period_end=CLOCK.now() - timedelta(days=1))
        _seed(uow, subscription, with_unpaid_invoice=True)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["past_due"], 1)
        self.assertEqual(subscription.status, SubscriptionStatus.PAST_DUE)
        self.assertEqual(
            subscription.grace_period_ends_at, CLOCK.now() + timedelta(days=7)
        )

    async def test_grace_expiry_suspends(self) -> None:
        """Scenarios 3 and 4: grace runs, then suspension."""
        uow = make_uow()
        subscription = _subscription(
            status=SubscriptionStatus.PAST_DUE,
            period_end=CLOCK.now() - timedelta(days=10),
            grace_period_ends_at=CLOCK.now() - timedelta(minutes=1),
        )
        _seed(uow, subscription, with_unpaid_invoice=True)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["suspended"], 1)
        self.assertEqual(subscription.status, SubscriptionStatus.SUSPENDED)

    async def test_grace_still_running_does_not_suspend(self) -> None:
        uow = make_uow()
        subscription = _subscription(
            status=SubscriptionStatus.PAST_DUE,
            period_end=CLOCK.now() - timedelta(days=1),
            grace_period_ends_at=CLOCK.now() + timedelta(days=3),
        )
        _seed(uow, subscription, with_unpaid_invoice=True)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["suspended"], 0)
        self.assertEqual(subscription.status, SubscriptionStatus.PAST_DUE)

    async def test_settled_period_renews_and_issues_the_next_invoice(self) -> None:
        """The half of the lifecycle that never existed before ADR-0039: rolling into the next
        billing period at all. Previously a period could only ever end, never renew."""
        uow = make_uow()
        subscription = _subscription(period_end=CLOCK.now() - timedelta(days=1))
        _seed(uow, subscription, with_unpaid_invoice=False)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["renewed"], 1)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(len(await uow.invoices.list_all()), 1)

    async def test_settled_period_without_auto_renew_expires(self) -> None:
        uow = make_uow()
        subscription = _subscription(
            period_end=CLOCK.now() - timedelta(days=1), auto_renew=False
        )
        _seed(uow, subscription, with_unpaid_invoice=False)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["expired"], 1)
        self.assertEqual(subscription.status, SubscriptionStatus.EXPIRED)

    async def test_a_live_period_is_left_alone(self) -> None:
        uow = make_uow()
        subscription = _subscription(period_end=CLOCK.now() + timedelta(days=10))
        _seed(uow, subscription, with_unpaid_invoice=True)

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts, {"past_due": 0, "renewed": 0, "suspended": 0, "expired": 0})
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(uow.commit_count, 0)

    async def test_the_job_is_idempotent(self) -> None:
        """Scenario 17, and requirement 39J's "safe to run repeatedly". The second run must be a
        complete no-op — no second invoice, no second transition, no commit."""
        uow = make_uow()
        subscription = _subscription(period_end=CLOCK.now() - timedelta(days=1))
        _seed(uow, subscription, with_unpaid_invoice=False)
        service = _service()

        first = await service.advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )
        invoices_after_first = len(await uow.invoices.list_all())
        commits_after_first = uow.commit_count

        second = await service.advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(first["renewed"], 1)
        self.assertEqual(second, {"past_due": 0, "renewed": 0, "suspended": 0, "expired": 0})
        self.assertEqual(len(await uow.invoices.list_all()), invoices_after_first)
        self.assertEqual(uow.commit_count, commits_after_first)

    async def test_a_missing_plan_is_skipped_not_expired(self) -> None:
        """A subscription pointing at a deleted plan cannot be priced. Expiring the tenant over
        RAAD's own data-integrity problem would punish the customer for our bug."""
        uow = make_uow()
        subscription = _subscription(period_end=CLOCK.now() - timedelta(days=1))
        uow.subscriptions.add(subscription)  # deliberately no plan seeded

        counts = await _service().advance_subscription_lifecycle(
            grace_period_days=7, uow=uow
        )

        self.assertEqual(counts["renewed"], 0)
        self.assertEqual(counts["expired"], 0)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)

    async def test_tenant_isolation_each_organization_transitions_independently(
        self,
    ) -> None:
        """Scenario 23. One organization suspending must not touch another's state."""
        uow = make_uow()
        delinquent = _subscription(
            organization_id=ORG_A,
            subscription_id="01J8Z3K9G6X8YV5T4N2RSSSSA6",
            period_end=CLOCK.now() - timedelta(days=1),
        )
        healthy = _subscription(
            organization_id=ORG_B,
            subscription_id="01J8Z3K9G6X8YV5T4N2RSSSSB7",
            period_end=CLOCK.now() + timedelta(days=20),
        )
        _seed(uow, delinquent, with_unpaid_invoice=True)
        uow.subscriptions.add(healthy)

        await _service().advance_subscription_lifecycle(grace_period_days=7, uow=uow)

        self.assertEqual(delinquent.status, SubscriptionStatus.PAST_DUE)
        self.assertEqual(healthy.status, SubscriptionStatus.ACTIVE)

    async def test_reactivation_restores_access_end_to_end(self) -> None:
        """Scenarios 12 and 13, through the application service rather than the aggregate."""
        uow = make_uow()
        subscription = _subscription(
            status=SubscriptionStatus.SUSPENDED,
            period_end=CLOCK.now() + timedelta(days=10),
            grace_period_ends_at=CLOCK.now() - timedelta(days=1),
        )
        _seed(uow, subscription)

        dto = await _service().reactivate_subscription(
            ReactivateSubscriptionCommand(
                subscription_id=str(subscription.id),
                actor=_principal(Role.FOUNDER, org_id=None),
            ),
            uow=uow,
        )

        self.assertEqual(dto.status, "active")
        self.assertIsNone(dto.grace_period_ends_at)

    async def test_extend_grace_period_through_the_service(self) -> None:
        uow = make_uow()
        subscription = _subscription(
            status=SubscriptionStatus.PAST_DUE,
            period_end=CLOCK.now() - timedelta(days=1),
            grace_period_ends_at=CLOCK.now() + timedelta(days=1),
        )
        _seed(uow, subscription)
        new_deadline = CLOCK.now() + timedelta(days=30)

        dto = await _service().extend_grace_period(
            ExtendGracePeriodCommand(
                subscription_id=str(subscription.id),
                grace_period_ends_at=new_deadline,
                actor=_principal(Role.FOUNDER, org_id=None),
            ),
            uow=uow,
        )

        self.assertEqual(dto.status, "grace_period")
        self.assertEqual(dto.grace_period_ends_at, new_deadline)

    async def test_get_current_subscription_sees_terminal_states(self) -> None:
        """The bug this guards against: `get_active_by_organization` hides EXPIRED behind a
        `None`, which the access policy reads as "never subscribed" and grants. Enforcement must
        use the finder that hides nothing, or expired organizations keep full access."""
        uow = make_uow()
        subscription = _subscription(status=SubscriptionStatus.EXPIRED)
        _seed(uow, subscription)

        current = await _service().get_current_subscription_for_organization(
            ORG_A, uow=uow
        )
        active = await _service().get_active_subscription_for_organization(
            ORG_A, uow=uow
        )

        self.assertIsNotNone(current)
        self.assertEqual(current.status, "expired")
        self.assertIsNone(active)


# =============================================================================================
# HTTP / WebSocket enforcement (requirements 39E/39G/39K/39M)
# =============================================================================================


class _FakeContainer:
    """Minimal container double. Deliberately supports `try_resolve` returning `None` for an
    unbound key, so the "no billing subsystem deployed" path is exercised for real."""

    def __init__(self, bindings: dict) -> None:
        self._bindings = bindings

    def resolve(self, key):
        if key not in self._bindings:
            raise LookupError(key)
        return self._bindings[key]

    def try_resolve(self, key):
        return self._bindings.get(key)


class _FakeRequest:
    def __init__(self, path: str, principal: Principal | None) -> None:
        self.url = type("U", (), {"path": path})()
        self.state = type("S", (), {"principal": principal})()


def _container_for(subscription: Subscription | None) -> _FakeContainer:
    from raad.modules.billing.application.ports import BillingUnitOfWork

    uow = make_uow()
    if subscription is not None:
        uow.subscriptions.add(subscription)
    return _FakeContainer(
        {
            OrganizationAccessPolicy: OrganizationAccessPolicy(),
            BillingApplicationService: _service(),
            BillingUnitOfWork: uow,
        }
    )


class SubscriptionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_organization_passes(self) -> None:
        """Scenario 1."""
        container = _container_for(_subscription(status=SubscriptionStatus.ACTIVE))
        await enforce_organization_subscription(
            _FakeRequest("/api/v1/vehicles", _principal(Role.ORG_ADMIN)),
            container=container,
        )  # must not raise

    async def test_every_tenant_role_is_blocked_when_suspended(self) -> None:
        """Scenarios 5-9: Org Admin, Driver and Parent are all blocked. The organization is the
        tenant, so suspension applies to the whole tenant — not just its admin."""
        for role in (Role.ORG_ADMIN, Role.DRIVER, Role.PARENT):
            with self.subTest(role=role):
                container = _container_for(
                    _subscription(status=SubscriptionStatus.SUSPENDED)
                )
                with self.assertRaises(OrganizationSubscriptionInactiveError) as ctx:
                    await enforce_organization_subscription(
                        _FakeRequest("/api/v1/vehicles", _principal(role)),
                        container=container,
                    )
                self.assertEqual(
                    ctx.exception.code, "ORGANIZATION_SUBSCRIPTION_INACTIVE"
                )

    async def test_expired_organization_is_blocked(self) -> None:
        """Scenario 14 — the state that would have slipped through had enforcement used
        `get_active_by_organization`."""
        container = _container_for(_subscription(status=SubscriptionStatus.EXPIRED))
        with self.assertRaises(OrganizationSubscriptionInactiveError):
            await enforce_organization_subscription(
                _FakeRequest("/api/v1/students", _principal(Role.ORG_ADMIN)),
                container=container,
            )

    async def test_platform_roles_are_never_blocked(self) -> None:
        """Scenarios 10 and 11."""
        for role in _PLATFORM_ROLES:
            with self.subTest(role=role):
                container = _container_for(
                    _subscription(status=SubscriptionStatus.SUSPENDED)
                )
                await enforce_organization_subscription(
                    _FakeRequest("/api/v1/organizations", _principal(role, org_id=None)),
                    container=container,
                )  # must not raise

    async def test_exempt_paths_stay_reachable_while_suspended(self) -> None:
        """`/billing` is the recovery path — an Org Admin who cannot reach it could never pay,
        making suspension permanent and self-sealing. `/auth` keeps the state diagnosable and
        `/me` lets the caller learn why they are blocked."""
        for prefix in _EXEMPT_PATH_PREFIXES:
            with self.subTest(prefix=prefix):
                container = _container_for(
                    _subscription(status=SubscriptionStatus.SUSPENDED)
                )
                await enforce_organization_subscription(
                    _FakeRequest(f"{prefix}/anything", _principal(Role.ORG_ADMIN)),
                    container=container,
                )  # must not raise

    async def test_unauthenticated_requests_fall_through(self) -> None:
        """`POST /auth/login` carries no principal. This guard must not turn login into a 401 —
        authentication is not its job."""
        container = _container_for(None)
        await enforce_organization_subscription(
            _FakeRequest("/api/v1/auth/login", None), container=container
        )  # must not raise

    async def test_error_detail_is_graded_by_role(self) -> None:
        """Requirement 39K. An Org Admin gets actionable billing state; a Driver gets nothing
        beyond the generic message — a driver has no business reading the school's billing
        position."""
        admin_container = _container_for(
            _subscription(status=SubscriptionStatus.SUSPENDED)
        )
        with self.assertRaises(OrganizationSubscriptionInactiveError) as admin_ctx:
            await enforce_organization_subscription(
                _FakeRequest("/api/v1/vehicles", _principal(Role.ORG_ADMIN)),
                container=admin_container,
            )
        self.assertIsNotNone(admin_ctx.exception.details)
        self.assertEqual(
            admin_ctx.exception.details["subscription_status"], "suspended"
        )

        driver_container = _container_for(
            _subscription(status=SubscriptionStatus.SUSPENDED)
        )
        with self.assertRaises(OrganizationSubscriptionInactiveError) as driver_ctx:
            await enforce_organization_subscription(
                _FakeRequest("/api/v1/trips", _principal(Role.DRIVER)),
                container=driver_container,
            )
        self.assertIsNone(driver_ctx.exception.details)

    async def test_websocket_helper_mirrors_the_http_decision(self) -> None:
        """Scenario 24: a suspended tenant must not keep consuming realtime services. Both
        surfaces share one decision function precisely so they cannot disagree."""
        suspended = _container_for(_subscription(status=SubscriptionStatus.SUSPENDED))
        self.assertFalse(
            await is_organization_access_allowed(
                _principal(Role.ORG_ADMIN), container=suspended
            )
        )
        active = _container_for(_subscription(status=SubscriptionStatus.ACTIVE))
        self.assertTrue(
            await is_organization_access_allowed(
                _principal(Role.ORG_ADMIN), container=active
            )
        )

    async def test_unbound_billing_subsystem_does_not_break_every_route(self) -> None:
        """An un-deployed billing subsystem must not read as "every tenant is delinquent". This
        is the explicit-absence case only — a bound-but-failing lookup still propagates."""
        empty = _FakeContainer({})
        await enforce_organization_subscription(
            _FakeRequest("/api/v1/vehicles", _principal(Role.ORG_ADMIN)),
            container=empty,
        )  # must not raise
        self.assertTrue(
            await is_organization_access_allowed(
                _principal(Role.ORG_ADMIN), container=empty
            )
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
