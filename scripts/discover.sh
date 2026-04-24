#!/usr/bin/env bash
# Pipeline orchestration: runs each agent as an independent claude -p session.
# Each step reads the previous step's output file.
#
# Usage:
#   bash scripts/discover.sh samples/ --url <confluence-url>
#   bash scripts/discover.sh samples/ --url <url> --from 3   # resume from step 3
#   bash scripts/discover.sh samples/ --url <url> --scout    # include step 0: scout public wikis
set -euo pipefail

SAMPLES_DIR="${1:?Usage: discover.sh <samples-dir> --url <confluence-url> [--from N] [--scout]}"
OUTPUT_DIR="output"
FROM_STEP=1
SCOUT=false
URL=""

# Parse flags
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STEP="$2"; shift 2 ;;
        --scout) SCOUT=true; shift ;;
        --url) URL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "$FROM_STEP" -le 4 && -z "$URL" ]]; then
    echo "[ERROR] --url <confluence-url> is required when step 4 (convert) runs."
    echo "        Example: --url https://cwiki.apache.org/confluence/display/KAFKA/Home"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

check_output() {
    local file="$1"
    local step_name="$2"
    if [[ ! -f "$file" ]]; then
        echo "[ERROR] Step '$step_name' did not produce expected output: $file"
        echo "        Check the log: ${OUTPUT_DIR}/${step_name}.log"
        exit 1
    fi
}

run_step() {
    local step_num="$1"
    local step_name="$2"
    local prompt="$3"

    if [[ "$step_num" -lt "$FROM_STEP" ]]; then
        echo "==> Step $step_num: $step_name (skipped, --from $FROM_STEP)"
        return
    fi

    echo "==> Step $step_num: $step_name"
    if ! claude -p "$prompt" \
        --allowedTools "Read,Write,Bash,Glob,Grep,Edit" \
        2>&1 | tee "$OUTPUT_DIR/${step_name}.log"; then
        echo "[ERROR] Step $step_num ($step_name) failed."
        echo "        Log: ${OUTPUT_DIR}/${step_name}.log"
        exit 1
    fi

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
    "$(cat .claude/agents/discover/pattern-discovery.md)

Analyze the XHTML files in ${SAMPLES_DIR} and write discovered patterns to ${OUTPUT_DIR}/patterns.json"

if [[ "$FROM_STEP" -le 1 ]]; then
    check_output "${OUTPUT_DIR}/patterns.json" "pattern-discovery"
fi

# Step 2: Rule Proposer
run_step 2 "rule-proposer" \
    "$(cat .claude/agents/discover/rule-proposer.md)

Read ${OUTPUT_DIR}/patterns.json and propose transformation rules. Write to ${OUTPUT_DIR}/proposals.json"

if [[ "$FROM_STEP" -le 2 ]]; then
    check_output "${OUTPUT_DIR}/proposals.json" "rule-proposer"
fi

# Step 3: Finalize rules (2-agent shortcut: proposals → rules.json)
# When critic/arbitrator agents are added, this step will be replaced by steps 3+4.
if [[ "$FROM_STEP" -le 3 ]]; then
    echo "==> Step 3: finalize (proposals → rules.json)"
    if ! pnpm exec c2n finalize "${OUTPUT_DIR}/proposals.json" --out "${OUTPUT_DIR}/rules.json"; then
        echo "[ERROR] Step 3 (finalize) failed."
        echo "        Input: ${OUTPUT_DIR}/proposals.json"
        exit 1
    fi
    check_output "${OUTPUT_DIR}/rules.json" "finalize"
    echo "    Done: ${OUTPUT_DIR}/rules.json"
fi

# Step 4: Convert XHTML → Notion blocks (artifacts land under output/runs/<slug>/converted/)
if [[ "$FROM_STEP" -le 4 ]]; then
    echo "==> Step 4: convert (XHTML → Notion blocks)"
    if ! pnpm exec c2n convert \
        --rules "${OUTPUT_DIR}/rules.json" \
        --input "${SAMPLES_DIR}" \
        --url "${URL}"; then
        echo "[ERROR] Step 4 (convert) failed."
        echo "        Rules: ${OUTPUT_DIR}/rules.json"
        echo "        Input: ${SAMPLES_DIR}"
        echo "        URL:   ${URL}"
        exit 1
    fi
    echo "    Done: ${OUTPUT_DIR}/runs/<slug>/converted/ (slug derived from --url)"
fi

echo ""
echo "==> Pipeline complete. Output in ${OUTPUT_DIR}/"
