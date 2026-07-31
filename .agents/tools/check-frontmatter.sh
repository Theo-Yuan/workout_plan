#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

KNOWLEDGE_DIR="knowledge"
ERRORS=0
VALID_TYPES="index principle guide knowledge reference"

for md in "$KNOWLEDGE_DIR"/*.md; do
    [ ! -f "$md" ] && continue
    filename="$(basename "$md")"

    # Skip WORKFLOW.md — meta doc, no frontmatter required
    [ "$filename" = "WORKFLOW.md" ] && continue

    # Check for frontmatter block
    first_line="$(head -1 "$md")"
    if [ "$first_line" != "---" ]; then
        echo "✗ $filename: missing frontmatter (no opening ---)"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    # Extract frontmatter
    fm="$(sed -n '2,/^---$/p' "$md" | sed '$d')"

    if ! echo "$fm" | grep -q '^type:'; then
        echo "✗ $filename: missing 'type' field"
        ERRORS=$((ERRORS + 1))
    else
        ftype="$(echo "$fm" | grep '^type:' | sed 's/^type: *//')"
        if ! echo "$VALID_TYPES" | grep -qw "$ftype"; then
            echo "✗ $filename: invalid type '$ftype' (allowed: $VALID_TYPES)"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    if ! echo "$fm" | grep -q '^tags:'; then
        echo "✗ $filename: missing 'tags' field"
        ERRORS=$((ERRORS + 1))
    fi

    if ! echo "$fm" | grep -q '^updated:'; then
        echo "✗ $filename: missing 'updated' field"
        ERRORS=$((ERRORS + 1))
    elif ! echo "$fm" | grep -qE '^updated: [0-9]{4}-[0-9]{2}-[0-9]{2}'; then
        echo "✗ $filename: invalid 'updated' date format (expected YYYY-MM-DD)"
        ERRORS=$((ERRORS + 1))
    fi
done

if [ $ERRORS -gt 0 ]; then
    echo ""
    echo "$ERRORS frontmatter error(s) found in $KNOWLEDGE_DIR/"
    exit 1
fi

echo "✓ All frontmatter valid ($KNOWLEDGE_DIR/)"
