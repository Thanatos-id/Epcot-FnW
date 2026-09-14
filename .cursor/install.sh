#!/usr/bin/env bash
# Idempotent repository setup for Cloud Agents: system deps, Python deps, .env.
set -euo pipefail
cd "$(dirname "$0")/.."

# PostgreSQL server is a system dependency. This is a no-op when it is already
# present (e.g. booting from the environment snapshot that has it baked in);
# it self-heals a fresh base image that lacks it.
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib
fi

# Python dependencies: editable install with the dev and data_ledger extras.
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -e ".[dev,data_ledger]"

# App settings live in .env (gitignored). Only create when missing so a
# hand-edited file is preserved across reruns.
if [ ! -f .env ]; then
  cat > .env <<'EOF'
DATABASE_URL=postgresql+psycopg://ubuntu@localhost:5432/epcot_fw
TEST_DATABASE_URL=postgresql+psycopg://ubuntu@localhost:5432/epcot_fw_test
USER_AGENT_CONTACT=dev@example.com
LOG_LEVEL=INFO
EOF
fi

echo "install.sh complete"
