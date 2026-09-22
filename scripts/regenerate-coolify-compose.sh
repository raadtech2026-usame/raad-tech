#!/usr/bin/env bash
# Regenerate docker/docker-compose.coolify.full.yml (ADR-0022, ADR-0045).
#
# That file is the single, fully-merged Compose stack Coolify deploys. It is GENERATED from
#   docker/docker-compose.yml        (base stack)
#   docker/docker-compose.coolify.yml (Coolify overlay)
# and must never be hand-edited, or it silently drifts from the two files it mirrors.
#
# `docker compose config` strips comments and normalises two fields in ways Coolify's stricter
# validator rejects, so three things have to happen every time, in order:
#   1. merge the two source files
#   2. re-prepend the explanatory header (preserved from the existing file, so it survives)
#   3. re-apply the two documented post-generation patches
#
# Doing any of them by hand is how the patches got silently reintroduced as bugs twice before.
# Run this from the repository root. Requires `docker compose` (v2+) and python3; it needs no
# Docker daemon, because `docker compose config` is a pure YAML merge.

set -euo pipefail

cd "$(dirname "$0")/.."

BASE="docker/docker-compose.yml"
OVERLAY="docker/docker-compose.coolify.yml"
TARGET="docker/docker-compose.coolify.full.yml"

for f in "$BASE" "$OVERLAY" "$TARGET"; do
  [ -f "$f" ] || { echo "ERROR: missing $f" >&2; exit 1; }
done

TMP_BODY="$(mktemp)"
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_BODY" "$TMP_OUT"' EXIT

echo "==> merging $BASE + $OVERLAY"
# --no-interpolate: keep ${SOURCE_COMMIT} and every other variable unresolved, so Coolify
#                   substitutes them at deploy time and no local .env value is baked in.
# --no-path-resolution: keep relative paths relative; absolute local paths are meaningless on
#                   the VPS.
# COMPOSE_PROFILES= : leave the `gateway` profile inactive (Coolify runs its own Traefik).
COMPOSE_PROFILES= docker compose --env-file /dev/null \
  -f "$BASE" -f "$OVERLAY" \
  config --no-interpolate --no-path-resolution > "$TMP_BODY"

echo "==> re-prepending header and applying post-generation patches"
python3 - "$TARGET" "$TMP_BODY" "$TMP_OUT" <<'PY'
import io, re, sys

target, body_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

# The header is whatever precedes the first `name:` key in the CURRENT committed file. Carrying
# it forward (rather than embedding a copy in this script) keeps one source of truth: edit the
# header in the .yml, and every later regeneration preserves the edit.
current = io.open(target, encoding='utf-8').read()
m = re.search(r'^name:', current, flags=re.M)
if not m:
    sys.exit("ERROR: no top-level `name:` key in %s - cannot locate the header boundary" % target)
header = current[:m.start()]
if '=====' not in header:
    sys.exit("ERROR: header in %s does not look like the expected comment block" % target)

body = io.open(body_path, encoding='utf-8').read()

# PATCH 1 - Coolify's validator accepts only a string or null for `entrypoint`, never [].
n1 = body.count('    entrypoint: []')
body = body.replace('    entrypoint: []', '    entrypoint: ""')

# PATCH 2 - a bind-mount `source:` without a leading ./ is ambiguous with a named volume.
n2 = len(re.findall(r'^(\s+source: )\.\./', body, flags=re.M))
body = re.sub(r'^(\s+source: )\.\./', r'\1./', body, flags=re.M)

# Guard: production services must be pulled, never built on the VPS (ADR-0045). A stray build:
# section here would silently restore the CPU spike this whole change exists to remove.
builds = re.findall(r'^\s{4}build:', body, flags=re.M)
if builds:
    sys.exit("ERROR: %d build: section(s) survived the merge - production must pull images, not "
             "build them. Check that docker-compose.coolify.yml still carries "
             "`build: !reset null` for every RAAD service." % len(builds))

io.open(out_path, 'w', encoding='utf-8', newline='\n').write(header + body)
print("    patch 1 (entrypoint) applied to %d line(s)" % n1)
print("    patch 2 (bind-mount ./ prefix) applied to %d line(s)" % n2)
print("    build: sections remaining: 0 (correct)")
PY

mv "$TMP_OUT" "$TARGET"
echo "==> wrote $TARGET"
echo
echo "Image references now in the deployed stack:"
grep -E '^    image: ' "$TARGET" | sed 's/^/    /'
echo
echo "Review the diff before committing:  git diff -- $TARGET"
