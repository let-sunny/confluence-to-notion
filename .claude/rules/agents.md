# Agent Module Rules

- Each agent is a module under `src/confluence_to_notion/agents/<name>/`
- Structure per agent module:
  - `__init__.py` — exports `run` function
  - `agent.py` — orchestration logic, uses Claude API
  - `prompts/` — directory containing `.md` prompt templates (Jinja2 syntax)
  - `schemas.py` — Input/Output Pydantic models
- Prompt rendering utility lives in `src/confluence_to_notion/prompts.py`
- Never inline multi-line prompts in Python strings
- Each agent has a single public entry point: `async def run(input: InputModel) -> OutputModel`
- Agents communicate via typed Pydantic models, never raw dicts
