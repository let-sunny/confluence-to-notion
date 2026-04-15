Create a new Claude Code subagent following the rules in `.claude/rules/agents.md`.

## Steps

1. Ask for the agent name (kebab-case) and its purpose (one-line description).
2. Create the agent file at `.claude/agents/$ARGUMENTS.md` with the structure defined in `.claude/rules/prompts.md`:
   - Purpose
   - Input (files on disk, expected format)
   - Output (files on disk, expected format)
   - Instructions (detailed task, constraints, examples)
   - Output schema reference (which Pydantic model the output must match)
3. If new Pydantic schemas are needed, add them to `src/confluence_to_notion/agents/schemas.py`.
4. Create tests for the new schemas in `tests/unit/test_agent_schemas.py`.
5. Verify: `uv run ruff check` and `uv run mypy src/` pass.
6. Report created files and next steps (adding the step to `scripts/discover.sh`).
