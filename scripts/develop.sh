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
#   3. Test      (cli)    — pnpm lint + typecheck + test (matches CI)
#   4. Review    (agent)  — diff + plan → output/dev/review.json
#   5. Fix       (agent)  — review issues → code fixes
#   6. Verify    (cli)    — pnpm lint + typecheck + test (final)
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

# --- Helper: apply protected-paths.patch emitted by an agent ---
#
# Subagents emit a unified diff to $OUTPUT_DIR/protected-paths.patch when they
# need to edit `.claude/` paths that are write-protected from their session.
# The orchestrator owns the apply step — agents are instructed not to run
# `git apply` themselves.
#
# Idempotency: in practice an agent may still reason its way around the prompt
# and self-apply the patch (issue #191 — implementer ran `git apply` in its own
# session, then this helper failed re-applying the same diff). To survive that
# slip, the helper now:
#   1. `git apply --check` — if clean, apply (the normal path).
#   2. Else `git apply --reverse --check` — if clean, the patch is already in
#      the tree (likely self-applied by the agent). Log it, drop the patch
#      file, return 0 so the pipeline continues.
#   3. Else fail loud (preserve patch file, dump first 50 lines) — a genuinely
#      broken patch must not be silently skipped, or the PR ends up missing
#      intended protected-path changes.
apply_protected_patch() {
    local step_num="$1"
    local source_label="$2"

    if [[ "$step_num" -lt "$FROM_STEP" ]]; then
        return 0
    fi

    local patch_file="$OUTPUT_DIR/protected-paths.patch"
    if [[ ! -f "$patch_file" ]]; then
        return 0
    fi
    if [[ ! -s "$patch_file" ]]; then
        echo "    [protected-patch] empty patch file from $source_label — removing"
        rm -f "$patch_file"
        return 0
    fi

    echo "==> Applying protected-paths.patch (emitted by $source_label)"
    if git apply --check "$patch_file" >/dev/null 2>&1; then
        if git apply --verbose "$patch_file"; then
            echo "    [protected-patch] applied successfully"
            rm -f "$patch_file"
            return 0
        fi
        echo "[ERROR] git apply failed on $patch_file (after --check passed)"
        echo "    Patch preserved for manual inspection. First 50 lines:"
        head -50 "$patch_file"
        return 1
    fi

    if git apply --reverse --check "$patch_file" >/dev/null 2>&1; then
        echo "    [protected-patch] already applied (likely self-applied by agent) — skipping"
        rm -f "$patch_file"
        return 0
    fi

    echo "[ERROR] git apply failed on $patch_file"
    echo "    Patch preserved for manual inspection. First 50 lines:"
    head -50 "$patch_file"
    return 1
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

    echo "    Running pnpm lint..."
    pnpm lint || return 1

    echo "    Running pnpm typecheck..."
    pnpm typecheck || return 1

    echo "    Running pnpm test..."
    pnpm test || return 1

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

# --- Helper: stage intended changes (Step 7) ---
#
# Replaces the old static allow-list (`git add src/ tests/ scripts/ .claude/ ...`)
# which silently dropped doc-only changes (CONTRIBUTING.md, docs/*) the implementer
# made outside the hardcoded directories.
#
# Behavior:
#   1. Collect ALL working-tree changes (tracked diff vs HEAD + untracked) via
#      null-delimited git output, so paths with spaces survive.
#   2. Filter pipeline artifacts (output/, eval_results/, samples/) — these are
#      committed manually elsewhere or are local-only.
#   3. Refuse (exit 1) if any sensitive-looking path appears (.env, *.pem, *.key,
#      credentials*, *secret*, case-insensitive). Matches CLAUDE.md "Never commit
#      secrets". User must resolve manually rather than auto-stage.
#      Escape hatch: DEVELOP_ALLOW_SENSITIVE="path/a,path/b" reclassifies the
#      named paths as stageable (use only after confirming the match is a false
#      positive — e.g. docs/secrets-rotation.md).
#   4. Compare the filtered set against plan.json's affected_files + test_files;
#      log [drift] WARNINGS for unplanned changes and planned-but-unchanged paths.
#      Drift does NOT fail the step — DoD is "make silent loss visible", not "block".
#      Baseline includes test_files (not just affected_files) because TDD-emitted
#      tests are equally "planned" — drift on tests is as informative as on src.
#   5. If filtered set is empty, exit 1 explicitly (clearer than an opaque
#      `git commit` "nothing to commit" error).
stage_intended_changes() {
    local plan_path="$OUTPUT_DIR/plan.json"
    local stage_plan_file
    stage_plan_file=$(mktemp)
    # Exception-safe cleanup: fires on success, early-return, or set -e abort.
    trap 'rm -f "$stage_plan_file"' RETURN

    if ! python3 - "$plan_path" "$stage_plan_file" <<'PYEOF'
import json
import os
import re
import subprocess
import sys
from pathlib import Path

plan_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])


def git_z(args: list[str]) -> list[str]:
    try:
        r = subprocess.run(["git", *args], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return []
    return [p.decode("utf-8") for p in r.stdout.split(b"\x00") if p]


tracked = git_z(["diff", "HEAD", "--name-only", "-z"])
untracked = git_z(["ls-files", "--others", "--exclude-standard", "-z"])

seen: set[str] = set()
unique: list[str] = []
for p in tracked + untracked:
    if p not in seen:
        seen.add(p)
        unique.append(p)

ARTIFACT_PREFIXES = ("output/", "eval_results/", "samples/")
SENSITIVE_PATTERNS = [
    re.compile(r"(?:^|/)\.env$", re.IGNORECASE),
    re.compile(r"(?:^|/)\.env\.", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
    re.compile(r"(?:^|/)credentials", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
]

allow_sensitive = {
    p.strip()
    for p in os.environ.get("DEVELOP_ALLOW_SENSITIVE", "").split(",")
    if p.strip()
}

artifacts: list[str] = []
sensitive: list[str] = []
allowed: list[str] = []
stageable: list[str] = []
for p in unique:
    if any(p.startswith(prefix) for prefix in ARTIFACT_PREFIXES):
        artifacts.append(p)
        continue
    if any(pat.search(p) for pat in SENSITIVE_PATTERNS):
        if p in allow_sensitive:
            allowed.append(p)
            stageable.append(p)
            continue
        sensitive.append(p)
        continue
    stageable.append(p)

planned: list[str] = []
if plan_path.exists():
    try:
        plan = json.loads(plan_path.read_text())
    except json.JSONDecodeError:
        plan = {}
    for t in plan.get("tasks", []) or []:
        for f in (t.get("affected_files") or []):
            if f not in planned:
                planned.append(f)
        for f in (t.get("test_files") or []):
            if f not in planned:
                planned.append(f)

out_path.write_text(json.dumps({
    "stageable": stageable,
    "sensitive": sensitive,
    "allowed_sensitive": allowed,
    "artifacts_skipped": artifacts,
    "planned": planned,
}, indent=2))
PYEOF
    then
        echo "[ERROR] Step 7: failed to compute stage plan"
        return 1
    fi

    # Surface DEVELOP_ALLOW_SENSITIVE reclassifications so the user sees what was waived.
    local allowed_lines
    allowed_lines=$(python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for p in data.get('allowed_sensitive', []):
    print(f'    [allow-sensitive] reclassified as stageable: {p}')
" "$stage_plan_file")
    if [[ -n "$allowed_lines" ]]; then
        echo "$allowed_lines"
    fi

    # Refuse on sensitive paths.
    local sensitive_lines
    sensitive_lines=$(python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for p in data['sensitive']:
    print(f'    - {p}')
" "$stage_plan_file")

    if [[ -n "$sensitive_lines" ]]; then
        echo "[ERROR] Step 7: sensitive-looking paths in working tree (refusing to stage):"
        echo "$sensitive_lines"
        echo "    Matches CLAUDE.md 'Never commit secrets'. Resolve manually:"
        echo "      1. Confirm the path is not a real secret (false positive on name?)."
        echo "      2. If safe to commit, stage + commit it yourself before re-running."
        echo "      3. If a real secret, remove it from the working tree (and rotate)."
        echo "      4. If many false positives, set DEVELOP_ALLOW_SENSITIVE=path1,path2"
        echo "         to reclassify named paths as stageable (use sparingly)."
        return 1
    fi

    # Drift logging (warnings only).
    python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
staged = set(data['stageable'])
planned = set(data['planned'])
for f in data['stageable']:
    if f not in planned:
        print(f'    [drift] unplanned change: {f}')
for f in data['planned']:
    if f not in staged:
        print(f'    [drift] planned-but-unchanged: {f}')
" "$stage_plan_file"

    # Read the stageable list as a NUL-delimited array (preserves spaces).
    local -a stageable_files=()
    while IFS= read -r -d '' f; do
        stageable_files+=("$f")
    done < <(python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
for p in data['stageable']:
    sys.stdout.buffer.write(p.encode('utf-8') + b'\x00')
" "$stage_plan_file")

    if [[ "${#stageable_files[@]}" -eq 0 ]]; then
        echo "[ERROR] Step 7: no files to commit after filtering"
        return 1
    fi

    echo "    Staging ${#stageable_files[@]} file(s):"
    local f
    for f in "${stageable_files[@]}"; do
        echo "      + $f"
    done
    # `--all` so deletions/renames stage correctly alongside modifications/additions.
    git add --all -- "${stageable_files[@]}"
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

# Apply any patch the implementer emitted for protected `.claude/**` paths (see
# apply_protected_patch docstring). Runs before Step 3 so test/lint sees the changes.
apply_protected_patch 2 "dev-implementer" || { echo "[ERROR] Step 2: protected patch apply failed"; exit 1; }

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

        # Apply any patch the fixer emitted for protected `.claude/**` paths.
        apply_protected_patch 5 "dev-fixer" || { echo "[ERROR] Step 5: protected patch apply failed"; exit 1; }
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

    # Apply any patch the re-plan implementer emitted for protected `.claude/**` paths.
    apply_protected_patch 2 "dev-implementer (re-plan)" || { echo "[ERROR] Re-plan: protected patch apply failed"; exit 1; }

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

    # Stage all working-tree changes minus artifacts/secrets, with drift logging.
    # Replaces the old hardcoded allow-list which silently dropped doc-only
    # changes outside the listed dirs (CONTRIBUTING.md, docs/*, etc.).
    if ! stage_intended_changes; then
        echo "[ERROR] Step 7: staging aborted"
        exit 1
    fi
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

- [ ] \`pnpm lint\` passes
- [ ] \`pnpm typecheck\` passes
- [ ] \`pnpm test\` passes
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
