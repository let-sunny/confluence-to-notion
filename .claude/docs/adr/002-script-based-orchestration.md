# ADR-002: Script-Based Orchestration with Claude Code Subagents

**Status**: Accepted
**Date**: 2026-04-16

## Context

ADR-001 established a multi-agent pipeline for rule discovery. The next question: how do agents run and who controls the flow?

Three options were considered:

1. **Python orchestration** — Python code calls `anthropic` SDK, passes data between agents as Pydantic objects
2. **Delegated orchestration** — A single Claude session (via `.claude/commands/discover.md`) spawns subagents internally, managing flow in its context window
3. **Script-based orchestration** — A bash script calls `claude -p` sequentially, each agent runs as an independent session

Our pipeline is linear: Discovery → Proposer → Critic → Arbitrator. No dynamic branching. Each step reads the previous step's output file and writes its own.

## Decision

Use **script-based orchestration** (`scripts/discover.sh`). Each agent is a Claude Code subagent defined in `.claude/agents/<name>.md`, invoked via `claude -p` with a clean context per step. The bash script controls the flow.

```
scripts/discover.sh samples/
  ├─ claude -p (pattern-discovery)  → output/patterns.json
  ├─ claude -p (rule-proposer)      → output/proposals.json
  ├─ claude -p (rule-critic)        → output/critiques.json
  └─ claude -p (rule-arbitrator)    → output/rules.json
```

## Consequences

### Positive

- **Deterministic flow**: Orchestration is visible bash code, not LLM judgment. Read the script to see the entire pipeline.
- **Clean context**: Each agent starts fresh. No accumulated noise or context window pressure.
- **Step-level retry**: Step 3 fails → `--from 3` reruns only step 3. No need to rerun the full pipeline.
- **Debuggable**: Intermediate files (`output/*.json`) are always on disk. Inspect any step's input/output.
- **Cheap to change**: Adding a step, reordering, or skipping one is a one-line script edit.
- **Same agents, multiple modes**: Agent `.md` files work identically whether called from a script, interactively, or via Routines.
- **No Python orchestration code**: No need for `anthropic` SDK, retry logic, or agent-to-agent plumbing in Python.

### Negative

- **No dynamic routing**: The script can't decide at runtime "this needs more critique, loop back to the Critic." If needed, the script would need conditional logic.
- **Startup cost per step**: Each `claude -p` session has cold-start overhead (loading context, tools). For a 4-step pipeline this is acceptable.
- **No shared context**: If step 3 needs context from step 1 beyond what's in the output file, it must re-derive it. This forces good file contracts but can be limiting.

### Mitigations

- If dynamic routing is needed later, the bash script can add conditionals (`if jq '.has_conflicts' output/critiques.json; then ...`).
- Cold-start cost is amortized against the LLM reasoning time (seconds of startup vs minutes of agent work).
- File contracts are enforced by Pydantic schemas in `src/**/schemas.py` — if an agent's output is insufficient, the schema is where to fix it.

## Alternatives Considered

### Python orchestration with `anthropic` SDK

Each agent is a Python module calling `messages.create()`. Orchestration is Python code.

Rejected because:
- Requires maintaining custom orchestration, retry, and error-handling code
- Agent prompts would be inline Python strings or Jinja templates — harder to review and version
- Locks agents to the Anthropic SDK; Claude Code subagents are SDK-agnostic
- Doesn't get clean-context benefits (would need manual context management)

### Delegated orchestration via Claude commands

A `.claude/commands/discover.md` command tells Claude to spawn subagents internally.

Rejected because:
- Flow control depends on LLM judgment — non-deterministic
- All state accumulates in one context window — harder to debug
- Can't retry a single step — must rerun the full pipeline
- Flow changes require prompt engineering, not code edits
- "Where did it go wrong?" is harder to answer than with file-based steps
