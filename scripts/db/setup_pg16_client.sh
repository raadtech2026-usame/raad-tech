#!/bin/sh
# scripts/db/setup_pg16_client.sh — ensures PostgreSQL 16 client binaries are installed
# and available on PATH (Priority 1 Item 1, CI backup/restore round-trip test).
#
# Option A: Configures the official PostgreSQL PGDG APT repository and installs
# postgresql-client-16 using secure signed-by keyring mechanism.
# Option B (Fallback): If APT package is unavailable, generates wrapper scripts
# invoking matching client tools from official postgres:16 Docker image.

set -eu

sudo apt-get update -y
sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release

# Option A: Configure official PostgreSQL PGDG APT repository
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor --yes -o /etc/apt/keyrings/postgresql.gpg
sudo chmod 0644 /etc/apt/keyrings/postgresql.gpg

CODENAME="$(lsb_release -cs 2>/dev/null || echo "resolute")"
echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list

sudo apt-get update -y
if apt-cache show postgresql-client-16 >/dev/null 2>&1; then
  echo "Installing postgresql-client-16 from PGDG repository (${CODENAME}-pgdg)..."
  sudo apt-get install -y --no-install-recommends postgresql-client-16
else
  echo "Package postgresql-client-16 not found for ${CODENAME}-pgdg, trying noble-pgdg fallback..."
  echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt noble-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
  sudo apt-get update -y
  sudo apt-get install -y --no-install-recommends postgresql-client-16 || true
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
      'exec docker run --rm --net=host -u "$(id -u):$(id -g)" -e PGPASSWORD -e PGUSER -e PGHOST -e PGPORT -v /tmp:/tmp -v "$PWD:$PWD" -w "$PWD" postgres:16 "$tool_name" "$@"' \
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
psql -tAc "SHOW server_version_num;"
