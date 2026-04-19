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

## Architecture Rules

- **CRITICAL**: Agents are Claude Code subagents in `.claude/agents/<pipeline>/<name>.md` — NOT Python modules
- **CRITICAL**: Orchestration is a bash script (`scripts/discover.sh`), NOT a Claude command. Flow control must be deterministic and visible in code.
- **CRITICAL**: Each `claude -p` call runs in a clean context. Agents communicate via files only.
- **CRITICAL**: Never commit secrets. Use `.env` + pydantic-settings
- `src/` contains only I/O adapters (Confluence, Notion) and the deterministic converter
- Pydantic models in `schemas.py` define the file-based contracts between agents

## Development Process

- **CRITICAL**: TDD — write a failing test first, then implement (for Python code in `src/`)
- **CRITICAL**: **discover-pipeline** 프롬프트(`pattern-discovery`, `rule-proposer`) 변경 PR은 `scripts/run-eval.sh` 결과(schema validation + semantic coverage + LLM-as-judge + baseline diff)를 **머지 게이트**로 사용한다. #84 (LLM-as-judge) / #85 (baseline snapshot) / #86 (fixture deprecate) 재설계로 eval 이 머지 게이트 신뢰성을 회복했음 — ADR-006 참조. PR 본문에 `eval_results/<timestamp>.json` 요약을 첨부한다(PR 템플릿 참조).
- Conventional commits: `feat|fix|docs|refactor|test|chore`
- Squash merge only
- PR 생성 시 관련 이슈를 `Closes #N` 키워드로 본문에 연결 (머지 시 자동 클로즈)

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

# Conversion & migration (Python CLI) — convert / migrate-tree / migrate-tree-pages require --url; migrate accepts --url optionally.
# When --url is set, artifacts land under output/runs/<slug>/{source.json,status.json,report.md,resolution.json,converted/,...}
uv run cli finalize output/proposals.json                                                           # proposals.json → rules.json (no run dir)
uv run cli convert --url <url> --rules output/rules.json --input samples/                           # XHTML → Notion blocks (→ output/runs/<slug>/converted/)
uv run cli migrate --url <url> --rules output/rules.json --input samples/ --target <page-id>        # Convert + publish pages (--url optional; without it, no run-dir artifacts)
uv run cli migrate-tree --url <url> --tree output/page-tree.json --target <page-id>                 # Create empty Notion hierarchy (→ output/runs/<slug>/resolution.json)
uv run cli migrate-tree-pages --url <url> --root-id <conf-id> --rules output/rules.json --target <page-id>  # Multi-pass tree migration (resolution.json + rules/table-rules.json + converted/)

# Agent pipeline (bash script orchestration) — steps 1-2 agents, 3-4 deterministic
bash scripts/discover.sh samples/ --url <url>             # Run full pipeline (4 steps)
bash scripts/discover.sh samples/ --url <url> --from 3    # Resume from step 3 (finalize + convert)

# Automated development pipeline — 7 steps: Plan, Implement, Test, Review, Fix, Verify, PR
bash scripts/develop.sh <issue-number>              # Run full pipeline
bash scripts/develop.sh <issue-number> --from 3     # Resume from step 3

# Eval pipeline — discover-pipeline 프롬프트 변경 PR 의 머지 게이트 (schema validation + semantic coverage + LLM-as-judge + baseline diff)
bash scripts/run-eval.sh                      # Results saved to eval_results/<timestamp>.json

# Development
uv run pytest                                 # Run tests
uv run ruff check src/ tests/                 # Lint
uv run mypy src/                              # Type check (strict)
```
