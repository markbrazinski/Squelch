#!/bin/bash
# Mirror lookups/*.csv into the Splunk app lookups dir.
# Run after editing any file in lookups/ at the repo root.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)/lookups"
DST="/Applications/Splunk/etc/apps/squelch/lookups"
cp "$SRC"/*.csv "$DST/"
ls -la "$DST/"
