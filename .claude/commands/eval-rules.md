Evaluate the current transformation rules against sample Confluence pages.

## Steps

1. Load rules from the latest `rules.json` (or path provided via $ARGUMENTS).
2. Load sample XHTML files from `samples/`.
3. For each sample page:
   - Apply rules to transform XHTML → Notion blocks
   - Compare output against expected output in `tests/fixtures/eval/`
   - Report: match, partial match, or mismatch with diff
4. Print summary table: total samples, pass rate, failing cases.
5. If any prompt files changed since last eval (check git diff), warn:
   "Prompt files changed — ensure eval results are reviewed before merging."
6. Save eval report to `eval_results/` with timestamp.

Refer to `.claude/rules/prompts.md` for prompt change policies.
