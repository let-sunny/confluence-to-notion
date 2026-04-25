# Contributing

Thanks for your interest in `confluence-to-notion`. This project uses a Claude
Code subagent pipeline to discover Confluence → Notion transformation rules
and a deterministic TypeScript converter to apply them.

This document covers development setup, adding a new agent, the prompt-change
policy, testing, PR rules, and code style. Deeper rules live in
`.claude/rules/*.md`; each section links to the relevant file.

---

## 1. Development environment setup

### Requirements

- Node 20 LTS (matches `.nvmrc`)
- [pnpm](https://pnpm.io/) 9+
- [Claude Code CLI](https://docs.claude.com/claude-code) (`claude`) — needed
  to run the discovery agents locally
- Confluence / Notion API credentials (for manual migration runs)

### Install

```bash
git clone https://github.com/let-sunny/confluence-to-notion.git
cd confluence-to-notion
pnpm install
cp .env.example .env
```

### Environment variables

Set these in `.env`. Public wikis only need `CONFLUENCE_BASE_URL`.

| Name | Required | Description |
| --- | --- | --- |
| `CONFLUENCE_BASE_URL` | ✓ | Confluence base URL (e.g. `https://cwiki.apache.org/confluence`). |
| `CONFLUENCE_EMAIL` | private only | Atlassian account email. |
| `CONFLUENCE_API_TOKEN` | private only | Atlassian API token. |
| `CONFLUENCE_API_PATH` | optional | Self-hosted path override (default `/rest/api`). |
| `NOTION_API_TOKEN` | ✓ (for Notion writes) | Notion integration token (`ntn_…` or `secret_…`). |
| `NOTION_ROOT_PAGE_ID` | ✓ (for Notion writes) | Target Notion parent page id. |

### Verify

```bash
pnpm test        # vitest
pnpm lint        # biome check
pnpm typecheck   # tsc --noEmit
pnpm build       # tsup → dist/cli.js + dist/mcp.js
```

---

## 2. Adding an agent

Agents are **Claude Code subagents**; each runs in its own `claude -p` session
with a **clean context**. They communicate only via files on disk.

### 2.1 Agent definition file

Create a markdown file at `.claude/agents/<pipeline>/<name>.md`. Both the
pipeline directory and the file name are kebab-case.

Agent files follow this order (see `.claude/rules/prompts.md`):

1. **Purpose** — one line summarising what the agent does.
2. **Input** — files the agent reads and their expected format.
3. **Output** — files the agent produces and their expected format.
4. **Instructions** — detailed prompt (constraints, examples).
5. **Output schema reference** — which zod/Pydantic model the output must match.

### 2.2 Schema-as-contract rule

Agent output schemas are code-first.

1. Define a zod schema in `src/**/schemas.ts`.
2. The agent produces JSON compatible with that schema.
3. The orchestration script validates the output via `c2n validate-output
   <file> <schema>`.

Because the schema is the contract, agent prompts must reference it and
include examples.

### 2.3 Pipeline wiring

Orchestration is a **bash script** (`scripts/discover.sh`,
`scripts/develop.sh`), not a Claude slash command. Flow control must be
visible in code — not hidden in LLM judgement.

Follow the existing `run_step` / `run_agent` helpers when adding a stage.
Concatenate the agent body and the runtime directives (input/output paths)
into a single prompt.

```bash
# scripts/discover.sh — e.g. pattern-discovery step
claude -p "$(cat .claude/agents/discover/pattern-discovery.md)

Analyze the XHTML files in samples/ and write discovered patterns to output/patterns.json" \
  --allowedTools "Read,Write,Bash,Glob,Grep,Edit"
```

`scripts/develop.sh` uses the same `run_agent` helper. Each stage reads files
produced by the previous stage and writes files for the next. Every stage must
be re-runnable via `--from N`.

### 2.4 File-based communication

- Inputs are files on disk (e.g. `samples/*.xhtml`, `output/patterns.json`).
- Outputs are files on disk (e.g. `output/rules.json`, `output/dev/plan.json`).
- **No** shared memory or context injection between agents.

Related rules: [`.claude/rules/agents.md`](./.claude/rules/agents.md),
[`.claude/rules/prompts.md`](./.claude/rules/prompts.md).

---

## 3. Prompt modification policy

PRs that change `.claude/agents/discover/*.md` (the discover pipeline) **must**
run the eval gate before merge:

```bash
bash scripts/run-eval.sh
```

- Results land in `eval_results/<timestamp>.json`.
- The gate combines schema validation + semantic coverage + baseline diff (see
  ADR-006).

If there is a regression, either fix the prompt and re-run, or — when the
change is intentional — update the baseline and explain why in the PR body.

Develop-pipeline prompts (`dev-planner`, `dev-implementer`, `dev-reviewer`,
`dev-fixer`) are **not** gated by eval.

Reference: [`.claude/rules/prompts.md`](./.claude/rules/prompts.md).

---

## 4. Testing guide

### TDD cycle

TypeScript code in `src/` is written **test-first**.

1. **Red** — write a failing test.
2. **Green** — minimum change to make it pass.
3. **Refactor** — improve while keeping behaviour.

### Tools and layout

- Test runner: `vitest` (+ `@vitest/coverage-v8`).
- Test file naming: `*.test.ts` under `tests/`.
- Shared fixtures under `tests/fixtures/`.
- External I/O (Confluence, Notion, Anthropic) must be mocked in unit tests.
  HTTP mocks use `undici`'s `MockAgent` or `msw`.
- Integration tests live under `tests/integration/` and are opt-in.

### Run

```bash
pnpm test                            # vitest run
pnpm test:watch                      # vitest
pnpm test tests/cli.test.ts          # single file
```

Reference: [`.claude/rules/testing.md`](./.claude/rules/testing.md).

---

## 5. Pull request rules

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <subject>

[optional body]
```

Accepted types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

### PR workflow

- **Squash merge only** — the PR becomes one commit on `main`.
- Link the related issue in the PR body with `Closes #N` so the merge
  auto-closes it.
- Keep PRs small and focused. Split unrelated concerns.
- Every PR must be **in English** — title, body, commit messages, inline
  discussion. Conversation with Claude may be in Korean, but the repo-bound
  artefacts are English (see `CLAUDE.md > Language`).
- If the PR changes `.claude/agents/discover/*.md`, attach the eval summary
  per section 3.

### Checklist

- [ ] `pnpm test` passes
- [ ] `pnpm lint` passes
- [ ] `pnpm typecheck` passes (strict)
- [ ] `bash scripts/run-eval.sh` attached when discover-pipeline prompts changed
- [ ] `Closes #N` in the PR body

---

## 6. Code style

### Lint and type check

```bash
pnpm lint        # biome check (format + recommended rules)
pnpm typecheck   # tsc --noEmit, strict + noUncheckedIndexedAccess
```

### Conventions

- TypeScript 5+, ESM only (`"type": "module"`).
- Strict mode with `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`.
- Data shapes via **zod** schemas (not hand-rolled interfaces) whenever the
  value crosses a serialisation boundary.
- I/O is **async-first**; use native `fetch` / `undici`, not wrapper libraries.
- Logging goes through a single module; no ad-hoc `console.log`. The CLI
  uses plain stderr writes for errors.
- Import paths use the bundler resolver — no `.js` extension gymnastics beyond
  what `moduleResolution: "Bundler"` requires.

### Security

- Never commit secrets. Credentials flow through `.env` → typed config module
  only.

Reference: biome + `tsconfig.json` are authoritative until a
`.claude/rules/typescript-style.md` lands in a later PR.

---

## 7. Release cutover smoke checklist

Before tagging a new release, the maintainer runs the following manual smoke
checks. None of these are enforced by CI; they exist to catch regressions that
unit tests cannot — real Notion writes, real Claude Desktop transport,
published-bundle layout. Tick every box on the release PR before merging.

- [ ] All golden-fixture converter tests are green:
      `pnpm test tests/converter` (≥30 fixtures).
- [ ] One real `c2n migrate-tree-pages` run end-to-end against a throwaway
      Notion workspace using a tiny Confluence sample (2–3 pages, at least one
      with a code block and one table) — manually verify the resulting Notion
      tree.
- [ ] One `c2n_convert_page` round-trip via Claude Desktop using the
      forthcoming `examples/mcp/claude-desktop.json` (slice (B) follow-up) —
      confirm the MCP server starts, the tool is discoverable, and the
      converted blocks render in the chat.
- [ ] `pnpm changeset publish --dry-run` reports
      `confluence-to-notion@0.1.0` (or the version under release).
- [ ] `npm publish --dry-run` package contents match the `files` manifest in
      `package.json` (no stray `output/`, `eval_results/`, `samples/`, or
      `tests/` artifacts).

---

## Source of truth

This document is an overview. Detailed rules live in:

- [`.claude/rules/agents.md`](./.claude/rules/agents.md) — subagents + orchestration
- [`.claude/rules/prompts.md`](./.claude/rules/prompts.md) — prompt structure + change policy
- [`.claude/rules/testing.md`](./.claude/rules/testing.md) — test structure + coverage + mocking
