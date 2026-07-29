# Runbook: Recover a locked-out Founder account

## When you need this

The Founder that `docs/runbooks/founder-bootstrap.md` created has forgotten their password, or
otherwise lost access, and no other Founder account can log in to reset it for them. Passwords
are never stored in plaintext anywhere in this system (`users.password_hash`, PBKDF2-hashed) —
there is no value to "look up." This command sets a *new* password; it cannot recover the old
one, and nothing in this codebase ever could.

This is a CLI command, not an HTTP endpoint, deliberately — same reasoning as
`founder-bootstrap.md`: it runs behind your deployment's own access boundary (whoever can
already reach a shell/exec into the running environment), not the public network.

**If the locked-out account is not a Founder** (an Org Admin, Regional Manager, etc.), use this
instead: any account holding `iam.users.reset_password` (founder/regional_manager/support_staff
as of this writing) can reset it over HTTP via `POST /users/{user_id}/reset-password` — no shell
access needed. This CLI recovers Founder accounts specifically, because a Founder is the one
role with no admin above it to call that endpoint on their behalf.

## Prerequisites

Same as `founder-bootstrap.md`: `RAAD_DB__URL` configured and reachable,
`RAAD_AUTH__JWT_SECRET_KEY` configured if `RAAD_ENVIRONMENT=prod`.

## Running it

From `backend/`, with your environment already configured exactly as you would for running the
API:

```bash
export RAAD_RESET_FOUNDER_EMAIL="founder@yourorg.example"
export RAAD_RESET_FOUNDER_PASSWORD="<a strong new password you already have in your own secrets manager>"
python -m raad.interfaces.cli.reset_founder_password
unset RAAD_RESET_FOUNDER_PASSWORD
```

Or with CLI flags (only if your shell/CI environment doesn't expose command arguments to other
users on the same host):

```bash
python -m raad.interfaces.cli.reset_founder_password \
  --email "founder@yourorg.example" \
  --password "<your new password>"
```

There is no `--generate-password` option, by the same design choice `bootstrap_founder.py`
makes — you supply the new password yourself.

## What it does

1. Looks up the account by email. Refuses (nothing touched) if no account exists, or if the
   account found is not `role=founder` — this command is Founder-specific; see "If the
   locked-out account is not a Founder" above for every other role.
2. Validates the new password against the same `PasswordPolicy` every other password path in
   this API enforces, hashes it, and stores it — the exact same application-layer call
   `POST /auth/change-password` itself makes.

This does **not** revoke the account's existing sessions (unlike the admin-reset-password HTTP
route) — you are recovering your own account, not resetting someone else's out from under them.
If you specifically want to invalidate other active sessions too, log out of them manually once
you're back in, or use `POST /auth/logout` per session.

## Verifying it worked

```bash
curl -X POST http://<your-api-host>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"identifier": "founder@yourorg.example", "password": "<your new password>"}'
```

A successful response returns `access_token`/`refresh_token`.

## Troubleshooting

**"No account found for ..."** — the email doesn't match any `users` row. Double-check it
against what `docs/runbooks/founder-bootstrap.md` originally used, or query the `users` table
directly if you have database access.

**"... is not a Founder account (role=...)"** — the email belongs to a real account, but not a
Founder one. Use `POST /users/{id}/reset-password` instead (see above).

**A password-policy error.** The message names exactly which rule failed (e.g. "must contain a
digit") — fix the input and re-run; nothing was changed.
