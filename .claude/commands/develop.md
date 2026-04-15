Run the automated development pipeline for a GitHub issue.

Usage: /develop <issue-number> [--from N]

## What this does

Executes `scripts/develop.sh` which runs a 7-step pipeline:

1. **Plan** (agent) — issue → task breakdown → `output/dev/plan.json`
2. **Implement** (agent) — TDD: tests first, then code
3. **Test** (cli) — `ruff + mypy + pytest`
4. **Review** (agent) — self code review → `output/dev/review.json`
5. **Fix** (agent) — resolve review issues
6. **Verify** (cli) — final `ruff + mypy + pytest`
7. **PR** (cli) — `gh pr create --draft`

Includes circuit breaker: if fix loop makes no progress, re-plans with a different approach.

## Steps

1. Parse the issue number from `$ARGUMENTS`. If empty, ask the user for the issue number.
2. Create a feature branch `feat/issue-<number>` if on main.
3. Run: `bash scripts/develop.sh $ARGUMENTS`
4. Stream the output so the user can follow progress.
5. When complete, report:
   - Branch name
   - Files changed
   - PR URL (if created)
   - Any circuit breaker events
