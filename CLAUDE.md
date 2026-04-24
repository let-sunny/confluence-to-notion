# confluence-to-notion

Auto-discovers Confluence → Notion transformation rules using a multi-agent pipeline.
Derived rules are applied by a deterministic converter to migrate wiki pages while preserving structure.

> **Port in progress (#129).** The repo is being rewritten from Python to
> TypeScript across 5 PRs. PR 1/5 deletes the Python runtime and lands a
> minimal TS scaffold; subcommands, the converter, and MCP server are filled
> in across PRs 2–5. See
> [`.claude/docs/ADR-00N-port-to-typescript.md`](.claude/docs/ADR-00N-port-to-typescript.md).

## Tech Stack

- Node 20 LTS (see `.nvmrc`)
- Package manager: pnpm
- Language: TypeScript 5 (strict + `noUncheckedIndexedAccess`), ESM (`"type": "module"`)
- Agents: Claude Code subagents (`.claude/agents/*.md`), each runs as an independent `claude -p` session
- Orchestration: bash scripts (`scripts/discover.sh`, `scripts/develop.sh`) — NOT Claude commands
- CLI: commander
- Schema validation: zod (lands in PR 2)
- XHTML parser: parse5 in XML mode (lands in PR 2)
- HTTP: undici / global `fetch` (lands in PR 3)
- Notion SDK: `@notionhq/client` (lands in PR 3)
- MCP SDK: `@modelcontextprotocol/sdk` (lands in PR 3)
- Anthropic SDK: `@anthropic-ai/sdk` (lands in PR 3 for eval `--llm-judge`)
- Bundler: tsup
- Test runner: vitest (+ `@vitest/coverage-v8`)
- Lint + format: biome
- Release: changesets

## Language

- **CRITICAL**: This repo is a global-audience portfolio. **Every artifact checked into the repo or pushed to GitHub must be in English.** This covers: commit messages, PR titles/bodies, issue titles/bodies/comments, README, `docs/`, `.claude/agents/*.md`, `.claude/rules/*.md`, `CLAUDE.md` itself, code comments, docstrings, log/error messages, and template files.
- Interactive conversation between the user and Claude may be in Korean; only the repo-bound output is English.
- When editing existing files that contain Korean, rewrite the touched passages in English. Bulk translation of untouched files should only happen when explicitly requested.

## Architecture Rules

- **CRITICAL**: Agents are Claude Code subagents in `.claude/agents/<pipeline>/<name>.md` — NOT TypeScript modules
- **CRITICAL**: Orchestration is a bash script (`scripts/discover.sh`), NOT a Claude command. Flow control must be deterministic and visible in code.
- **CRITICAL**: Each `claude -p` call runs in a clean context. Agents communicate via files only.
- **CRITICAL**: Never commit secrets. Use `.env` loaded via a typed config module.
- `src/` contains only I/O adapters (Confluence, Notion) and the deterministic converter
- zod schemas define the file-based contracts between agents (land in PR 2)

## Development Process

- **CRITICAL**: TDD — write a failing test first, then implement (for TypeScript code in `src/`)
- **CRITICAL**: PRs that change **discover-pipeline** prompts (`pattern-discovery`, `rule-proposer`) must use the output of `scripts/run-eval.sh` (schema validation + semantic coverage + LLM-as-judge + baseline diff) as a **merge gate**. The redesign in #84 (LLM-as-judge) / #85 (baseline snapshot) / #86 (fixture deprecation) restored the gate's reliability — see ADR-006. Attach the `eval_results/<timestamp>.json` summary in the PR body (see PR template).
- Conventional commits: `feat|fix|docs|refactor|test|chore`
- Squash merge only
- When opening a PR, link the related issue with a `Closes #N` keyword in the body (auto-closes on merge)

## Additional Rules

Load rules from `.claude/rules/*.md`:

- `testing.md` — test structure, coverage, mocking
- `agents.md` — subagent definition and orchestration rules
- `prompts.md` — prompt management within agent definitions

> `typescript-style.md` is authored in a later PR once the TS codebase has
> enough surface area to pin conventions against. Until then, biome +
> `tsconfig.json` strict mode are the enforced style.

## Commands

```bash
# Data preparation, conversion, migration (TypeScript CLI) — subcommands land in PR 4 of #129
pnpm exec c2n --version
pnpm exec c2n --help
# Planned subcommands (frozen in ADR-00M): fetch, fetch-tree, notion-ping, validate-output,
# finalize, convert, migrate, migrate-tree, migrate-tree-pages

# Agent pipeline (bash script orchestration) — retargeted to `pnpm exec c2n` in PR 4
bash scripts/discover.sh samples/ --url <url>             # Run full pipeline (4 steps)
bash scripts/discover.sh samples/ --url <url> --from 3    # Resume from step 3

# Automated development pipeline — 7 steps: Plan, Implement, Test, Review, Fix, Verify, PR
bash scripts/develop.sh <issue-number>              # Run full pipeline
bash scripts/develop.sh <issue-number> --from 3     # Resume from step 3

# Eval pipeline — merge gate for PRs that change discover-pipeline prompts
bash scripts/run-eval.sh                      # Results saved to eval_results/<timestamp>.json

# Development
pnpm install                                  # Install deps
pnpm test                                     # vitest run
pnpm lint                                     # biome check
pnpm typecheck                                # tsc --noEmit
pnpm build                                    # tsup → dist/cli.js + dist/mcp.js
```
