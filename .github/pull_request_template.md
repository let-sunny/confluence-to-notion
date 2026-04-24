## Summary

<!-- 1–3 bullets describing what this PR changes. -->

-
-

Closes #

## Eval report (discover-pipeline merge gate)

Did this PR touch `.claude/agents/discover/pattern-discovery.md` or
`.claude/agents/discover/rule-proposer.md`? (Other agents — including
`.claude/agents/develop/*` — are **not** gated.)

- [ ] **Yes** — ran `bash scripts/run-eval.sh` and attached the summary below.
      Default gate: **schema validation + semantic coverage + baseline diff**
      (see ADR-006 / CLAUDE.md).
- [ ] **No** — N/A, discover-pipeline untouched.

If yes, fill in:

- Report file: `eval_results/<timestamp>.json`
- Semantic coverage: `<e.g. 0.92 (+0.01 vs baseline)>`
- Baseline diff: `<no regression | regression summary + justification>`
- LLM-judge (opt-in, `--llm-judge`): `<e.g. avg 4.3 / 5, N samples | not run>`

> LLM-as-judge is off by default (API cost). Use `--llm-judge` when you want
> it; use `--fail-on-regression` to make regressions hard-fail.

## Test plan

- [ ] `pnpm test` passes
- [ ] `pnpm lint` passes
- [ ] `pnpm typecheck` passes
- [ ] Manual verification (describe if applicable):

## Checklist

- [ ] PR body and title are in English (`CLAUDE.md > Language`).
- [ ] Linked the related issue with `Closes #<n>` above.
