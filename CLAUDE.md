# confluence-to-notion

Auto-discovers Confluence → Notion transformation rules using a multi-agent pipeline.
Derived rules are applied by a deterministic converter to migrate wiki pages while preserving structure.

## Tech Stack

- Python 3.11+
- Package manager: uv
- Agents: Claude Code subagents (`.claude/agents/*.md`), each runs as independent `claude -p` session
- Orchestration: bash scripts (`scripts/discover.sh`, `scripts/develop.sh`) — NOT Claude commands
- Confluence client: httpx (direct REST, no atlassian-python-api)
- Notion client: notion-client (official SDK)
- CLI: typer (data prep utilities)
- Config: pydantic-settings + python-dotenv
- Logging: rich
- Testing: pytest, pytest-asyncio
- Lint/format: ruff
- Type check: mypy (strict on src/)

## Language

- **CRITICAL**: This repo is a global-audience portfolio. **Every artifact checked into the repo or pushed to GitHub must be in English.** This covers: commit messages, PR titles/bodies, issue titles/bodies/comments, README, `docs/`, `.claude/agents/*.md`, `.claude/rules/*.md`, `CLAUDE.md` itself, code comments, docstrings, log/error messages, and template files.
- Interactive conversation between the user and Claude may be in Korean; only the repo-bound output is English.
- When editing existing files that contain Korean, rewrite the touched passages in English. Bulk translation of untouched files should only happen when explicitly requested.

## Architecture Rules

- **CRITICAL**: Agents are Claude Code subagents in `.claude/agents/<pipeline>/<name>.md` — NOT Python modules
- **CRITICAL**: Orchestration is a bash script (`scripts/discover.sh`), NOT a Claude command. Flow control must be deterministic and visible in code.
- **CRITICAL**: Each `claude -p` call runs in a clean context. Agents communicate via files only.
- **CRITICAL**: Never commit secrets. Use `.env` + pydantic-settings
- `src/` contains only I/O adapters (Confluence, Notion) and the deterministic converter
- Pydantic models in `schemas.py` define the file-based contracts between agents

## Development Process

- **CRITICAL**: TDD — write a failing test first, then implement (for Python code in `src/`)
- **CRITICAL**: PRs that change **discover-pipeline** prompts (`pattern-discovery`, `rule-proposer`) must use the output of `scripts/run-eval.sh` (schema validation + semantic coverage + LLM-as-judge + baseline diff) as a **merge gate**. The redesign in #84 (LLM-as-judge) / #85 (baseline snapshot) / #86 (fixture deprecation) restored the gate's reliability — see ADR-006. Attach the `eval_results/<timestamp>.json` summary in the PR body (see PR template).
- Conventional commits: `feat|fix|docs|refactor|test|chore`
- Squash merge only
- When opening a PR, link the related issue with a `Closes #N` keyword in the body (auto-closes on merge)

## Additional Rules

Load rules from `.claude/rules/*.md`:
- `python-style.md` — coding style, type hints, async patterns
- `testing.md` — test structure, coverage, mocking
- `agents.md` — subagent definition and orchestration rules
- `prompts.md` — prompt management within agent definitions

## Commands

```bash
# Data preparation (Python CLI)
uv run c2n fetch --space <KEY> --limit <N>   # Fetch Confluence pages to samples/
uv run c2n fetch --pages <ID1>,<ID2>,...     # Fetch specific pages by ID
uv run c2n notion-ping                        # Validate Notion token
uv run c2n validate-output <file> <schema>   # Validate agent output (discovery|proposer)

# Conversion & migration (Python CLI) — convert / migrate / migrate-tree / migrate-tree-pages all require --url.
# When --url is set, artifacts land under output/runs/<slug>/{source.json,status.json,report.md,resolution.json,converted/,...}
uv run c2n finalize output/proposals.json                                                           # proposals.json → rules.json (no run dir)
uv run c2n convert --url <url> --rules output/rules.json --input samples/                           # XHTML → Notion blocks (→ output/runs/<slug>/converted/)
uv run c2n migrate --url <url> --rules output/rules.json --input samples/ --target <page-id>        # Convert + publish pages
uv run c2n migrate-tree --url <url> --tree output/page-tree.json --target <page-id>                 # Create empty Notion hierarchy (→ output/runs/<slug>/resolution.json)
uv run c2n migrate-tree-pages --url <url> --root-id <conf-id> --rules output/rules.json --target <page-id>  # Multi-pass tree migration (resolution.json + rules/table-rules.json + converted/)

# Agent pipeline (bash script orchestration) — steps 1-2 agents, 3-4 deterministic
bash scripts/discover.sh samples/ --url <url>             # Run full pipeline (4 steps)
bash scripts/discover.sh samples/ --url <url> --from 3    # Resume from step 3 (finalize + convert)

# Automated development pipeline — 7 steps: Plan, Implement, Test, Review, Fix, Verify, PR
bash scripts/develop.sh <issue-number>              # Run full pipeline
bash scripts/develop.sh <issue-number> --from 3     # Resume from step 3

# Eval pipeline — merge gate for PRs that change discover-pipeline prompts (schema validation + semantic coverage + LLM-as-judge + baseline diff)
bash scripts/run-eval.sh                      # Results saved to eval_results/<timestamp>.json

# Development
uv run pytest                                 # Run tests
uv run ruff check src/ tests/                 # Lint
uv run mypy src/                              # Type check (strict)
```
