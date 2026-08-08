#!/bin/bash
# Runs `epcot-fw refresh` using the project's venv. Invoked weekly by
# com.epcot.foodwine.refresh.plist (launchd), or run manually any time.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

source .venv/bin/activate
exec epcot-fw refresh
