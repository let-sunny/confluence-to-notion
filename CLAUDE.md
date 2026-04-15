# confluence-to-notion

Auto-discovers Confluence → Notion transformation rules using a multi-agent pipeline.
Derived rules are applied by a deterministic converter to migrate wiki pages while preserving structure.

## Tech Stack

- Python 3.11+
- Package manager: uv
- Agents: Claude Code subagents (`.claude/agents/*.md`)
- Confluence client: httpx (direct REST, no atlassian-python-api)
- Notion client: notion-client (official SDK)
- CLI: typer (data prep utilities)
- Config: pydantic-settings + python-dotenv
- Logging: rich
- Testing: pytest, pytest-asyncio
- Lint/format: ruff
- Type check: mypy (strict on src/)

## Architecture Rules

- **CRITICAL**: Agents are Claude Code subagents defined in `.claude/agents/<name>.md` — NOT Python modules
- **CRITICAL**: Agents communicate via files (e.g., `output/patterns.json`), not Python objects
- **CRITICAL**: Never commit secrets. Use `.env` + pydantic-settings
- **CRITICAL**: Do not use `anthropic` SDK to build agents. Claude Code handles LLM calls.
- Orchestration lives in `.claude/commands/` (e.g., `discover.md`)
- `src/` contains only I/O adapters (Confluence, Notion) and the deterministic converter
- Pydantic models in `schemas.py` define the file-based contracts between agents

## Development Process

- **CRITICAL**: TDD — write a failing test first, then implement (for Python code in `src/`)
- **CRITICAL**: Before any agent prompt change, run `scripts/run-eval.sh`
- Conventional commits: `feat|fix|docs|refactor|test|chore`
- Squash merge only

## Additional Rules

Load rules from `.claude/rules/*.md`:
- `python-style.md` — coding style, type hints, async patterns
- `testing.md` — test structure, coverage, mocking
- `agents.md` — subagent definition and orchestration rules
- `prompts.md` — prompt management within agent definitions

## Commands

```bash
# Data preparation (Python CLI)
uv run cli fetch --space <KEY> --limit <N>   # Fetch Confluence pages to samples/
uv run cli fetch --pages <ID1>,<ID2>,...     # Fetch specific pages by ID
uv run cli notion-ping                        # Validate Notion token

# Agent pipeline (Claude Code)
claude -p "/discover samples/"               # Run full discovery pipeline
claude -p "/agent pattern-discovery ..."     # Run individual agent

# Development
uv run pytest                                 # Run tests
uv run ruff check src/ tests/                 # Lint
uv run mypy src/                              # Type check (strict)
```
