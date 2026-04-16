#!/usr/bin/env bash
set -euo pipefail

echo "==> Running eval pipeline..."

# Step 1: Validate actual outputs exist
if [[ ! -f output/patterns.json ]]; then
  echo "ERROR: output/patterns.json not found. Run the discovery pipeline first."
  exit 1
fi

if [[ ! -f output/proposals.json ]]; then
  echo "ERROR: output/proposals.json not found. Run the discovery pipeline first."
  exit 1
fi

# Step 2: Validate schemas
echo "--- Validating output schemas ---"
uv run cli validate-output output/patterns.json discovery
uv run cli validate-output output/proposals.json proposer

# Step 3: Run comparison against expected fixtures
echo "--- Comparing against expected fixtures ---"
uv run python -m confluence_to_notion.eval output/ tests/fixtures/eval/ eval_results/
