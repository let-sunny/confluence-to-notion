#!/usr/bin/env bash
# Automated development pipeline: reads a GitHub issue and produces a draft PR.
# Each step runs as an independent claude -p session or deterministic CLI command.
# Agents communicate via files in output/dev/.
#
# Usage:
#   bash scripts/develop.sh <issue-number>
#   bash scripts/develop.sh <issue-number> --from 3   # resume from step 3
#
# Steps:
#   1. Plan      (agent)  — issue → output/dev/plan.json
#   2. Implement (agent)  — plan → code changes in working tree
#   3. Test      (cli)    — ruff + mypy + pytest
#   4. Review    (agent)  — diff + plan → output/dev/review.json
#   5. Fix       (agent)  — review issues → code fixes
#   6. Verify    (cli)    — ruff + mypy + pytest (final)
#   7. PR        (cli)    — gh pr create --draft
set -euo pipefail

ISSUE_NUMBER="${1:?Usage: develop.sh <issue-number> [--from N]}"
OUTPUT_DIR="output/dev"
FROM_STEP=1
MAX_FIX_RETRIES=3

# Parse --from flag
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM_STEP="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

# Create feature branch upfront (before any code changes)
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" == "main" ]]; then
    BRANCH_NAME="feat/issue-${ISSUE_NUMBER}"
    git checkout -b "$BRANCH_NAME" 2>/dev/null || git checkout "$BRANCH_NAME"
    echo "==> Working on branch: $BRANCH_NAME"
fi

# Preflight: stale remote branch check
# If origin/feat/issue-${ISSUE_NUMBER} already exists we refuse to continue — a stale
# remote branch from a prior run silently causes step 7 (git push) to append onto
# unknown commits. Fail early with actionable guidance (ADR-005: ambiguity → ask human).
if [[ "$FROM_STEP" -le 1 ]]; then
    PREFLIGHT_BRANCH="feat/issue-${ISSUE_NUMBER}"
    if git ls-remote --exit-code --heads origin "$PREFLIGHT_BRANCH" >/dev/null 2>&1; then
        git fetch origin "$PREFLIGHT_BRANCH" >/dev/null 2>&1 || true
        remote_sha=$(git rev-parse --short "origin/$PREFLIGHT_BRANCH" 2>/dev/null || echo "unknown")
        ahead_count=$(git rev-list --count "origin/$PREFLIGHT_BRANCH" "^main" 2>/dev/null || echo "?")
        if [[ "${DEVELOP_ALLOW_STALE_REMOTE:-0}" == "1" ]]; then
            echo "==> [WARN] Stale remote branch origin/$PREFLIGHT_BRANCH exists" \
                 "(HEAD=$remote_sha, $ahead_count commits ahead of main)."
            echo "    DEVELOP_ALLOW_STALE_REMOTE=1 set — proceeding anyway."
        else
            echo "[ERROR] Remote branch origin/$PREFLIGHT_BRANCH already exists" \
                 "(HEAD=$remote_sha, $ahead_count commits ahead of main)."
            echo "    A prior run for issue #${ISSUE_NUMBER} left a stale remote branch." \
                 "Pushing onto it would mix unrelated commits."
            echo "    Next actions:"
            echo "      1. Inspect:   git fetch origin && git log --oneline origin/$PREFLIGHT_BRANCH ^main"
            echo "      2. If safe to discard:  git push origin --delete $PREFLIGHT_BRANCH"
            echo "      3. Or override (advanced):  DEVELOP_ALLOW_STALE_REMOTE=1 bash scripts/develop.sh $ISSUE_NUMBER"
            exit 1
        fi
    fi
fi

# --- Helper: run an agent step ---
run_agent() {
    local step_num="$1"
    local step_name="$2"
    local prompt="$3"

    if [[ "$step_num" -lt "$FROM_STEP" ]]; then
        echo "==> Step $step_num: $step_name (skipped, --from $FROM_STEP)"
        return
    fi

    local log_file="$OUTPUT_DIR/${step_name}.log"
    echo "==> Step $step_num: $step_name"
    # Capture to file first, then mirror to stdout. `tee` was observed to
    # silently drop dev-reviewer output (0-byte log) under --output-format text;
    # direct redirect + cat is deterministic and survives SIGPIPE on the outer pipe.
    set +e
    claude -p "$prompt" \
        --allowedTools "Read,Write,Bash,Glob,Grep,Edit" \
        --output-format text \
        >"$log_file" 2>&1
    local exit_code=$?
    set -e
    cat "$log_file"
    if [[ "$exit_code" -ne 0 ]]; then
        echo "[ERROR] $step_name failed (exit=$exit_code)"
        return "$exit_code"
    fi
    echo "    Done: $log_file"
}

# --- Helper: run lint + type check + tests ---
run_checks() {
    local step_num="$1"
    local step_name="$2"

    if [[ "$step_num" -lt "$FROM_STEP" ]]; then
        echo "==> Step $step_num: $step_name (skipped, --from $FROM_STEP)"
        return 0
    fi

    echo "==> Step $step_num: $step_name"

    echo "    Running ruff check..."
    uv run ruff check --fix src/ tests/ || return 1
    uv run ruff check src/ tests/ || return 1

    echo "    Running mypy..."
    uv run mypy src/ || return 1

    echo "    Running pytest..."
    uv run pytest || return 1

    echo "    All checks passed."
    return 0
}

# --- Circuit breaker helpers (used by Fix+Verify loop and re-plan fallback) ---
#
# Circuit breaker states (persisted in output/dev/circuit.json):
#   CLOSED    — normal operation, fix loop runs
#   OPEN      — tripped by non-improving failures, switches to re-plan strategy
#   HALF_OPEN — after re-plan, allows ONE probe to verify the new approach
#
# Transitions:
#   CLOSED    → verify passes                  → stay CLOSED (done)
#   CLOSED    → errors not decreasing          → OPEN (re-plan)
#   CLOSED    → max retries with progress      → OPEN (re-plan)
#   OPEN      → re-plan + re-implement         → HALF_OPEN (one probe)
#   HALF_OPEN → probe passes                   → CLOSED (done)
#   HALF_OPEN → probe fails                    → exit 1 (needs manual intervention)

CIRCUIT_FILE="$OUTPUT_DIR/circuit.json"

circuit_read_state() {
    if [[ -f "$CIRCUIT_FILE" ]]; then
        python3 -c "import json; print(json.load(open('$CIRCUIT_FILE'))['state'])" 2>/dev/null || echo "CLOSED"
    else
        echo "CLOSED"
    fi
}

circuit_read_prev_errors() {
    if [[ -f "$CIRCUIT_FILE" ]]; then
        python3 -c "import json; print(json.load(open('$CIRCUIT_FILE')).get('error_count', 999))" 2>/dev/null || echo "999"
    else
        echo "999"
    fi
}

circuit_write() {
    local state="$1"
    local error_count="$2"
    local attempt="$3"
    python3 -c "
import json
json.dump({'state': '$state', 'error_count': $error_count, 'attempt': $attempt}, open('$CIRCUIT_FILE', 'w'), indent=2)
print('    [circuit] state=$state errors=$error_count attempt=$attempt')
"
}

circuit_announce() {
    # Announce current circuit state at a phase entry point.
    # Usage: circuit_announce "<context>"
    local context="$1"
    local state
    state=$(circuit_read_state)
    echo "==> circuit: $state ($context)"
}

circuit_transition() {
    # Emit a state-transition line in a uniform format.
    # Usage: circuit_transition <from> <to> "<reason>"
    local from="$1"
    local to="$2"
    local reason="$3"
    echo "==> circuit transition: $from → $to ($reason)"
}

count_errors() {
    if [[ -f "$OUTPUT_DIR/review.json" ]]; then
        python3 -c "
import json
r = json.load(open('$OUTPUT_DIR/review.json'))
print(sum(1 for i in r.get('issues', []) if i.get('severity') == 'error'))
" 2>/dev/null || echo "999"
    else
        echo "999"
    fi
}

# --- Step 1: Plan ---
run_agent 1 "dev-planner" \
    "$(cat .claude/agents/develop/dev-planner.md)

Plan the implementation for GitHub issue #${ISSUE_NUMBER}.
Write the plan to ${OUTPUT_DIR}/plan.json"

# Validate plan.json
if [[ "$FROM_STEP" -le 1 ]]; then
    echo "    Validating plan.json..."
    python3 -c "
import json, sys
plan = json.load(open('${OUTPUT_DIR}/plan.json'))
assert plan.get('issue_number'), 'missing issue_number'
assert plan.get('tasks') and len(plan['tasks']) > 0, 'missing tasks'
for t in plan['tasks']:
    assert t.get('task_id'), 'task missing task_id'
    assert t.get('affected_files') and len(t['affected_files']) > 0, f\"task {t.get('task_id')} missing affected_files\"
print(f\"Plan valid: {len(plan['tasks'])} tasks\")
" || { echo "[ERROR] plan.json validation failed"; exit 1; }
fi

# --- Step 2: Implement ---
run_agent 2 "dev-implementer" \
    "$(cat .claude/agents/develop/dev-implementer.md)

Execute the development plan in ${OUTPUT_DIR}/plan.json.
Read the plan, then implement each task in order following TDD.
After implementation, write your decisions and known risks to ${OUTPUT_DIR}/implement-log.json"

# --- Step 3: Test ---
if [[ "$FROM_STEP" -le 3 ]]; then
    if ! run_checks 3 "test"; then
        echo "[WARN] Step 3 checks failed — continuing to review for diagnosis"
    fi
fi

# --- Step 4: Review ---
circuit_announce "entering Review"
run_agent 4 "dev-reviewer" \
    "$(cat .claude/agents/develop/dev-reviewer.md)

Review the code changes against the plan in ${OUTPUT_DIR}/plan.json.
Run 'git diff HEAD' to see all changes. Write review to ${OUTPUT_DIR}/review.json"

# --- Step 5+6: Fix + Verify loop with circuit breaker ---
# Determine initial circuit state
circuit_state=$(circuit_read_state)

# OPEN from previous run + user re-ran full pipeline → reset to CLOSED, let it try fresh
if [[ "$circuit_state" == "OPEN" && "$FROM_STEP" -le 1 ]]; then
    circuit_transition "OPEN" "CLOSED" "full pipeline re-run requested — reset"
    circuit_state="CLOSED"
    circuit_write "CLOSED" 999 0
fi

# OPEN from previous run + user resumed mid-pipeline → keep OPEN, post-loop will re-plan
if [[ "$circuit_state" == "OPEN" ]]; then
    echo "==> [CIRCUIT BREAKER] Circuit OPEN from previous run — will re-plan after loop"
fi

retry=0
max_attempts=$MAX_FIX_RETRIES
if [[ "$circuit_state" == "HALF_OPEN" ]]; then
    max_attempts=1  # half-open: only one probe
fi

while [[ "$retry" -lt "$max_attempts" ]]; do
    circuit_announce "fix+verify iteration $((retry + 1))/$max_attempts"

    # Check if review approved
    if [[ -f "$OUTPUT_DIR/review.json" ]]; then
        approved=$(python3 -c "import json; print(json.load(open('$OUTPUT_DIR/review.json'))['approved'])" 2>/dev/null || echo "False")
        if [[ "$approved" == "True" ]]; then
            prev_state=$(circuit_read_state)
            if [[ "$prev_state" == "HALF_OPEN" ]]; then
                circuit_transition "HALF_OPEN" "CLOSED" "review approved after re-plan probe"
            else
                echo "==> Review approved — circuit stays CLOSED"
            fi
            circuit_write "CLOSED" 0 "$retry"
            break
        fi
    fi

    # Check progress (skip on first attempt)
    curr_errors=$(count_errors)
    prev_errors=$(circuit_read_prev_errors)
    if [[ "$retry" -gt 0 && "$curr_errors" -ge "$prev_errors" ]]; then
        prev_state=$(circuit_read_state)
        circuit_transition "$prev_state" "OPEN" "errors not decreasing ($prev_errors -> $curr_errors) — will trigger re-plan"
        circuit_write "OPEN" "$curr_errors" "$retry"
        break
    fi
    circuit_write "$circuit_state" "$curr_errors" "$retry"

    if [[ "$FROM_STEP" -le 5 ]]; then
        # Step 5: Fix
        run_agent 5 "dev-fixer" \
            "$(cat .claude/agents/develop/dev-fixer.md)

Fix the issues in ${OUTPUT_DIR}/review.json.
Read the review, then apply fixes to resolve each issue."
    fi

    if [[ "$FROM_STEP" -le 6 ]]; then
        # Step 6: Verify
        if run_checks 6 "verify"; then
            prev_state=$(circuit_read_state)
            if [[ "$prev_state" == "HALF_OPEN" ]]; then
                circuit_transition "HALF_OPEN" "CLOSED" "verify passed after re-plan probe"
            else
                echo "==> Verify passed — circuit stays CLOSED"
            fi
            circuit_write "CLOSED" 0 "$retry"
            break
        else
            echo "[WARN] Verify failed (attempt $((retry + 1))/$max_attempts)"
            retry=$((retry + 1))
            # Re-run review before next fix attempt
            if [[ "$retry" -lt "$max_attempts" ]]; then
                run_agent 4 "dev-reviewer" \
                    "$(cat .claude/agents/develop/dev-reviewer.md)

Review the code changes against the plan in ${OUTPUT_DIR}/plan.json.
Run 'git diff HEAD' to see all changes. Write review to ${OUTPUT_DIR}/review.json"
            fi
        fi
    else
        break
    fi
done

# Post-loop: handle circuit state
circuit_state=$(circuit_read_state)

if [[ "$circuit_state" == "HALF_OPEN" && "$retry" -ge "$max_attempts" ]]; then
    # Half-open probe failed — both original and re-plan approach failed
    circuit_transition "HALF_OPEN" "OPEN" "re-plan probe also failed — manual intervention required"
    circuit_write "OPEN" "$(count_errors)" "$retry"
    exit 1
fi

if [[ "$circuit_state" == "OPEN" || "$retry" -ge "$max_attempts" ]]; then
    # Re-plan fallback. The condition fires for two distinct prior states:
    #   - OPEN: errors weren't decreasing (caught mid-loop)
    #   - CLOSED: max_attempts exhausted with progress but no approval
    # Use the actual prior state in the transition log so observability matches reality.
    circuit_announce "entering re-plan fallback"
    circuit_transition "$circuit_state" "HALF_OPEN" "probing re-plan"
    circuit_write "HALF_OPEN" "$(count_errors)" 0

    run_agent 1 "dev-planner" \
        "$(cat .claude/agents/develop/dev-planner.md)

IMPORTANT: This is a RE-PLAN. The previous implementation attempt failed.
Read the previous review at ${OUTPUT_DIR}/review.json to understand what went wrong.
Read the previous plan at ${OUTPUT_DIR}/plan.json to see what was tried.

Create a NEW plan for GitHub issue #${ISSUE_NUMBER} that takes a different approach.
Write the new plan to ${OUTPUT_DIR}/plan.json"

    run_agent 2 "dev-implementer" \
        "$(cat .claude/agents/develop/dev-implementer.md)

Execute the development plan in ${OUTPUT_DIR}/plan.json.
Read the plan, then implement each task in order following TDD.
After implementation, write your decisions and known risks to ${OUTPUT_DIR}/implement-log.json"

    # Half-open probe: one verify attempt
    circuit_announce "re-plan probe verify"
    if run_checks 6 "verify-replan"; then
        circuit_transition "HALF_OPEN" "CLOSED" "re-plan succeeded"
        circuit_write "CLOSED" 0 0
    else
        circuit_transition "HALF_OPEN" "OPEN" "re-plan also failed — manual intervention required"
        circuit_write "OPEN" "$(count_errors)" 0
        exit 1
    fi
fi

# --- Step 7: Create draft PR ---
if [[ "$FROM_STEP" -le 7 ]]; then
    echo "==> Step 7: create draft PR"

    # Read issue title for PR
    ISSUE_TITLE=$(gh issue view "$ISSUE_NUMBER" --json title -q .title 2>/dev/null || echo "Issue #$ISSUE_NUMBER")

    # Stage source files only (exclude pipeline artifacts)
    git add src/ tests/ scripts/ .claude/ CLAUDE.md pyproject.toml
    git commit -m "feat: ${ISSUE_TITLE}

Automated implementation via scripts/develop.sh for issue #${ISSUE_NUMBER}.

Co-Authored-By: Claude <noreply@anthropic.com>"

    # Push and create PR
    git push -u origin HEAD
    gh pr create \
        --draft \
        --title "feat: ${ISSUE_TITLE}" \
        --body "$(cat <<EOF
## Summary

Automated implementation for #${ISSUE_NUMBER}.

Closes #${ISSUE_NUMBER}

## Pipeline

Generated by \`scripts/develop.sh ${ISSUE_NUMBER}\` — Plan, Implement, Test, Review, Fix, Verify, PR.

## Artifacts

- Plan: \`output/dev/plan.json\`
- Review: \`output/dev/review.json\`

## Test plan

- [ ] \`uv run ruff check src/ tests/\` passes
- [ ] \`uv run mypy src/\` passes
- [ ] \`uv run pytest\` passes
- [ ] Manual review of changes against issue requirements
EOF
)"

    echo "    Done: Draft PR created"

    # --- Handle split issues: create follow-up issue + mark progress ---
    if [[ -f "$OUTPUT_DIR/plan.json" ]]; then
        is_split=$(python3 -c "import json; print(json.load(open('$OUTPUT_DIR/plan.json')).get('split', False))" 2>/dev/null || echo "False")

        if [[ "$is_split" == "True" ]]; then
            remaining=$(python3 -c "import json; print(json.load(open('$OUTPUT_DIR/plan.json')).get('remaining_description', ''))" 2>/dev/null || echo "")
            completed_tasks=$(python3 -c "
import json
plan = json.load(open('$OUTPUT_DIR/plan.json'))
for t in plan['tasks']:
    print(f\"- [x] {t['title']}\")
" 2>/dev/null || echo "")

            if [[ -n "$remaining" ]]; then
                echo "==> Issue was split — creating follow-up issue for remaining work"

                FOLLOW_UP_URL=$(gh issue create \
                    --title "cont: ${ISSUE_TITLE} (remaining)" \
                    --body "$(cat <<SPLITEOF
## Continuation of #${ISSUE_NUMBER}

This is auto-generated follow-up for remaining work.

## Completed in previous PR
${completed_tasks}

## Remaining work
${remaining}

---
Parent issue: #${ISSUE_NUMBER}
SPLITEOF
)" 2>/dev/null || echo "")

                if [[ -n "$FOLLOW_UP_URL" ]]; then
                    echo "    Follow-up issue: $FOLLOW_UP_URL"

                    # Mark progress on original issue
                    gh issue comment "$ISSUE_NUMBER" \
                        --body "## Progress update

${completed_tasks}

Remaining work tracked in ${FOLLOW_UP_URL}
PR: $(git log -1 --format='%s')" 2>/dev/null || true
                fi
            fi
        fi
    fi
fi

echo ""
echo "==> Pipeline complete for issue #${ISSUE_NUMBER}"
