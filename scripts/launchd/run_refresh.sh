#!/bin/bash
# Runs `epcot-fw refresh` using the project's venv. Invoked daily at 03:00 by
# com.epcot.foodwine.refresh.plist (launchd), or run manually any time.
#
# Install the schedule with:
#   ln -sfn "$PWD/scripts/launchd/com.epcot.foodwine.refresh.plist" \
#           ~/Library/LaunchAgents/com.epcot.foodwine.refresh.plist
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.epcot.foodwine.refresh.plist
# The symlink keeps this repo the source of truth for the schedule; edit the
# plist here and `launchctl kickstart -k` to pick the change up.
#
# This refreshes the DATABASE only. docs/ is a build output and still has to
# be regenerated (export_snapshot -> fetch_images -> build_artifact) before a
# photo this picks up shows in the studio or on Pages - deliberately, since
# rebuilding rewrites ledger_history.json and leaves docs/ dirty for review
# rather than publishing on its own.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

source .venv/bin/activate
exec epcot-fw refresh
