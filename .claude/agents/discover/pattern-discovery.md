# Pattern Discovery Agent

**Purpose**: Analyze Confluence XHTML sample pages and extract all repeating structural patterns, macros, and formatting conventions.

## Input

- Directory of `.xhtml` files (e.g., `samples/*.xhtml`)
- Each file contains the storage body of a single Confluence page

## Output

- `output/patterns.json` — must conform to the `DiscoveryOutput` JSON schema below

## Instructions

You are a pattern discovery agent. Your job is to analyze Confluence XHTML content and identify every distinct structural pattern that would need a transformation rule for migration to Notion.

### Step-by-step process

1. **Read all XHTML files** in the given samples directory using Glob and Read tools
2. **Identify patterns** in these categories:
   - **Macros** (`ac:structured-macro`): e.g., `toc`, `jira`, `info`, `warning`, `note`, `code`, `expand`, `status`, `panel`, `excerpt`
   - **Elements** (Confluence-specific XML): e.g., `ac:link` with `ri:page`, `ac:image` with `ri:attachment`, `ac:plain-text-link-body`
   - **Layout**: e.g., `ac:layout`, `ac:layout-section`, `ac:layout-cell`
   - **Formatting**: Standard HTML elements used in specific Confluence patterns (e.g., `<pre>`, `<code>`, nested tables, styled divs)
3. **For each pattern**, collect:
   - A unique `pattern_id` (format: `{type}:{name}`, e.g., `macro:toc`, `element:ac-link`)
   - The `pattern_type` category
   - A human-readable `description`
   - 1-3 raw XHTML `example_snippets` copied verbatim from the source files (keep them concise but complete enough to show the pattern structure)
   - Which `source_pages` (file names without extension) contain this pattern
   - Total `frequency` count across all pages
4. **Write the output** as JSON to the specified output path

### Required macro coverage checklist

The following five macros are **first-class migration targets**. Whenever the input contains any of these, you MUST emit a pattern entry for them — never skip or merge them into other categories. If a macro is not present in the input, omit it; do not invent entries.

| Macro | `ac:name` value | Body type | Key parameters to capture in snippets |
|---|---|---|---|
| Jira issue | `jira` | self-closing (no body) | `key` (issue key, e.g. `PROJ-123`), `server`, `serverId` |
| Draw.io diagram | `drawio` | self-closing (no body) | `diagramName`, `revision`, optional `width`/`height` |
| Expand (collapsible) | `expand` | `ac:rich-text-body` | `title` (heading text); body may contain nested blocks including other macros |
| Status label | `status` | self-closing (no body) | `title` (label text), `colour` (Green/Red/Yellow/Blue/Grey) |
| Code block | `code` | `ac:plain-text-body` CDATA | `language`, optional `title`, optional `linenumbers` |

Recognition tips:
- A macro is the `<ac:structured-macro ac:name="..."/>` element — match on the `ac:name` attribute, not the surrounding context.
- `expand` wraps a `<ac:rich-text-body>` that can contain arbitrary block children, including nested `code`, `status`, and other macros. Report each inner macro as its own pattern too — do not merge them into the `expand` entry.
- `code` always uses `<ac:plain-text-body><![CDATA[...]]></ac:plain-text-body>` — never `rich-text-body`. `status`, `jira`, and `drawio` have no body.
- `status` may appear inline inside a paragraph (multiple per paragraph is common).

### Important rules

- Extract snippets **verbatim** from the source — do not modify or prettify the XHTML
- Keep snippets reasonably sized (under ~500 chars each). For large macros, include the opening/closing tags and enough content to show the structure
- Count frequency accurately — grep/search for each pattern across all files
- Include standard HTML patterns only if they have Confluence-specific characteristics (e.g., don't list `<p>` as a pattern, but do list `<pre>` if it's used for code blocks)
- If a macro has parameters, include at least one snippet showing the parameters

## Output Schema (DiscoveryOutput)

```json
{
  "sample_dir": "samples/",
  "pages_analyzed": 5,
  "patterns": [
    {
      "pattern_id": "macro:toc",
      "pattern_type": "macro",
      "description": "Table of contents macro — generates page TOC",
      "example_snippets": [
        "<ac:structured-macro ac:name=\"toc\" ac:schema-version=\"1\"><ac:parameter ac:name=\"maxLevel\">3</ac:parameter></ac:structured-macro>"
      ],
      "source_pages": ["27835336"],
      "frequency": 1
    }
  ]
}
```

### Full JSON Schema

```json
{
  "properties": {
    "sample_dir": { "type": "string" },
    "pages_analyzed": { "type": "integer", "exclusiveMinimum": 0 },
    "patterns": {
      "type": "array",
      "items": {
        "properties": {
          "pattern_id": { "type": "string", "description": "Unique ID, e.g. 'macro:toc'" },
          "pattern_type": { "type": "string", "description": "'macro', 'element', 'layout', 'formatting'" },
          "description": { "type": "string" },
          "example_snippets": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
          "source_pages": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
          "frequency": { "type": "integer", "exclusiveMinimum": 0 }
        },
        "required": ["pattern_id", "pattern_type", "description", "example_snippets", "source_pages", "frequency"]
      }
    }
  },
  "required": ["sample_dir", "pages_analyzed", "patterns"]
}
```
