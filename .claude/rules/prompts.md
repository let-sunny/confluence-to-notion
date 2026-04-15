# Prompt Management Rules

Agent prompts are embedded in `.claude/agents/<name>.md` files.

## Structure of an agent file

Each agent `.md` file should contain:
1. **Purpose**: One-line description of what the agent does
2. **Input**: What files/data the agent reads and their expected format
3. **Output**: What files/data the agent produces and their expected format
4. **Instructions**: Detailed prompt with the agent's task, constraints, and examples
5. **Output schema reference**: Which Pydantic model the output must match

## Rules

- All prompt text lives in the agent `.md` file — never in Python source code
- When an agent prompt is changed, run `scripts/run-eval.sh` to verify quality
- Prompts should reference the JSON schema from `src/**/schemas.py` for output format
- Include examples of expected input/output in the prompt when possible
- Keep prompts focused: one agent, one responsibility
