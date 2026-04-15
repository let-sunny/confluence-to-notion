# Agent Rules

Agents are Claude Code subagents, NOT Python modules.

## Definition

- Each agent is a markdown file at `.claude/agents/<name>.md`
- The agent file contains: purpose, instructions, expected input/output, and the prompt
- Agents use Claude Code tools (Read, Write, Bash, Grep, Glob) to do their work
- Agents do NOT call the Anthropic API directly — Claude Code handles the LLM

## Communication

- Agents communicate via files, not function calls or Python objects
- Input: files on disk (e.g., `samples/*.xhtml`, `output/patterns.json`)
- Output: files on disk (e.g., `output/patterns.json`, `output/rules.json`)
- File formats follow JSON schemas defined by Pydantic models in `src/**/schemas.py`
- The Pydantic models are the contract — agents must produce valid JSON matching the schema

## Orchestration

- Pipeline orchestration lives in `.claude/commands/discover.md`
- The command spawns subagents sequentially, each reading the previous agent's output
- Can be run interactively (`/discover`) or automated (`claude -p "/discover samples/"`)

## Execution modes

| Mode | Command | Use case |
|---|---|---|
| Interactive | `/discover samples/` | Development, debugging |
| Automated | `claude -p "/discover samples/"` | Scripts, CI |
| Scheduled | Routines | Recurring runs |

## Naming

- Agent files: `pattern-discovery.md`, `rule-proposer.md`, etc. (kebab-case)
- Output files: `patterns.json`, `proposals.json`, etc.
