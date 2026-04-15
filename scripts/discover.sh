#!/usr/bin/env bash
# Pipeline orchestration: runs each agent as an independent claude -p session.
# Each step reads the previous step's output file.
#
# Usage:
#   bash scripts/discover.sh samples/
#   bash scripts/discover.sh samples/ --from 3   # resume from step 3
#   bash scripts/discover.sh samples/ --scout     # include step 0: scout public wikis
set -euo pipefail

SAMPLES_DIR="${1:?Usage: discover.sh <samples-dir> [--from N] [--scout]}"
OUTPUT_DIR="output"
FROM_STEP=1
SCOUT=false

# Parse flags
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STEP="$2"; shift 2 ;;
        --scout) SCOUT=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

run_step() {
    local step_num="$1"
    local step_name="$2"
    local agent_file="$3"
    local prompt="$4"

    if [[ "$step_num" -lt "$FROM_STEP" ]]; then
        echo "==> Step $step_num: $step_name (skipped, --from $FROM_STEP)"
        return
    fi

    echo "==> Step $step_num: $step_name"
    claude -p "$prompt" \
        --allowedTools "Read,Write,Bash,Glob,Grep,Edit" \
        2>&1 | tee "$OUTPUT_DIR/${step_name}.log"

    echo "    Done: $OUTPUT_DIR/"
}

# Step 0: Confluence Scout (optional, enabled with --scout; skipped when --from >= 1)
if [[ "$SCOUT" == "true" && "$FROM_STEP" -le 0 ]]; then
    echo "==> Step 0: confluence-scout"
    claude -p "$(cat .claude/agents/discover/confluence-scout.md)

Discover public Confluence wikis with rich macro usage. Write results to ${OUTPUT_DIR}/sources.json" \
        --allowedTools "Read,Write,Bash,Glob,Grep,Edit,WebSearch,WebFetch" \
        2>&1 | tee "$OUTPUT_DIR/confluence-scout.log"
    echo "    Done: ${OUTPUT_DIR}/sources.json"
elif [[ "$SCOUT" == "true" ]]; then
    echo "==> Step 0: confluence-scout (skipped, --from $FROM_STEP)"
else
    echo "==> Step 0: confluence-scout (skipped, use --scout to enable)"
fi

# Step 1: Pattern Discovery
run_step 1 "pattern-discovery" \
    ".claude/agents/discover/pattern-discovery.md" \
    "$(cat .claude/agents/discover/pattern-discovery.md)

Analyze the XHTML files in ${SAMPLES_DIR} and write discovered patterns to ${OUTPUT_DIR}/patterns.json"

# Step 2: Rule Proposer
run_step 2 "rule-proposer" \
    ".claude/agents/discover/rule-proposer.md" \
    "$(cat .claude/agents/discover/rule-proposer.md)

Read ${OUTPUT_DIR}/patterns.json and propose transformation rules. Write to ${OUTPUT_DIR}/proposals.json"

# Step 3: Finalize rules (2-agent shortcut: proposals → rules.json)
# When critic/arbitrator agents are added, this step will be replaced by steps 3+4.
if [[ "$FROM_STEP" -le 3 ]]; then
    echo "==> Step 3: finalize (proposals → rules.json)"
    uv run cli finalize "${OUTPUT_DIR}/proposals.json" --out "${OUTPUT_DIR}/rules.json"
    echo "    Done: ${OUTPUT_DIR}/rules.json"
fi

# Step 4: Convert XHTML → Notion blocks
if [[ "$FROM_STEP" -le 4 ]]; then
    echo "==> Step 4: convert (XHTML → Notion blocks)"
    uv run cli convert \
        --rules "${OUTPUT_DIR}/rules.json" \
        --input "${SAMPLES_DIR}" \
        --output "${OUTPUT_DIR}/converted"
    echo "    Done: ${OUTPUT_DIR}/converted/"
fi

echo ""
echo "==> Pipeline complete. Output in ${OUTPUT_DIR}/"
