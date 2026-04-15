#!/usr/bin/env bash
# Pipeline orchestration: runs each agent as an independent claude -p session.
# Each step reads the previous step's output file.
#
# Usage:
#   bash scripts/discover.sh samples/
#   bash scripts/discover.sh samples/ --from 3   # resume from step 3
set -euo pipefail

SAMPLES_DIR="${1:?Usage: discover.sh <samples-dir> [--from N]}"
OUTPUT_DIR="output"
FROM_STEP=1

# Parse --from flag
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STEP="$2"; shift 2 ;;
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

# Step 1: Pattern Discovery
run_step 1 "pattern-discovery" \
    ".claude/agents/pattern-discovery.md" \
    "$(cat .claude/agents/pattern-discovery.md)

Analyze the XHTML files in ${SAMPLES_DIR} and write discovered patterns to ${OUTPUT_DIR}/patterns.json"

# Step 2: Rule Proposer
run_step 2 "rule-proposer" \
    ".claude/agents/rule-proposer.md" \
    "$(cat .claude/agents/rule-proposer.md)

Read ${OUTPUT_DIR}/patterns.json and propose transformation rules. Write to ${OUTPUT_DIR}/proposals.json"

# Step 3: Rule Critic (deferred — agent not yet implemented)
if [[ -f ".claude/agents/rule-critic.md" ]]; then
    run_step 3 "rule-critic" \
        ".claude/agents/rule-critic.md" \
        "$(cat .claude/agents/rule-critic.md)

Read ${OUTPUT_DIR}/proposals.json, validate against XHTML samples in ${SAMPLES_DIR}. Write to ${OUTPUT_DIR}/critiques.json"
else
    echo "==> Step 3: rule-critic (skipped, agent not implemented)"
fi

# Step 4: Rule Arbitrator (deferred — agent not yet implemented)
if [[ -f ".claude/agents/rule-arbitrator.md" ]]; then
    run_step 4 "rule-arbitrator" \
        ".claude/agents/rule-arbitrator.md" \
        "$(cat .claude/agents/rule-arbitrator.md)

Read ${OUTPUT_DIR}/critiques.json, resolve conflicts. Write final rules to ${OUTPUT_DIR}/rules.json"
else
    echo "==> Step 4: rule-arbitrator (skipped, agent not implemented)"
fi

echo ""
echo "==> Pipeline complete. Output in ${OUTPUT_DIR}/"
