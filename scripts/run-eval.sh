#!/usr/bin/env bash
set -euo pipefail

echo "==> Running rule evaluation..."
echo "[STUB] Eval framework not yet implemented (Day 4)"
echo ""
echo "This script will:"
echo "  1. Load rules from rules.json"
echo "  2. Apply rules to sample XHTML in samples/"
echo "  3. Compare output against expected fixtures"
echo "  4. Report pass/fail per sample"
echo ""
echo "For now, running tests as a sanity check:"
uv run pytest -v
