# confluence-to-notion

Auto-discovers Confluence → Notion transformation rules using a multi-agent pipeline.
Derived rules are applied by a deterministic converter to migrate wiki pages while preserving structure.

## Tech Stack

- Python 3.11+
- Package manager: uv
- Agents: Claude Code subagents (`.claude/agents/*.md`), each runs as independent `claude -p` session
- Orchestration: bash scripts (`scripts/discover.sh`) — NOT Claude commands
- Confluence client: httpx (direct REST, no atlassian-python-api)
- Notion client: notion-client (official SDK)
- CLI: typer (data prep utilities)
- Config: pydantic-settings + python-dotenv
- Logging: rich
- Testing: pytest, pytest-asyncio
- Lint/format: ruff
- Type check: mypy (strict on src/)

## Architecture Rules

- **CRITICAL**: Agents are Claude Code subagents in `.claude/agents/<name>.md` — NOT Python modules
- **CRITICAL**: Orchestration is a bash script (`scripts/discover.sh`), NOT a Claude command. Flow control must be deterministic and visible in code.
- **CRITICAL**: Each `claude -p` call runs in a clean context. Agents communicate via files only.
- **CRITICAL**: Never commit secrets. Use `.env` + pydantic-settings
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
uv run cli validate-output <file> <schema>   # Validate agent output (discovery|proposer)

# Conversion (Python CLI)
uv run cli finalize output/proposals.json     # proposals.json → rules.json
uv run cli convert --rules output/rules.json --input samples/  # XHTML → Notion blocks

# Agent pipeline (bash script orchestration) — steps 1-2 agents, 3-4 deterministic
bash scripts/discover.sh samples/             # Run full pipeline (4 steps)
bash scripts/discover.sh samples/ --from 3    # Resume from step 3 (finalize + convert)

# Development
uv run pytest                                 # Run tests
uv run ruff check src/ tests/                 # Lint
uv run mypy src/                              # Type check (strict)
```
