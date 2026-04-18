#!/usr/bin/env bash
set -euo pipefail

# Optional flags:
#   --llm-judge            Opt into the Anthropic-backed LLM-as-judge pass.
#                          Default off so CI runs incur no API cost.
#   --fail-on-regression   Exit non-zero when baseline comparison detects a
#                          regression. Default warn-only per ADR-004.
EVAL_FLAGS=()
for arg in "$@"; do
  case "$arg" in
    --llm-judge)
      EVAL_FLAGS+=("--llm-judge")
      ;;
    --fail-on-regression)
      EVAL_FLAGS+=("--fail-on-regression")
      ;;
    *)
      echo "ERROR: unknown argument '$arg'. Supported: --llm-judge, --fail-on-regression" >&2
      exit 2
      ;;
  esac
done

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

# Step 3: Semantic coverage + baseline diff (+ optional LLM-as-judge)
echo "--- Semantic coverage + baseline ---"
uv run python -m confluence_to_notion.eval output/ eval_results/ samples/ ${EVAL_FLAGS[@]+"${EVAL_FLAGS[@]}"}
