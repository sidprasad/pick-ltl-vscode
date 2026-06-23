#!/usr/bin/env bash
# Re-vendor the Python backend from a pick-ltl checkout into python/pick_ltl.
#
# Usage:
#   ./util/sync-backend.sh                      # from ../pick-ltl/src/pick_ltl
#   ./util/sync-backend.sh /path/to/pick_ltl    # from an explicit source
#
# preflight.py and this script live in the extension and are never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$REPO_ROOT/../pick-ltl/src/pick_ltl}"
DEST="$REPO_ROOT/python/pick_ltl"

if [ ! -d "$SRC" ]; then
  echo "error: source package not found: $SRC" >&2
  echo "Pass the path to pick-ltl's src/pick_ltl as the first argument." >&2
  exit 1
fi

mkdir -p "$DEST"
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache/' \
  "$SRC/" "$DEST/"

echo "Synced backend: $SRC -> $DEST"
