Review the output of a `/develop` pipeline run.

Usage: /review-run [run-directory]

## What this does

Reads all pipeline artifacts from a completed `/develop` run and produces a comprehensive review with a final verdict (`approve` or `request-changes`).

## Artifacts reviewed

| File | Schema | What to check |
|------|--------|---------------|
| `plan.json` | `DevPlan` | Task decomposition quality vs issue requirements |
| `implement-log.json` | `DevImplementLog` | Decisions, rationale, known risks |
| `git diff` | — | Actual changes vs plan alignment |
| `review.json` | `DevReview` | Severity distribution, unresolved items |
| `circuit.json` | — | Circuit breaker state, retry history |
| `*.log` | — | Errors and warnings from each step |

## Steps

1. Parse the run directory from `$ARGUMENTS`. Default to `output/dev/` if empty.
2. Verify the directory exists and contains at least `plan.json`. If not, report what's missing and stop.
3. **Plan review** — Read `plan.json`:
   - Read `issue_number` from `plan.json`, then fetch the original issue to get requirements. Try `gh issue view <issue_number>` first; if `gh` is unavailable, use GitHub MCP tools or fall back to `issue_title` and task descriptions from the plan.
   - Assess: Does the task breakdown cover all issue requirements? Are tasks appropriately scoped? Is the dependency order correct?
   - Flag any scope gaps or over-engineering.
4. **Implementation review** — Read `implement-log.json` (if present):
   - Check that decisions align with the plan's tasks (matching `task_id`).
   - Evaluate whether rationale is sound and alternatives were considered.
   - Highlight any `known_risks` that need attention.
5. **Diff review** — Run `git diff $(git merge-base main HEAD)...HEAD` to see all changes on this branch:
   - Verify changes match what the plan specified (`affected_files`).
   - Check for unexpected file changes not in the plan.
   - Look for code quality issues: unused imports, hardcoded values, missing error handling.
   - Verify adherence to project rules (`.claude/rules/python-style.md`, `.claude/rules/testing.md`).
6. **Review findings** — Read `review.json` (if present):
   - Summarize severity distribution (errors / warnings / suggestions).
   - Check if all error-severity items were resolved.
   - Note any `intent_conflict: true` findings — these indicate the reviewer disagrees with an explicit implementer decision.
7. **Circuit breaker** — Read `circuit.json` (if present):
   - Report the final state (`CLOSED` / `OPEN` / `HALF_OPEN`).
   - If retries occurred (`attempt > 0`), summarize what happened.
8. **Logs** — Scan `*.log` files in the run directory:
   - Grep for `error`, `Error`, `ERROR`, `warning`, `Warning`, `WARN`, `Traceback`, `FAILED`.
   - Report any notable findings per step log.
9. **Verdict** — Based on all findings, produce one of:
   - **approve** — All requirements met, no blocking issues, code quality acceptable.
   - **comment** — No blocking issues, but has observations or suggestions worth noting.
   - **request-changes** — With specific, actionable items grouped by severity.

   Present the verdict in this format:

   ```
   ## Summary

   | Aspect | Assessment |
   |--------|------------|
   | Plan coverage | Full / Partial / Missing items |
   | Implementation | Aligned / Diverged from plan |
   | Code quality | Clean / Issues found |
   | Review findings | All resolved / N unresolved |
   | Circuit breaker | CLOSED / Events occurred |

   ## Verdict: approve / comment / request-changes

   [Reasoning and specific items if request-changes]
   ```
