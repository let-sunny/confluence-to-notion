#!/usr/bin/env bash
# Scout pipeline: discover public Confluence wikis, fetch pages, run discovery.
#
# Chains:
#   1. Run confluence-scout agent → output/sources.json
#   2. Parse sources.json for new accessible sources (fetched_at == null)
#   Per new source:
#     3. Fetch pages into samples/<space_key>/
#     4. Run discover.sh
#     5. Stamp fetched_at (only after both 3+4 succeed; failures retry next run)
#
# Usage:
#   bash scripts/scout-pipeline.sh
#   bash scripts/scout-pipeline.sh --dry-run   # preview without executing
#
# Note: --dry-run with no existing sources.json exits after Step 1 (nothing to preview).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${PROJECT_DIR}/output"
SOURCES_FILE="${OUTPUT_DIR}/sources.json"
DRY_RUN=false

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Require jq for JSON processing in Steps 2-5
if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required but not installed. Install it with: brew install jq"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# --- Step 1: Run confluence-scout agent ---
echo "==> Step 1: confluence-scout agent"
if [[ "$DRY_RUN" == "true" ]]; then
    echo "    [dry-run] Would run confluence-scout agent"
    if [[ ! -f "$SOURCES_FILE" ]]; then
        echo "    [dry-run] No existing sources.json — nothing to preview"
        exit 0
    fi
else
    claude -p "$(cat "${PROJECT_DIR}/.claude/agents/discover/confluence-scout.md")

Discover public Confluence wikis with rich macro usage. Write results to ${OUTPUT_DIR}/sources.json" \
        --allowedTools "Read,Write,Bash,Glob,Grep,Edit,WebSearch,WebFetch" \
        2>&1 | tee "$OUTPUT_DIR/confluence-scout.log"
    echo "    Done: ${SOURCES_FILE}"
fi

# --- Step 2: Find new accessible sources (fetched_at == null) ---
echo ""
echo "==> Step 2: Find new accessible sources"

if [[ ! -f "$SOURCES_FILE" ]]; then
    echo "    ERROR: ${SOURCES_FILE} not found"
    exit 1
fi

# Extract sources where accessible==true AND fetched_at==null
NEW_SOURCES=$(jq -r '.sources[] | select(.accessible == true and .fetched_at == null) | "\(.wiki_url)|\(.space_key)"' "$SOURCES_FILE")

if [[ -z "$NEW_SOURCES" ]]; then
    echo "    No new sources to process. All accessible sources already fetched."
    exit 0
fi

echo "    New sources found:"
echo "$NEW_SOURCES" | while IFS='|' read -r url key; do
    echo "      - ${key} @ ${url}"
done

# --- Steps 3-5: For each new source: fetch, discover, stamp fetched_at ---
# fetched_at is set only after discover succeeds, so failed sources are retried next run.
# One source failing does not block subsequent sources.
echo ""
FAILED_SOURCES=""

while IFS='|' read -r wiki_url space_key; do
    SAMPLES_SUBDIR="${PROJECT_DIR}/samples/${space_key}"

    # Step 3: Fetch pages
    echo "==> Step 3: Fetch pages for ${space_key} from ${wiki_url}"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "    [dry-run] Would run: CONFLUENCE_BASE_URL=${wiki_url} uv run c2n fetch --space ${space_key} --limit 50 --out-dir ${SAMPLES_SUBDIR}"
    else
        mkdir -p "$SAMPLES_SUBDIR"
        if ! CONFLUENCE_BASE_URL="${wiki_url}" uv run c2n fetch \
            --space "$space_key" \
            --limit 50 \
            --out-dir "$SAMPLES_SUBDIR"; then
            echo "    FAILED: fetch for ${space_key} — skipping"
            FAILED_SOURCES="${FAILED_SOURCES}${space_key} (fetch), "
            echo ""
            continue
        fi
        echo "    Done: ${SAMPLES_SUBDIR}/"
    fi

    # Step 4: Run discovery pipeline
    echo "==> Step 4: Run discover.sh for ${space_key}"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "    [dry-run] Would run: bash scripts/discover.sh ${SAMPLES_SUBDIR}"
    else
        if ! bash "${SCRIPT_DIR}/discover.sh" "$SAMPLES_SUBDIR"; then
            echo "    FAILED: discover for ${space_key} — skipping"
            FAILED_SOURCES="${FAILED_SOURCES}${space_key} (discover), "
            echo ""
            continue
        fi
        echo "    Done: discovery pipeline for ${space_key}"
    fi

    # Step 5: Stamp fetched_at (only after fetch + discover both succeed)
    echo "==> Step 5: Update fetched_at for ${space_key}"
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "    [dry-run] Would set fetched_at=${TIMESTAMP} for ${space_key}"
    else
        jq --arg key "$space_key" --arg ts "$TIMESTAMP" \
            '(.sources[] | select(.space_key == $key)) .fetched_at = $ts' \
            "$SOURCES_FILE" > "${SOURCES_FILE}.tmp" \
            && mv "${SOURCES_FILE}.tmp" "$SOURCES_FILE"
        echo "    Done: fetched_at=${TIMESTAMP}"
    fi

    echo ""
done <<< "$NEW_SOURCES"

# Report results
if [[ -n "$FAILED_SOURCES" ]]; then
    echo "==> Scout pipeline complete with failures: ${FAILED_SOURCES%, }"
    exit 1
else
    echo "==> Scout pipeline complete."
fi
