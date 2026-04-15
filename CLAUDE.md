# confluence-to-notion

Auto-discovers Confluence → Notion transformation rules using a multi-agent pipeline.
Derived rules are applied by a deterministic converter to migrate wiki pages while preserving structure.

## Tech Stack

- Python 3.11+
- Package manager: uv
- LLM: anthropic (Claude API)
- Confluence client: httpx (direct REST, no atlassian-python-api)
- Notion client: notion-client (official SDK)
- CLI: typer
- Config: pydantic-settings + python-dotenv
- Logging: rich
- Testing: pytest, pytest-asyncio
- Lint/format: ruff
- Type check: mypy (strict on src/)

## Architecture Rules

- **CRITICAL**: Agent prompts live in `src/**/prompts/*.md`, never inline in Python strings
- **CRITICAL**: All LLM-facing schemas are Pydantic models in `schemas.py`
- **CRITICAL**: Never commit secrets. Use `.env` + pydantic-settings
- Agents communicate via typed Pydantic models, not raw dicts
- Each agent exposes a single public entry: `run(input: In) -> Out`

## Development Process

- **CRITICAL**: TDD — write a failing test first, then implement
- **CRITICAL**: Before any prompt change, run `scripts/run-eval.sh`
- Conventional commits: `feat|fix|docs|refactor|test|chore`
- Squash merge only

## Additional Rules

Load rules from `.claude/rules/*.md`:
- `python-style.md` — coding style, type hints, async patterns
- `testing.md` — test structure, coverage, mocking
- `agents.md` — agent module structure
- `prompts.md` — prompt file format and management

## Commands

```bash
# CLI
uv run cli fetch --space <KEY> --limit <N>   # Fetch Confluence pages to samples/
uv run cli discover                           # Run pattern discovery (Day 2)
uv run cli migrate                            # Run migration (Day 3)
uv run cli notion-ping                        # Validate Notion token

# Development
uv run pytest                                 # Run tests
uv run pytest tests/integration/ -m integration  # Integration tests only
uv run ruff check src/ tests/                 # Lint
uv run ruff format src/ tests/                # Format
uv run mypy src/                              # Type check (strict)
```
