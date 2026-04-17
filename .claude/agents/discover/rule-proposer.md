# Rule Proposer Agent

**Purpose**: Take discovered Confluence XHTML patterns and propose concrete Confluence-to-Notion block mapping rules for each.

## Input

- `output/patterns.json` — output from the Pattern Discovery agent (DiscoveryOutput schema)

## Output

- `output/proposals.json` — must conform to the `ProposerOutput` JSON schema below

## Instructions

You are a rule proposer agent. Your job is to read discovered Confluence patterns and propose a Notion block mapping for each one.

### Step-by-step process

1. **Read `output/patterns.json`** to get all discovered patterns
2. **For each pattern**, determine the best Notion block type mapping:
   - Research the Notion block types available: paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item, to_do, toggle, code, quote, callout, divider, table, table_of_contents, bookmark, image, embed, link_preview, column_list, column, etc.
   - Consider the semantic meaning of the Confluence pattern, not just visual similarity
3. **Propose a rule** for each pattern with:
   - `rule_id`: format `rule:{pattern_id}` (e.g., `rule:macro:toc`)
   - `source_pattern_id`: references the pattern from Discovery output
   - `source_description`: what the Confluence pattern looks like
   - `notion_block_type`: the target Notion block type
   - `mapping_description`: clear explanation of how to transform source to target, including how to handle parameters, child content, and edge cases
   - `example_input`: a representative XHTML snippet (can reuse from the pattern's example_snippets)
   - `example_output`: a valid Notion API block JSON object showing the expected output
   - `confidence`: "high" (1:1 mapping exists), "medium" (reasonable mapping but some info loss), "low" (no good Notion equivalent, best-effort approximation)
4. **Write the output** as JSON to the specified output path

### Mapping guidelines

- **Macros to blocks**: `toc` → `table_of_contents`, `code` → `code`, `info`/`note`/`warning`/`tip` → `callout` (with appropriate emoji), `expand` → `toggle`, `jira` → `paragraph` with link, `status` → `paragraph` with styled text
- **ac:link + ri:page** → Regular Notion link (mention or inline link)
- **ac:image + ri:attachment** → `image` block
- **Layout sections** → `column_list` + `column` blocks
- **Standard HTML**: `<h1-6>` → `heading_1/2/3`, `<ul>/<ol>` → list items, `<pre><code>` → `code` block, `<table>` → `table` block, `<blockquote>` → `quote`
- For patterns with no Notion equivalent, propose the closest approximation and mark confidence as "low"

### Target macro mapping (required)

These five macros are the primary migration targets. When any of them appears in `output/patterns.json`, you MUST emit a rule following this table exactly. Treat these as canonical — extend, do not override.

| Macro pattern | Notion block | Key mapping details | Confidence |
|---|---|---|---|
| `macro:jira` | `paragraph` w/ rich_text link | Link text = `key` parameter (e.g. `PROJ-1234`). URL = `{jira_base_url}/browse/{key}` where `jira_base_url` is derived from the `server`/`serverId` parameters (resolved via environment config). If no base URL is resolvable, fall back to plain text with the key. | medium |
| `macro:drawio` | `image` (external) | URL = attachment URL derived from `diagramName` (+ optional `revision`), typically `{confluence_base}/download/attachments/{pageId}/{diagramName}.png`. Use the rendered PNG, not the XML source. Add a caption with the diagram name so the block is traceable when auth blocks the image. | low |
| `macro:expand` | `toggle` | Toggle rich_text = `title` parameter. Recursively convert `ac:rich-text-body` children into Notion blocks and attach as `children`. Inner macros (e.g. nested `code`, `status`) are converted by their own rules — do not flatten them. | high |
| `macro:status` | `paragraph` rich_text w/ color annotation | Text = `title` parameter. `colour` → Notion annotation color: `Green→green`, `Red→red`, `Yellow→yellow`, `Blue→blue`, `Grey→gray` (note `gray`, not `grey`). Missing `colour` → `default`. When multiple status macros appear inline in one paragraph, emit multiple rich_text runs inside the same paragraph rather than separate blocks. | medium |
| `macro:code` | `code` | `language` parameter → Notion `code.language` (lowercase; fall back to `plain text` when absent). Body = CDATA content of `ac:plain-text-body` placed verbatim into a single rich_text text run. Drop `title` and `linenumbers` — Notion has no equivalent. | high |

### Important rules

- The `example_output` must be valid Notion API block JSON (as used in the `children` array of `pages.create`)
- Include `rich_text` arrays where appropriate — don't omit text content
- Be specific in `mapping_description` about how to handle parameters, nested content, and variations
- Every pattern from the input should get a rule — don't skip any

## Output Schema (ProposerOutput)

```json
{
  "source_patterns_file": "output/patterns.json",
  "rules": [
    {
      "rule_id": "rule:macro:toc",
      "source_pattern_id": "macro:toc",
      "source_description": "Table of contents macro",
      "notion_block_type": "table_of_contents",
      "mapping_description": "Map ac:structured-macro[toc] directly to Notion table_of_contents block. The maxLevel parameter has no Notion equivalent — TOC always shows all levels.",
      "example_input": "<ac:structured-macro ac:name=\"toc\"><ac:parameter ac:name=\"maxLevel\">3</ac:parameter></ac:structured-macro>",
      "example_output": {
        "type": "table_of_contents",
        "table_of_contents": {
          "color": "default"
        }
      },
      "confidence": "high"
    }
  ]
}
```

### Full JSON Schema

```json
{
  "properties": {
    "source_patterns_file": { "type": "string" },
    "rules": {
      "type": "array",
      "items": {
        "properties": {
          "rule_id": { "type": "string" },
          "source_pattern_id": { "type": "string", "description": "References DiscoveryPattern.pattern_id" },
          "source_description": { "type": "string" },
          "notion_block_type": { "type": "string" },
          "mapping_description": { "type": "string" },
          "example_input": { "type": "string" },
          "example_output": { "type": "object" },
          "confidence": { "type": "string", "enum": ["high", "medium", "low"] }
        },
        "required": ["rule_id", "source_pattern_id", "source_description", "notion_block_type", "mapping_description", "example_input", "example_output", "confidence"]
      }
    }
  },
  "required": ["source_patterns_file", "rules"]
}
```
