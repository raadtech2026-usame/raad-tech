# Runbook: TLS / HTTPS setup

## When you need this

Once, when you first have a real domain name and a real VPS to point it at (Priority 1 Item 2,
`PROJECT_STATUS.md`) — turning the platform from plain HTTP into a real, browser-trusted HTTPS
site via Let's Encrypt. Not needed for local development, which stays plain HTTP on purpose (see
`docker/docker-compose.prod.yml`'s own comments).

**Testing scope, stated honestly:** the nginx TLS config and the `certbot` renewal automation
were built and carefully reviewed, but not run against a real domain — no domain/VPS existed
while this was implemented. The design (nginx + certbot + Let's Encrypt via the webroot HTTP-01
challenge) is the standard, widely-documented pattern for this exact Docker Compose topology, and
`infrastructure/nginx/conf.d/prod.conf`'s own comment already named it as the intended shape
before this runbook existed. Step 3 below — testing against Let's Encrypt's **staging**
environment — is deliberately where the first genuinely live test happens, safely, before any
production (rate-limited) certificate request.

## Prerequisites

- A real domain name, with an A (and/or AAAA) record already pointing at your VPS's public IP.
  DNS propagation can take anywhere from minutes to (rarely) a day — confirm with
  `dig +short yourdomain.example` from outside the VPS before continuing.
- Ports `80` and `443` reachable from the public internet on that VPS (check your cloud
  provider's firewall/security-group rules, not just the OS firewall).
- The stack already running on plain HTTP (`docker compose -f docker/docker-compose.yml -f
  docker/docker-compose.prod.yml up -d --build`, per `docker/README.md`) — `certbot`'s first
  request needs a working HTTP server to validate domain ownership against.
- `docker/.env` filled in with `DOMAIN_NAME` and `TLS_EMAIL` (used only for Let's Encrypt's own
  expiry-notice/account-recovery email, never sent anywhere else in this codebase).

## Step 1 — confirm the ACME challenge path is reachable

Before requesting any certificate, prove the webroot challenge actually resolves end to end
(this exercises the exact mechanism certbot will use, without touching Let's Encrypt yet):

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  exec nginx sh -c 'echo ok > /var/www/certbot/test.txt'
curl -f http://yourdomain.example/.well-known/acme-challenge/test.txt
# Expect: ok
```

If this doesn't return `ok`, stop here — DNS or firewall isn't ready yet, and certbot will fail
for the same reason. Fix that first (see Troubleshooting).

## Step 2 — request a certificate against Let's Encrypt's **staging** environment first

Staging certificates aren't browser-trusted, but staging has no meaningful rate limits — this is
where you find out your setup actually works before spending one of your limited real attempts.

`--entrypoint certbot` below is required, not optional: the `certbot` service's own entrypoint is
cleared (`entrypoint: []` in `docker-compose.prod.yml`) so its long-running renewal loop
(`scripts/tls/certbot-renew-loop.sh`) can run standalone as `command:` — a one-off `docker
compose run` inherits that same cleared entrypoint unless told otherwise.

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  run --rm --entrypoint certbot certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --staging \
  --email "you@yourorg.example" \
  --agree-tos --no-eff-email \
  -d yourdomain.example
```

Confirm it reports success (`Successfully received certificate` / a cert path under
`/etc/letsencrypt/live/yourdomain.example/`). If it fails, fix the reported cause and re-run —
staging has effectively no rate limit, so retry freely.

## Step 3 — get the real certificate

Remove `--staging` from the command above (nothing else changes) and re-run. This one **does**
count against Let's Encrypt's production rate limits (currently 5 certificates per exact domain
set per week) — only do this once Step 2 succeeded cleanly.

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  run --rm --entrypoint certbot certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --email "you@yourorg.example" \
  --agree-tos --no-eff-email \
  -d yourdomain.example
```

## Step 4 — switch nginx to the TLS config

Edit `docker/.env`:

```bash
NGINX_PROD_CONF=prod-tls.conf
```

Then restart nginx so it picks up the new template and the certificate now sitting in the shared
`raad_certbot_conf` volume:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d nginx certbot
```

## Verifying it worked

```bash
curl -I https://yourdomain.example/health
# Expect: HTTP/2 200, and a Strict-Transport-Security header

curl -I http://yourdomain.example/
# Expect: HTTP/1.1 301, Location: https://yourdomain.example/
```

Also check from a real browser — a padlock with no warnings confirms the certificate chain is
actually trusted, which `curl` alone doesn't fully prove.

## Verifying auto-renewal (don't wait 60 days to find out it's broken)

Force a renewal attempt right now — `--force-renewal` bypasses the "not due yet" check so you can
confirm the mechanism works today rather than assuming it will in two months:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  exec certbot certbot renew --force-renewal \
  --webroot --webroot-path /var/www/certbot \
  --deploy-hook "kill -HUP 1"

# Confirm nginx actually reloaded (its error log shows a reload, not a restart):
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  logs nginx --tail 20
```

The `certbot` service itself checks for a due renewal automatically every
`CERTBOT_RENEW_INTERVAL_HOURS` (default 12h, `docker/.env`) — nothing further to schedule.

## Troubleshooting

**Step 1's `curl` fails or times out.** Almost always DNS (not yet propagated, or pointing at the
wrong IP — recheck with `dig`) or a cloud firewall/security-group rule blocking port 80 from the
public internet (distinct from the VPS's own OS-level firewall, which Docker's own port
publishing already bypasses correctly).

**Certbot reports a rate-limit error.** You skipped or failed Step 2 and went straight to
production requests. Wait out the rate-limit window (the error message states exactly how long)
and use `--staging` while debugging in the meantime.

**nginx fails to start after switching to `NGINX_PROD_CONF=prod-tls.conf`.** Almost always means
Step 3 wasn't actually completed successfully — `ssl_certificate`/`ssl_certificate_key` point at
`/etc/letsencrypt/live/${DOMAIN_NAME}/...`, and nginx refuses to boot if those files don't exist.
Confirm with `docker compose ... exec nginx ls /etc/letsencrypt/live/` that a directory matching
`DOMAIN_NAME` exactly is actually there.

**The renewal's `--deploy-hook` doesn't seem to reload nginx.** Confirm `docker-compose.prod.yml`'s
`certbot` service still has `pid: "service:nginx"` — without it, `kill -HUP 1` signals the
`certbot` container's own PID 1 (itself), not nginx's, and silently does nothing useful.

**HSTS locked me out after a misconfiguration.** This is exactly why `prod-tls.conf` ships a
conservative `max-age=15552000` (180 days) with no `preload`/`includeSubDomains` — a browser that
already cached the HSTS header will refuse to load the site over HTTP even if you roll back
`NGINX_PROD_CONF`, but the cached policy expires in 180 days rather than being effectively
permanent. Fix the underlying HTTPS problem rather than trying to roll back once HSTS has been
served to real users.
