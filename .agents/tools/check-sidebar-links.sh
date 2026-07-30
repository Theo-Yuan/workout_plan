#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

SIDEBAR="_sidebar.md"
BROKEN=0

if [ ! -f "$SIDEBAR" ]; then
    echo "WARN: $_sidebar.md not found, skipping check"
    exit 0
fi

while IFS= read -r link; do
    [ -z "$link" ] && continue

    path="${link#](}"
    path="${path%)}"

    [[ "$path" =~ ^https?:// ]] && continue
    [[ "$path" =~ ^# ]] && continue

    if [ ! -f "$path" ]; then
        echo "✗ BROKEN: $link  →  $path  (file not found)"
        BROKEN=$((BROKEN + 1))
    fi
done < <(grep -oE '\]\([^)]+\)' "$SIDEBAR")

if [ $BROKEN -gt 0 ]; then
    echo ""
    echo "$BROKEN broken link(s) found in $SIDEBAR"
    exit 1
fi

echo "✓ All sidebar links valid ($SIDEBAR)"
