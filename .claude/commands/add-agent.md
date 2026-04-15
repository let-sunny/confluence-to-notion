Create a new agent module following the rules in `.claude/rules/agents.md`.

## Steps

1. Ask for the agent name and its purpose (one-line description).
2. Create the module at `src/confluence_to_notion/agents/$ARGUMENTS/`:
   - `__init__.py` — exports `run`
   - `agent.py` — scaffold with `async def run(input: InputModel) -> OutputModel`
   - `schemas.py` — define `InputModel` and `OutputModel` (Pydantic v2)
   - `prompts/system.md` — with YAML front-matter per `.claude/rules/prompts.md`
   - `prompts/user.md` — with YAML front-matter per `.claude/rules/prompts.md`
3. Create test file at `tests/unit/test_$ARGUMENTS.py` with a failing test skeleton.
4. Create fixtures directory at `tests/fixtures/$ARGUMENTS/`.
5. Verify: `uv run ruff check` and `uv run mypy src/` pass.
6. Report created files.
