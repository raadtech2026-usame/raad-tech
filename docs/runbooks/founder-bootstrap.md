# Runbook: Bootstrap the first Founder account

## When you need this

A brand-new deployment starts with an empty `users` table. Every documented way to create a user
(`POST /users`, API Contracts §4.1) requires an already-authenticated in-scope admin — so without
this command there is no way to obtain the very first account at all. Run this exactly once, right
after migrations (`alembic upgrade head`) have been applied and before anyone needs to log in.

This is a CLI command, not an HTTP endpoint, deliberately — it runs behind your deployment's own
access boundary (whoever can already reach a shell/exec into the running environment), not the
public network, and it adds no new attack surface to the API itself.

## Prerequisites

- Migrations applied (`alembic upgrade head`) — the `users` table must exist.
- `RAAD_DB__URL` configured and reachable (same requirement as running the API itself).
- `RAAD_AUTH__JWT_SECRET_KEY` configured if `RAAD_ENVIRONMENT=prod` (same requirement `Settings.
  validate_on_startup()` already enforces for the API).
- **Confirm the `users` table is actually empty first.** The command refuses to run otherwise, but
  it's your own signal that this step still needs doing (a non-empty table means either a prior
  successful bootstrap, or an interrupted one — see Troubleshooting below).

## Running it

From `backend/`, with your environment already configured (`.env` or real environment variables,
exactly as you would for running the API):

```bash
# Preferred: password via environment variable (not visible in shell history or `ps`)
export RAAD_BOOTSTRAP_FOUNDER_EMAIL="founder@yourorg.example"
export RAAD_BOOTSTRAP_FOUNDER_PASSWORD="<a strong password you already have in your own secrets manager>"
python -m raad.interfaces.cli.bootstrap_founder
unset RAAD_BOOTSTRAP_FOUNDER_PASSWORD
```

Or, with CLI flags (only if your shell/CI environment doesn't expose command arguments to other
users on the same host):

```bash
python -m raad.interfaces.cli.bootstrap_founder \
  --email "founder@yourorg.example" \
  --password "<your password>" \
  --full-name "Jane Doe"
```

`--full-name` is optional either way (defaults to `"Founder"`).

There is no `--generate-password` option and never will be by design — you must already have the
password before running this, from whatever secrets workflow your organization uses. Nothing is
printed, logged, or persisted in plaintext by this command; only its hash is stored.

## What it does

1. Refuses to run (clean error, no rows touched) if `users` already has **any** row at all — not
   just Founders. This is the enforced "brand-new deployment only" guarantee.
2. Creates the Founder account (`invite_user`).
3. Sets its password, validated against the same `PasswordPolicy` every other password path in
   this API enforces (`change_password`).
4. Activates it (`activate_user`) — it can log in immediately afterward, no separate step needed.

All three steps reuse this codebase's existing `UserApplicationService` methods and the same
composition root (`core.di.bootstrap.build_container`) the HTTP app and background workers already
share — no new business logic was written for this command.

## Verifying it worked

```bash
curl -X POST http://<your-api-host>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier": "founder@yourorg.example", "password": "<your password>"}'
```

A successful response returns `access_token`/`refresh_token`. In Swagger UI (`/docs`), click
**Authorize**, paste the `access_token` value, and any endpoint the Founder role can reach should
now work from "Try it out."

## Troubleshooting

**"Refusing to bootstrap: N user(s) already exist" on a deployment you don't believe has ever
logged in successfully.** This means a prior run was interrupted partway (steps 2-4 above are
three separate transactions, not one atomic operation — see `bootstrap_founder.py`'s own module
docstring for why). Inspect the `users` table directly to see which state the row is in
(`status = 'invited'` with a null `password_hash` means it never got past step 2;
`status = 'invited'` with a password set means it never got past step 3). There is currently no
CLI path to resume a partial bootstrap — an operator with direct database access will need to
either delete the incomplete row and re-run this command, or complete the remaining step(s)
manually via the existing `UserApplicationService` methods. This is a known, accepted limitation,
not a bug: an atomic three-step transaction would require changing already-tested, already-shipped
application-service methods that every other caller also depends on staying exactly as they are.

**"No Founder email/password provided."** Neither `--email`/`--password` nor
`RAAD_BOOTSTRAP_FOUNDER_EMAIL`/`RAAD_BOOTSTRAP_FOUNDER_PASSWORD` resolved to a value. Set one of
each pair before retrying.

**A password-policy or invalid-email error.** The message names exactly which rule failed (e.g.
"must contain a digit") or which email string was rejected — fix the input and re-run; nothing was
created.
