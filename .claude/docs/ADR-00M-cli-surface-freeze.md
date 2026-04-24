# ADR-00M: CLI Surface Freeze

**Status**: Accepted (2026-04-24)
**Related**: [ADR-00N — Port to TypeScript](./ADR-00N-port-to-typescript.md)

## Decision

This document is the **authoritative, frozen inventory of the `c2n` CLI
surface** as of commit `c958021` (immediately before the Python runtime is
deleted in PR 1/5 of #129). PR 4 of the TS port will reimplement every
subcommand + flag listed here verbatim. The test suite added in PR 4 will
diff `c2n --help` and each `c2n <sub> --help` output against this file; drift
fails CI.

Captured from `src/confluence_to_notion/cli.py` and
`src/confluence_to_notion/config.py`. Env-var defaults come from `Settings`
(pydantic-settings).

## Environment variables

| Name | Default | Required | Notes |
|---|---|---|---|
| `CONFLUENCE_BASE_URL` | `https://cwiki.apache.org/confluence` | Always (has default) | Must start with `http://` or `https://`. |
| `CONFLUENCE_EMAIL` | _unset_ | Private Cloud only | Paired with `CONFLUENCE_API_TOKEN` for basic auth. |
| `CONFLUENCE_API_TOKEN` | _unset_ | Private Cloud only | See above. |
| `CONFLUENCE_API_PATH` | `/rest/api` | Always (has default) | Must start with `/`. Override for self-hosted Confluence. |
| `NOTION_API_TOKEN` | _unset_ | `notion-ping` + every `migrate*` command | Must start with `ntn_` or `secret_`. |
| `NOTION_ROOT_PAGE_ID` | _unset_ | Fallback for `--target` / `--to` | Every `migrate*` command falls back to this when the flag is omitted. |
| `ANTHROPIC_API_KEY` | _unset_ | Only `c2n eval --llm-judge` (or `scripts/run-eval.sh --llm-judge`) | Never required by the CLI itself. |

## Subcommands

### `c2n fetch`

> Fetch Confluence pages and save XHTML to disk.

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--space` | TEXT | _none_ | — | One of `--space`/`--pages` required | Confluence space key; paginates listing with `--limit`. |
| `--pages` | TEXT | _none_ | — | One of `--space`/`--pages` required | Comma-separated page IDs. |
| `--limit` | INTEGER | `25` | — | No | Max pages when using `--space`. |
| `--out-dir` | PATH | `samples` | — | No | Output directory for XHTML. |
| `--url` | TEXT | _none_ | — | No | Confluence source URL; when set, writes artifacts to `output/runs/<slug>/` and overrides `--out-dir`. |

### `c2n fetch-tree`

> Fetch the Confluence page tree starting from a root page.

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--root-id` | TEXT | _none_ | — | Yes | Confluence root page ID. |
| `--output` | PATH | `output/page-tree.json` | — | No | Output JSON path; ignored when `--url` is set. |
| `--url` | TEXT | _none_ | — | No | When set, writes `page-tree.json` under `output/runs/<slug>/`. |

### `c2n notion-ping`

> Validate Notion API token by fetching bot user info.

No flags. Requires `NOTION_API_TOKEN` and `NOTION_ROOT_PAGE_ID`.

### `c2n discover`

> Reminder shim: prints the correct `bash scripts/discover.sh` invocation and exits 1. Not a real pipeline entry point.

No flags.

### `c2n eval`

> Semantic coverage over sample XHTML, optional LLM-as-judge, and baseline diff vs the latest prior snapshot under `eval_results/`.

| Arg / Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `OUTPUT_DIR` (positional) | PATH | `output` | — | No | Directory containing `patterns.json` and `proposals.json` (validated before coverage). |
| `EVAL_RESULTS_DIR` (positional) | PATH | `eval_results` | — | No | Directory where `eval_results/<timestamp>.json` snapshots are written and read for baseline diff. |
| `SAMPLES_DIR` (positional) | PATH | _none_ | — | No | Sample XHTML directory; **required** when `--llm-judge` is set (semantic coverage also uses it when provided). |
| `--llm-judge` | FLAG | `false` | — | No | When set, runs the Anthropic judge pass if `ANTHROPIC_API_KEY` is present; otherwise judge output stays null. |
| `--fail-on-regression` | FLAG | `false` | — | No | Exit non-zero when baseline comparison marks a regression. |

### `c2n validate-output`

> Validate an agent output file against its Pydantic/zod schema.

| Arg | Type | Default | Required | Semantics |
|---|---|---|---|---|
| `FILE` (positional) | PATH | _none_ | Yes | JSON file to validate. |
| `SCHEMA` (positional) | TEXT | _none_ | Yes | Schema name: `discovery`, `proposer`, or `scout`. |

### `c2n finalize`

> Convert `proposals.json` → `rules.json` by promoting every proposed rule with `enabled=true`.

| Arg / Flag | Type | Default | Required | Semantics |
|---|---|---|---|---|
| `PROPOSALS_FILE` (positional) | PATH | `output/proposals.json` | No (has default) | Path to proposals.json. |
| `--out` | PATH | `output/rules.json` | No | Output rules.json path. |

### `c2n convert`

> Convert XHTML pages to Notion blocks using finalized rules.

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--rules` | PATH | `output/rules.json` | — | No | Path to rules.json. |
| `--input` | PATH | `samples` | — | No | Directory of XHTML files. |
| `--url` | TEXT | _none_ | — | **Yes** | Confluence source URL; converted JSON lands under `output/runs/<slug>/converted/`. |

### `c2n migrate`

> Convert XHTML pages and publish them to Notion. Two shapes — URL-dispatch (preferred) and legacy batch.

**Preferred form** (positional URL):

| Arg / Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `CONFLUENCE_URL` (positional) | TEXT | _none_ | — | No (but required for the preferred form; `--url` required otherwise, see legacy table) | When set, `c2n` auto-dispatches to a single-page or tree/space fan-out flow. |
| `--to` | TEXT | _none_ | `NOTION_ROOT_PAGE_ID` | No | Notion parent (page URL or page id). URLs are normalized: last path segment with hyphens stripped. |
| `--name` | TEXT | _none_ | — | No | Override the run slug under `output/runs/`. |
| `--rediscover` | FLAG | `false` | — | No | Force re-running `scripts/discover.sh` even when `output/rules.json` exists. |
| `--dry-run` | FLAG | `false` | — | No | Fetch + convert only; skip every Notion write. |

**Legacy form** (no positional URL):

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--rules` | PATH | `output/rules.json` | — | No | Path to rules.json. |
| `--input` | PATH | `samples` | — | No | Directory of XHTML files. |
| `--target` | TEXT | _none_ | `NOTION_ROOT_PAGE_ID` | No | Notion parent page ID. |
| `--url` | TEXT | _none_ | — | **Yes** (in legacy form) | Confluence source URL; required when the positional URL is omitted. |

### `c2n migrate-tree`

> Create an empty Notion page hierarchy mirroring a Confluence tree.

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--tree` | PATH | `output/page-tree.json` | — | No | Path to page-tree.json produced by `fetch-tree`. |
| `--target` | TEXT | _none_ | `NOTION_ROOT_PAGE_ID` | No | Notion parent page ID. |
| `--url` | TEXT | _none_ | — | **Yes** | Confluence source URL; `resolution.json` lands under `output/runs/<slug>/`. |

### `c2n migrate-tree-pages`

> Multi-pass migration: tree → table-rule discovery → body upload.

| Flag | Type | Default | Env fallback | Required | Semantics |
|---|---|---|---|---|---|
| `--root-id` | TEXT | _none_ | — | **Yes** | Confluence root page ID. |
| `--target` | TEXT | _none_ | `NOTION_ROOT_PAGE_ID` | No | Notion parent page ID. |
| `--rules` | PATH | `output/rules.json` | — | No | Path to rules.json. |
| `--url` | TEXT | _none_ | — | **Yes** | Confluence source URL; every artifact (source / status / report / resolution / rules / converted) lands under `output/runs/<slug>/`. |

## Exit codes

- `0` — success.
- `1` — any validation failure, missing required flag, missing file, API error, or user-cancelled prompt. All failures print a Rich-style `[red]...[/red]` message (Python runtime); the TS rewrite must preserve exit-code semantics but may replace Rich markup with plain text. The PR 4 test suite asserts exit codes only, not ANSI output.

## Why

PR 1/5 deletes the Python runtime. Without a written freeze, PR 4 would have to
reverse-engineer the CLI from git history — brittle, easy to drift. Freezing
here means PR 4's acceptance test is mechanical: parse help output, diff
against this file.

## Impact

- PR 4 must implement every flag listed here with the documented type, default, env fallback, required-ness, and one-line semantic. Adding, removing, or renaming a flag requires an ADR amendment.
- Help-text wording is **not** frozen — only flag names and semantics. The TS implementation may reword `--help` output for clarity.
- New subcommands introduced after PR 5 are additive and must get their own ADR entry or amendment here.
