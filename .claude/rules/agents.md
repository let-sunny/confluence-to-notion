# Agent Rules

Agents are Claude Code subagents, each running as an independent `claude -p` session.
Orchestration is a bash script, NOT a Claude command.

## Definition

- Each agent is a markdown file at `.claude/agents/<pipeline>/<name>.md`
- The agent file contains: purpose, instructions, expected input/output format
- Agents use Claude Code tools (Read, Write, Bash, Grep, Glob) to do their work
- Each `claude -p` call starts with a **clean context** — no shared state between agents

## Communication

- Agents communicate via files on disk — NEVER via shared context or memory
- Input: files on disk (e.g., `samples/*.xhtml`, `output/patterns.json`)
- Output: files on disk (e.g., `output/patterns.json`, `output/rules.json`)
- File formats follow JSON schemas defined by Pydantic models in `src/**/schemas.py`
- The Pydantic models are the contract — agents must produce valid JSON matching the schema

## Orchestration

- Pipeline orchestration is in bash scripts (`scripts/discover.sh`, `scripts/develop.sh`)
- Each script calls `claude -p` sequentially, one step per agent
- Flow control is deterministic and visible in code — not LLM judgment
- Failed steps can be rerun individually with `--from N`

## Directory Structure

```
.claude/agents/
├── discover/              # Confluence → Notion migration pipeline
│   ├── pattern-discovery.md
│   └── rule-proposer.md
└── develop/               # Automated development pipeline
    ├── dev-planner.md
    ├── dev-implementer.md
    ├── dev-reviewer.md
    └── dev-fixer.md
```

## Naming

- Pipeline directories: kebab-case (`discover/`, `develop/`)
- Agent files: kebab-case (`pattern-discovery.md`, `dev-planner.md`)
- Output files: `patterns.json`, `proposals.json`, `plan.json`, `review.json`
- Scripts: `scripts/discover.sh`, `scripts/develop.sh`
