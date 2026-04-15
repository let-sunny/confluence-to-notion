# Prompt Management Rules

- Prompts are markdown files (`.md`), loaded at runtime
- Variables use Jinja2 syntax: `{{ variable_name }}`
- Every prompt file must have a YAML front-matter block:
  ```yaml
  ---
  agent: <agent-name>
  purpose: <one-line description>
  expected_output_schema: <PydanticModelName>
  ---
  ```
- Prompt changes require a corresponding eval run (`scripts/run-eval.sh`)
- Prompt files live in `src/confluence_to_notion/agents/<name>/prompts/`
- System prompts and user prompts are separate files
- Never hardcode prompt text in Python source files
