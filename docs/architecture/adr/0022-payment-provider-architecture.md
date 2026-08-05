# ADR-0022: Payment Provider Architecture

## Status
Accepted (direct user decision, 2026-08-05 — resolves the "genuinely blocked without external
input" framing `PROJECT_STATUS.md` Known Issue #4 has carried since the Priority 1 audit). User
explicitly selected, among presented options: Stripe gets a real adapter now; EVC Plus/Zaad get
the `PaymentProviderPort` interface wired but stay explicit stubs; secrets live in environment
variables, never `SystemSetting`; the webhook authenticates via per-provider HMAC signature.

## Context
Two independent blockers had stopped `POST /billing/payments`/`POST /billing/payments/callback`
from ever being wired, both confirmed by re-reading the actual code rather than assumed:

1. **No real merchant account or API documentation existed for any provider**, so building an
   adapter against guessed request/response shapes would have embedded unverified assumptions as
   if they were tested integration code (`.claude/rules/workflow.md` #8). Stripe changes this:
   its REST API is public, stable, and extensively documented, so a genuinely verified adapter is
   possible without a live account — only real *credentials* remain external.
2. **No documented signature/secret verification scheme, and no `Principal` for a "provider
   (signed)" webhook caller** — `billing/api/routers.py`'s own module docstring had already
   reached this conclusion independently. `PaymentCallbackCommand.actor: Principal` is a
   required, non-optional field with no documented value for a non-human caller.

Reading the actual `Payment` aggregate and `PaymentProviderPort` (not assumed from their
docstrings) surfaced two further, previously-undiscovered issues this ADR also resolves:

3. **A live idempotency bug.** `Payment.mark_paid`/`mark_failed` (`domain/entities.py`) have no
   same-state guard, unlike `mark_processing`/`mark_expired`, which already are idempotent. Every
   real payment provider retries a webhook delivery until it receives a `200` — a duplicate
   `"paid"` callback today would call `subscription.renew(...)` a second time, double-advancing
   the organization's billing period. Not hypothetical: this is normal provider behavior, not an
   edge case.
4. **`PaymentProviderPort` (`application/ports.py`) is shaped entirely around mobile money**:
   `charge(amount, msisdn, reference) -> str`. A card provider has no `msisdn` and must never
   receive a raw card number server-side (PCI DSS scope) — it needs a client-tokenized
   `payment_method` id instead. The existing one-method interface cannot represent both shapes
   without redesign.

`raad/modules/billing/infra/adapters.py` is completely empty (0 bytes) — there was no prior stub
to preserve compatibility with. `PaymentSettings` (`core/config/settings.py`) already declares
`provider: str = "evcplus"` / `provider_credentials: dict[str, str] = {}`, unused by anything —
the existing seam this ADR builds on for secret storage, not a new mechanism.

## Decision

### 1. Redesigned `PaymentProviderPort` — provider-agnostic by construction
```python
@dataclass(frozen=True)
class PaymentChargeRequest:
    amount: Money
    reference: str  # = idempotency_key; also passed through as the provider's own idempotency key
    msisdn: str | None = None
    payment_method_token: str | None = None  # a client-tokenized id (e.g. Stripe PaymentMethod)
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class PaymentChargeResult:
    provider_ref: str
    status: Literal["succeeded", "pending", "failed"]
    failure_reason: str | None = None

@dataclass(frozen=True)
class WebhookEvent:
    provider_ref: str
    status: Literal["paid", "failed"]
    failure_reason: str | None = None

class PaymentProviderPort(ABC):
    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult: ...
    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool: ...
    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent: ...
```
`msisdn`/`payment_method_token` are both optional on the request; each adapter validates that the
field it actually needs is present, rather than the port forcing every provider through a
mobile-money-shaped signature. Signature verification and webhook parsing move onto the port
itself, since each provider defines its own scheme — there is no provider-agnostic way to check a
signature.

### 2. Provider scope: Stripe real, EVC Plus/Zaad wired-but-stubbed
`infra/adapters.py` gains three classes, all satisfying `PaymentProviderPort`:
- **`StripePaymentAdapter`** — a real, `httpx`-based implementation. `charge()` calls Stripe's
  Payment Intents API (`confirm=true`, `automatic_payment_methods[allow_redirects]=never` — a
  deliberate v1 scope cut to a single synchronous confirm, no 3D Secure/SCA challenge flow: SCA
  is EU-driven and RAAD's documented target market does not currently require it). Amounts
  convert to integer cents (Stripe's own required unit). `verify_webhook_signature` implements
  Stripe's documented HMAC-SHA256 scheme against the `Stripe-Signature` header.
- **`EvcPlusPaymentAdapter`/`ZaadPaymentAdapter`** — implement the full interface (so they bind
  and type-check identically to Stripe, and the seam is real and discoverable, not just an empty
  interface), but `charge`/`verify_webhook_signature` raise a clear `NotImplementedError` naming
  exactly what's missing: a real merchant account and API documentation. Matches this codebase's
  own established "fail loudly, don't fake it" posture — an unverified guess dressed up as a
  working adapter would be worse than an honest stub.

### 3. Secrets: environment variables only, never `SystemSetting`
`PaymentSettings.provider_credentials` (env var `RAAD_PAYMENT__PROVIDER_CREDENTIALS`, read once
at the DI composition root) holds the Stripe secret key and webhook signing secret. Rejected
alternative: storing them in `SystemSetting` — that table is plain JSON in Postgres, and
`admin.settings.read`/`.update` are held by `org_admin` too, not just Founder/Finance, so any
Organization Admin could read or tamper with a platform-wide payment secret. `SystemSetting` is
still used for exactly one **non-secret** value — which provider is currently active
(`key="billing_payment_provider"`) — read via the already-existing `GET /admin/settings` route so
the frontend can decide what payment UI to render without a new endpoint.

### 4. Webhook authentication: per-provider HMAC signature, no `Principal`
`POST /billing/payments/callback` verifies the request via `PaymentProviderPort.
verify_webhook_signature` before parsing or trusting any of the body — a missing/invalid
signature is a `401`, audited, never silently accepted (`.claude/rules/security.md` #10). No
`Depends(require_permission(...))`/bearer JWT — the signature *is* the authentication, matching
how Stripe's (and every mainstream provider's) own webhook documentation describes this exact
model. `PaymentCallbackCommand.actor` is populated with `SYSTEM_PRINCIPAL` — moved from
`notifications/events/subscribers.py` (where it already exists for an identical "a worker-
triggered command needs *a* `Principal`, and none of the seven real roles fit" gap) to
`core/tenancy/principal.py`, so both call sites share one constant instead of two independently-
drifting copies. This is a reuse of an already-accepted "least-bad available role" precedent, not
a new RBAC concept — `Role` gains no new member.

### 5. Fix the idempotency bug at its root
`Payment.mark_paid`/`mark_failed` become same-state-idempotent no-ops, mirroring
`mark_processing`/`mark_expired`'s existing pattern exactly: calling either again on a `Payment`
already in that terminal state returns without raising a duplicate event or touching anything
else. `handle_payment_callback` additionally short-circuits before touching `Invoice`/
`Subscription` at all if the payment is already terminal — belt-and-suspenders with the entity
fix, and avoids wasted work on a replay delivery.

### 6. `Payment.failure_reason` — new nullable field
`mark_failed(*, clock, actor_id, reason: str | None = None)` now records why a payment failed
(new `payments.failure_reason VARCHAR(255)` column) — a real production gap otherwise ("why did
my payment fail" is a normal support question with no answer today).

### 7. New `GET /billing/payments` route (payment history)
No list route exists for `Payment` today — only `POST /billing/payments` (initiate). A new
`billing.payments.list` permission (granted to `founder`/`finance_staff`/`org_admin`, mirroring
`.subscriptions.list`'s existing grant set — not `regional_manager`/`support_staff`, who hold
only `billing.plans.list`) backs it, via a new `PaymentRepository.list_page`/`filterable_fields`
(`organization_id`/`invoice_id`/`status`) mirroring `SqlAlchemyInvoiceRepository`'s identical
existing shape.

## Consequences
- One new migration: `payments.failure_reason`, the `billing.payments.list` grant, and the
  `billing_payment_provider` `SystemSetting` seed row.
- New backend dependency: `httpx` (async HTTP client — chosen over the official `stripe` SDK to
  match this codebase's existing "hand-roll a narrow, well-understood need" pattern rather than
  pull a heavier dependency; Stripe's REST API is simple enough to call directly).
- New frontend dependencies: `@stripe/stripe-js` + `@stripe/react-stripe-js` (card tokenization
  client-side — not optional, since a raw card number must never reach this backend).
- **Explicitly deferred, not silently dropped**: 3D Secure/SCA, refunds (`PaymentStatus.
REFUNDED` remains a documented enum value with no behavior method — unchanged), and EVC Plus/
  Zaad's actual API integration (blocked on a real merchant account, the same external dependency
  this ADR itself was written to stop pretending could be worked around).
- `PaymentProviderPort`'s method signatures change — no existing caller outside `billing`
  depended on the old `charge(amount, msisdn, reference) -> str` shape (confirmed: the port was
  never bound to anything, so there is no live caller to break).

## Verification
- Unit: the idempotency-guard regression specifically (a second `handle_payment_callback("paid")`
  call does not re-advance the subscription period); `StripePaymentAdapter` against mocked
  `httpx` responses (request shape, cents conversion, signature verification against Stripe's own
  published test vectors); `EvcPlusPaymentAdapter`/`ZaadPaymentAdapter` confirmed to raise the
  documented error, never silently succeed.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped, `alembic check` clean.
- `tests/architecture/test_module_boundaries.py` re-run green.
- **Disclosed limitation, not overstated**: no live Stripe account exists in this environment —
  the adapter is verified against Stripe's public API documentation and mocked HTTP responses,
  not a real Stripe test-mode account. Same posture as TLS (Item 2) and Redis hardening (Item 4):
  mechanism complete and carefully verified, live end-to-end confirmation pending a real external
  account.

## References
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §20 (payment workflow design)
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §8.4 (`payments`)
- `.claude/rules/security.md` #10 (payment callbacks are untrusted input until verified)
- `.claude/rules/workflow.md` #1/#2 (new dependencies), #7/#8 (ADR before business logic)
- `raad/modules/billing/domain/entities.py` (`Payment`), `application/ports.py`
  (`PaymentProviderPort`), `infra/adapters.py`
- `raad/modules/notifications/events/subscribers.py` (`SYSTEM_PRINCIPAL`'s prior, single-module
  precedent — moved to `core/tenancy/principal.py` by this ADR)
- `PROJECT_STATUS.md` Known Issue #4 (the audit this ADR resolves)
