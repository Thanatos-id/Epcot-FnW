#!/usr/bin/env bash
# Per-boot reconciliation: bring up PostgreSQL, ensure role/databases, migrate,
# and seed. Safe to run repeatedly.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_VER="$(ls /etc/postgresql 2>/dev/null | sort -n | tail -1)"
HBA="/etc/postgresql/${PG_VER}/main/pg_hba.conf"

# Start the cluster only if it is not already accepting connections.
if ! pg_isready -q -h localhost -p 5432 2>/dev/null; then
  sudo pg_ctlcluster "${PG_VER}" main start || true
fi

# Dev-only: trust local TCP/socket connections so the app connects without a
# password. Idempotent - only rewrites when a non-trust method is still set.
if sudo grep -Eq '^(host|local)[[:space:]]+all[[:space:]]+all[[:space:]]+\S+[[:space:]]+(scram-sha-256|md5|peer)' "$HBA" \
   || sudo grep -Eq '^local[[:space:]]+all[[:space:]]+all[[:space:]]+(scram-sha-256|md5|peer)' "$HBA"; then
  sudo sed -ri 's/^(host[[:space:]]+all[[:space:]]+all[[:space:]]+127\.0\.0\.1\/32[[:space:]]+)(scram-sha-256|md5)/\1trust/' "$HBA"
  sudo sed -ri 's/^(host[[:space:]]+all[[:space:]]+all[[:space:]]+::1\/128[[:space:]]+)(scram-sha-256|md5)/\1trust/' "$HBA"
  sudo sed -ri 's/^(local[[:space:]]+all[[:space:]]+all[[:space:]]+)(peer|scram-sha-256|md5)/\1trust/' "$HBA"
  sudo pg_ctlcluster "${PG_VER}" main reload || true
fi

# Wait for readiness before touching the database.
for _ in $(seq 1 30); do
  pg_isready -q -h localhost -p 5432 && break
  sleep 1
done

# Ensure the login role and both databases exist.
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='ubuntu'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE ubuntu LOGIN SUPERUSER"
for db in epcot_fw epcot_fw_test; do
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1 \
    || sudo -u postgres createdb -O ubuntu "${db}"
done

# Apply schema migrations and seed reference data (both idempotent).
python3 -m alembic upgrade head
python3 -m epcot_fw.db.seed

echo "start.sh complete"
