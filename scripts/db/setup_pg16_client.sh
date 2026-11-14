#!/bin/sh
# scripts/db/setup_pg16_client.sh — ensures PostgreSQL 16 client binaries are installed
# and available on PATH (Priority 1 Item 1, CI backup/restore round-trip test).
#
# Option A: Attempts to configure the official PostgreSQL PGDG APT repository and install
# postgresql-client-16 using secure signed-by keyring mechanism.
# Option B (Fallback): If APT package is unavailable or network/distro issues occur,
# generates wrapper scripts invoking matching client tools from official postgres:16 Docker image.

set -eu

# Install base prerequisites if apt-get is present
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y || true
  sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release || true
fi

# Option A: Attempt official PostgreSQL PGDG APT repository installation
try_apt_install() {
  command -v apt-get >/dev/null 2>&1 || return 1
  command -v curl >/dev/null 2>&1 || return 1
  command -v gpg >/dev/null 2>&1 || return 1

  sudo install -d -m 0755 /etc/apt/keyrings 2>/dev/null || return 1

  KEY_TMP="$(mktemp 2>/dev/null || echo "/tmp/pgdg_key_$$.asc")"
  echo "Fetching PostgreSQL PGDG signing key..."
  if ! curl --retry 5 --retry-delay 2 --retry-connrefused --max-time 15 -fsSL \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc -o "$KEY_TMP" 2>/dev/null || [ ! -s "$KEY_TMP" ]; then
    echo "Warning: Could not securely download PostgreSQL signing key from postgresql.org"
    rm -f "$KEY_TMP"
    return 1
  fi

  if ! sudo gpg --dearmor --yes -o /etc/apt/keyrings/postgresql.gpg "$KEY_TMP" 2>/dev/null; then
    echo "Warning: Failed to dearmor PostgreSQL signing key"
    rm -f "$KEY_TMP"
    return 1
  fi
  rm -f "$KEY_TMP"
  sudo chmod 0644 /etc/apt/keyrings/postgresql.gpg 2>/dev/null || true

  CODENAME="$(lsb_release -cs 2>/dev/null || echo "noble")"
  echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null

  if sudo apt-get update -y 2>/dev/null && apt-cache show postgresql-client-16 >/dev/null 2>&1; then
    echo "Installing postgresql-client-16 from PGDG repository (${CODENAME}-pgdg)..."
    if sudo apt-get install -y --no-install-recommends postgresql-client-16 2>/dev/null; then
      return 0
    fi
  fi

  # Fallback for newer distros like 26.04 (resolute) where PGDG doesn't have a release yet
  echo "Package postgresql-client-16 not found for ${CODENAME}-pgdg, trying noble-pgdg fallback..."
  echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt noble-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
  if sudo apt-get update -y 2>/dev/null; then
    if sudo apt-get install -y --no-install-recommends postgresql-client-16 2>/dev/null; then
      return 0
    fi
  fi

  # Clean up failed repository entry so it does not interfere with other apt operations
  sudo rm -f /etc/apt/sources.list.d/pgdg.list
  return 1
}

# Run Option A with set +e so transient network or packaging failures do not abort the script
set +e
try_apt_install
APT_STATUS=$?
set -e

if [ "$APT_STATUS" -ne 0 ]; then
  echo "Option A (APT) unavailable or failed. Falling back to Option B (Docker wrapper)..."
  sudo rm -f /etc/apt/sources.list.d/pgdg.list 2>/dev/null || true
fi

# Prioritize PostgreSQL 16 directory
if [ -d "/usr/lib/postgresql/16/bin" ]; then
  export PATH="/usr/lib/postgresql/16/bin:$PATH"
fi

# Option B: Reliable fallback via official postgres:16 Docker image
PG_DUMP_CHECK="$(pg_dump --version 2>/dev/null || echo "")"
if ! echo "$PG_DUMP_CHECK" | grep -q " 16\."; then
  echo "Option B Fallback: Generating PostgreSQL 16 client wrappers via postgres:16 image..."
  sudo mkdir -p /usr/lib/postgresql/16/bin
  for tool in pg_dump pg_restore psql createdb dropdb pg_isready; do
    printf '%s\n' \
      '#!/bin/sh' \
      'tool_name="$(basename "$0")"' \
      'exec docker run -i --rm --net=host -u "$(id -u):$(id -g)" -e PGPASSWORD -e PGUSER -e PGHOST -e PGPORT -e PGDATABASE -e PGSSLMODE -e PGOPTIONS -v /tmp:/tmp -v "$PWD:$PWD" -w "$PWD" postgres:16 "$tool_name" "$@"' \
      | sudo tee "/usr/lib/postgresql/16/bin/$tool" >/dev/null
    sudo chmod +x "/usr/lib/postgresql/16/bin/$tool"
  done
  export PATH="/usr/lib/postgresql/16/bin:$PATH"
fi

echo "Verifying PostgreSQL client tools:"
pg_dump --version
pg_restore --version
psql --version
echo -n "Target server version num: "
psql -tAc "SHOW server_version_num;" || echo "(server not reachable or not running yet)"
