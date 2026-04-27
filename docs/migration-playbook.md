# Migration playbook — c2n + Notion MCP

End-to-end guide for migrating Confluence pages to Notion through any MCP host (OpenClaw, Claude Desktop / Claude Code, Codex, Cursor, custom MCP clients) by composing the **c2n MCP server** with a **separate Notion MCP server**. The c2n server is read-mostly: it fetches Confluence, converts to Notion blocks, and bookkeeps proposals / mappings. Page creation (`create_page`, `append_blocks`) runs through the host's Notion MCP. See [ADR-007](../.claude/docs/ADR.md) for the rationale.

This playbook is vendor-neutral. Host-specific configuration walkthroughs live in each host's own docs; here we cover the bits common to all of them and the c2n side in depth.

## Table of contents

1. [Setup — register both MCP servers](#1-setup--register-both-mcp-servers)
2. [Single-page migration flow](#2-single-page-migration-flow)
3. [Question / answer loop (rule accumulation)](#3-question--answer-loop-rule-accumulation)
4. [Re-run and dedup](#4-re-run-and-dedup)
5. [Tree migration](#5-tree-migration)
6. [Schemas referenced](#6-schemas-referenced)
7. [Failure modes](#7-failure-modes)

---

## 1. Setup — register both MCP servers

The host needs **two MCP servers** registered side by side: `c2n` and `notion`. Both speak stdio.

### 1.1 Generic JSON shape

Every host that supports stdio MCP servers uses the same four fields per entry:

| Field     | Description                                                                          |
| --------- | ------------------------------------------------------------------------------------ |
| `command` | Executable to spawn.                                                                 |
| `args`    | Array of command-line arguments.                                                     |
| `env`     | Extra environment variables (credentials, profile selectors).                         |
| `cwd`     | Working directory. For c2n, point at where `output/runs/` and `output/proposals.json` live. |

Generic JSON form (host-agnostic):

```jsonc
{
  "mcpServers": {
    "c2n": {
      "command": "npx",
      "args": ["-p", "confluence-to-notion@0.1.3", "c2n-mcp"],
      "cwd": "/path/to/c2n-workspace"
    },
    "notion": {
      "command": "npx",
      "args": ["-y", "@notionhq/notion-mcp-server"],
      "env": {
        "NOTION_TOKEN": "secret_..."
      }
    }
  }
}
```

> **Notion MCP package.** The official package is `@notionhq/notion-mcp-server`. Its tool surface (notably `create_page`, `append_blocks`, page search) is what the playbook assumes. Other Notion MCP implementations expose similar primitives; tool names may differ.

> **c2n credentials.** Run `npx -p confluence-to-notion c2n init` once on the host to write `~/.config/c2n/config.json`. After that, the c2n entry can stay credential-free — `c2n_fetch_page` reads Confluence creds from the profile store. Override with `C2N_PROFILE` in `env` if you have multiple profiles. Direct env vars (`CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`) still work as a fallback.

> **Why `cwd` matters for c2n.** Tools that read or write run artifacts (`c2n_list_runs`, `c2n_get_run_report`, `c2n_list_unresolved`, `c2n_record_migration`, `c2n_propose_resolution`, `c2n_finalize_proposals`) default to `<cwd>/output/...`. Either set `cwd` to the workspace where those files live, or pass the per-call overrides (`rootDir`, `proposalsPath`, `rulesOutPath`).

### 1.2 Host-specific commands (brief)

The shape above is universal. Each host has its own way to load it:

- **OpenClaw** — `openclaw mcp set c2n '{"command":"npx","args":["-p","confluence-to-notion","c2n-mcp"]}'`. Repeat for `notion`. The full `mcp.servers` registry is documented at `openclaw/openclaw → docs/cli/mcp.md`.
- **Claude Desktop** — edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`); paste both entries under `mcpServers`. Restart the app.
- **Claude Code (CLI)** — `claude mcp add c2n -- npx -p confluence-to-notion c2n-mcp` plus `claude mcp add notion -- npx -y @notionhq/notion-mcp-server -e NOTION_TOKEN=...`. Listing/removing is `claude mcp list` / `claude mcp remove`.
- **Codex / Cursor / custom clients** — by analogy: each one accepts the same `command` / `args` / `env` / `cwd` triple, either through a settings UI or a config file under the editor's profile dir. Consult the host's MCP docs for the exact field names.

Anything beyond "register the server" — channel routing, approval UI, secrets storage — belongs in the host's own documentation, not here.

---

## 2. Single-page migration flow

The minimal end-to-end sequence for one page. Each numbered step is a single tool call.

### 2.1 Fetch the Confluence page

```jsonc
// → c2n MCP
{
  "name": "c2n_fetch_page",
  "arguments": { "pageIdOrUrl": "https://example.atlassian.net/wiki/spaces/ENG/pages/123456789/Onboarding" }
}
```

Returns:

```jsonc
{
  "pageId": "123456789",
  "title": "Onboarding",
  "spaceKey": "ENG",
  "version": 12,
  "body": { "storage": { "value": "<p>…XHTML…</p>", "representation": "storage" } }
}
```

Accepts either a numeric page ID or a `/spaces/<KEY>/pages/<ID>/...` URL. **Display URLs (`/display/SPACE/Title`) and other shapes are rejected as `InvalidParams`** — resolve them to a page ID first (`c2n fetch` CLI does this).

### 2.2 Convert the XHTML

```jsonc
// → c2n MCP
{
  "name": "c2n_convert_page",
  "arguments": {
    "xhtml": "<p>…XHTML from step 2.1…</p>",
    "pageId": "123456789",
    "title": "Onboarding"
  }
}
```

Returns:

```jsonc
{
  "blocks": [ /* Notion block payloads, ready for append_blocks */ ],
  "unresolved": [
    {
      "id": "unresolved:123456789:macro:expand:0",
      "kind": "macro",
      "name": "expand",
      "snippet": "<ac:structured-macro ac:name=\"expand\">…",
      "pageId": "123456789"
    }
  ],
  "usedRules": { "rule:paragraph": 4, "rule:bullet-list": 1 }
}
```

`usedRules` is a counter map for diagnostics. `unresolved` lists every macro / construct the current ruleset has no rule for.

**If `unresolved.length > 0`:** decide whether to push ahead with a partial migration or branch into the [Q/A loop](#3-question--answer-loop-rule-accumulation) to teach c2n new rules and re-run. Most teams want zero-unresolved before creating the Notion page.

### 2.3 Create the Notion page (host's Notion MCP)

```jsonc
// → Notion MCP
{
  "name": "create_page",
  "arguments": {
    "parent": { "type": "page_id", "page_id": "<parent-page-id>" },
    "properties": {
      "title": [{ "type": "text", "text": { "content": "Onboarding" } }]
    }
  }
}
```

Returns the new page object; capture `notionPageId` (the `id` field).

### 2.4 Append the converted blocks

```jsonc
// → Notion MCP
{
  "name": "append_blocks",
  "arguments": {
    "block_id": "<notionPageId>",
    "children": [ /* blocks from step 2.2 */ ]
  }
}
```

Notion's API caps `children` at 100 per call; chunk if the converted page is larger.

### 2.5 Record the mapping

```jsonc
// → c2n MCP
{
  "name": "c2n_record_migration",
  "arguments": {
    "confluencePageId": "123456789",
    "notionPageId": "<notionPageId>",
    "slug": "example-123456789",
    "notionUrl": "https://www.notion.so/Onboarding-<id>"
  }
}
```

Persists to `output/runs/<slug>/mapping.json`. The slug is the run directory name — see [§4 Re-run and dedup](#4-re-run-and-dedup) for how a slug is created and discovered. `notionUrl` is optional but recommended; downstream reports surface it.

The c2n run directory must already exist (`c2n_record_migration` requires a real `<runsRoot>/<slug>/` directory). If it does not, you get `InvalidParams: No run directory found for slug "..."`. Create the run via the CLI (`c2n migrate`, `c2n migrate-tree`, `c2n migrate-tree-pages`), or `mkdir -p output/runs/<slug>` from the workspace before calling the tool.

---

## 3. Question / answer loop (rule accumulation)

When `c2n_convert_page` reports `unresolved`, teach c2n new rules instead of leaving gaps.

### 3.1 List the open questions

```jsonc
// → c2n MCP
{ "name": "c2n_list_unresolved", "arguments": { "slug": "example-123456789" } }
```

Returns the parsed contents of `output/runs/<slug>/resolution.json`: a `Record<string, string>` keyed by unresolved-item id. Empty (`{}`) if nothing is open.

> Pass `rootDir` if your host's `cwd` is not the workspace where `output/runs/` lives.

### 3.2 Collect answers

Out of band — chat thread, UI form, ops worksheet, whatever the host provides. Each answer becomes one `ProposedRule`.

### 3.3 Append a proposal per answer

```jsonc
// → c2n MCP
{
  "name": "c2n_propose_resolution",
  "arguments": {
    "rule_id": "rule:jira-link",
    "source_pattern_id": "pattern:jira-macro",
    "source_description": "Confluence Jira inline link macro",
    "notion_block_type": "bookmark",
    "mapping_description": "Map ac:link macros pointing at Jira to Notion bookmarks.",
    "example_input": "<ac:link><ri:url ri:value=\"https://jira/browse/X-1\"/></ac:link>",
    "example_output": { "type": "bookmark", "url": "https://jira/browse/X-1" },
    "confidence": "high"
  }
}
```

Appends to `output/proposals.json` (created if missing). `rule_id` must be unique within the file — duplicates fail as `InvalidParams`. Override the path with `proposalsPath` if `cwd` is not the workspace.

### 3.4 Finalize into rules.json

```jsonc
// → c2n MCP
{ "name": "c2n_finalize_proposals", "arguments": {} }
```

Materializes `output/proposals.json` → `output/rules.json` (same logic as the `c2n finalize` CLI). Optional `proposalsPath` and `rulesOutPath` overrides if the workspace layout is non-default. Returns `{ ruleCount, rulesPath }`.

### 3.5 Re-convert

Re-run [§2.2](#22-convert-the-xhtml) with the same `xhtml`. The new ruleset is picked up automatically; `unresolved` should shrink. Iterate until it's empty (or as small as you're willing to ship).

> **Why this is a loop.** New Confluence macros are discovered case-by-case in real migrations. The Q/A loop is the path that builds `rules.json` over time without hand-editing JSON. ADR-006 + the `develop`/`discover` pipelines own the same data model; the MCP tools are the host-driven entry into it.

---

## 4. Re-run and dedup

A "Confluence page already migrated to Notion" check is a join over c2n run mappings.

### 4.1 List existing runs

```jsonc
{ "name": "c2n_list_runs", "arguments": {} }
```

Returns a sorted array of slugs under `<rootDir>/output/runs/` (default `<cwd>/output/runs`). Empty array if the directory is missing.

### 4.2 Inspect a run

For a quick human-readable summary:

```jsonc
{ "name": "c2n_get_run_report", "arguments": { "slug": "example-123456789" } }
```

Returns the rendered `report.md` body (status per step, source URL, rules usage). For the structured mapping(s), read the resource template instead — see [§6](#6-schemas-referenced).

### 4.3 Dedup decision

Walk each run's `mapping.json` (one per page recorded in that run) and look for `confluencePageId === <new page>`:

- **Skip** — if a mapping exists and the team's policy is "migrate once, never re-migrate". Surface the existing `notionPageId` / `notionUrl` instead.
- **Replace** — if the source has changed and the team's policy is "always overwrite". Use the host's Notion MCP to clear the existing page (`update_block` / `delete_block` / Notion archive flow) and re-run [§2.4](#24-append-the-converted-blocks). c2n itself does **not** mutate Notion.
- **New copy** — create a fresh Notion page and call `c2n_record_migration` again with the new `notionPageId`. The same `confluencePageId` may end up with multiple mappings across runs; that is intentional (versioned migrations).

The dedup policy is a **host concern**. c2n exposes the data; the agent / skill decides what to do with it.

---

## 5. Tree migration

The MCP surface stays per-page deliberately. To migrate a sub-tree:

1. **Enumerate the tree first via the CLI.** `c2n fetch-tree` is the recommended path:

   ```bash
   npx -p confluence-to-notion c2n fetch-tree --root-id <pageId> --output output/page-tree.json
   ```

   `--root-id` is required and takes a Confluence page ID (not a URL). Pass `--url <url>` alongside it if you want the source URL recorded in the manifest. This writes a tree manifest you can iterate from the host.

2. **Loop the per-page MCP flow** for each page in the manifest:

   For each `pageId` in `page-tree.json`, run [§2.1](#21-fetch-the-confluence-page) → [§2.2](#22-convert-the-xhtml) → optional [§3](#3-question--answer-loop-rule-accumulation) → [§2.3](#23-create-the-notion-page-hosts-notion-mcp) → [§2.4](#24-append-the-converted-blocks) → [§2.5](#25-record-the-mapping). Maintain a `confluencePageId → notionPageId` map across iterations so child pages can be created under the right Notion parent (use the parent's `notionPageId` from the running map).

3. **Skip already-migrated pages** using [§4.3](#43-dedup-decision). Tree re-runs are the common case where dedup matters most.

> **Why no `c2n_migrate_tree` MCP tool.** Per ADR-007 the c2n MCP surface is read-mostly. Tree orchestration belongs in the host so it can apply its own concurrency, approval, and rate-limit policy against Notion. The CLI `c2n migrate-tree` family stays as a batch path for headless / cron runs that bypass MCP entirely.

---

## 6. Schemas referenced

The MCP tool inputs/outputs are pinned by zod schemas in this repo. Hosts that want to validate or generate types should pull these.

| Concept                             | File                                                                 | Symbol                          |
| ----------------------------------- | -------------------------------------------------------------------- | ------------------------------- |
| `ProposedRule` (Q/A loop body)      | [`src/agentOutput/schemas.ts`](../src/agentOutput/schemas.ts)        | `ProposedRuleSchema`            |
| Bag of proposals (`proposals.json`) | [`src/agentOutput/schemas.ts`](../src/agentOutput/schemas.ts)        | `ProposerOutputSchema`          |
| `RunResolution` (unresolved questions per run) | [`src/runs/index.ts`](../src/runs/index.ts) (re-export) ↔ [`src/runs/schemas.ts`](../src/runs/schemas.ts) | `RunResolutionSchema`           |
| `Mapping` (`mapping.json` payload)  | [`src/runs/index.ts`](../src/runs/index.ts) (re-export) ↔ [`src/runs/schemas.ts`](../src/runs/schemas.ts) | `MappingSchema`                 |

The MCP server also exposes resource templates for raw run artifacts (read via the host's `resources/read`):

| URI                                       | Returns                                            |
| ----------------------------------------- | -------------------------------------------------- |
| `c2n://runs/{slug}/source`                | `source.json` for the run.                         |
| `c2n://runs/{slug}/report`                | `report.md` for the run.                           |
| `c2n://runs/{slug}/resolution`            | `resolution.json` (same data as `c2n_list_unresolved`). |
| `c2n://runs/{slug}/converted/{pageId}`    | Converted Notion blocks for one page in the run.   |

`mapping.json` is not exposed as a resource template today — read it via the run directory directly when you need the structured form.

The tools/list and resource-templates/list payloads are pinned by `tests/fixtures/mcp/{tools-list,resource-templates-list}.json` and treated as the parity gate; what you see at runtime matches those fixtures byte-for-byte.

---

## 7. Failure modes

The c2n MCP server uses two MCP error codes: `InvalidParams` for caller-correctable input problems, `InvalidRequest` for environment / configuration problems the caller cannot fix from the call site. Treat them differently in host recovery logic.

### 7.1 `InvalidParams`

| Tool                       | Trigger                                                                                                   | Host recovery                                                                                                              |
| -------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `c2n_fetch_page`           | `pageIdOrUrl` is a display URL or any non-`pages/<id>` link.                                              | Ask the user for a page ID or a `/spaces/<KEY>/pages/<ID>/...` URL. Do not retry the same input.                            |
| `c2n_get_run_report`       | `report.md` does not exist for `slug` under the resolved runs root.                                       | Confirm the slug with `c2n_list_runs`. If the run is mid-flight, ask the user to wait for migration to finish.              |
| `c2n_list_unresolved`      | Run directory missing, or `resolution.json` missing.                                                       | Confirm the slug with `c2n_list_runs`. If the run never had a discover step, there is nothing to ask — surface to the user. |
| `c2n_propose_resolution`   | `rule_id` already exists in `proposals.json`.                                                              | Ask the user whether to pick a new id or replace. The MCP does not edit existing rules — replace = remove + re-propose offline. |
| `c2n_finalize_proposals`   | `proposals.json` missing or fails schema parse.                                                            | Surface the underlying message to ops; the file is hand-readable. Do not retry without fixing the file.                     |
| `c2n_record_migration`     | `slug` directory missing under the resolved runs root.                                                     | Either create the run first (CLI: `c2n migrate ...`) or `mkdir -p output/runs/<slug>` if the host owns the workspace.        |
| Resource read              | `c2n://runs/{slug}/...` artifact missing.                                                                  | Same as the equivalent tool — confirm the slug, or accept that the artifact is not produced for that run yet.                |

A reasonable default: **retry once if it's transient, otherwise prompt the user**. Do not loop on `InvalidParams` without changing the input.

### 7.2 `InvalidRequest`

| Tool             | Trigger                                                                                              | Host recovery                                                                                                                |
| ---------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `c2n_fetch_page` | Confluence credentials not resolved (no profile, no env vars).                                        | Surface to ops: run `c2n init` on the host, or set `CONFLUENCE_BASE_URL` + `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` in `env`. Asking the user is unhelpful — the fix is at the host config layer. |

`InvalidRequest` is a **stop-and-page-ops** signal: the c2n side is misconfigured at the host. Do not retry from chat.

### 7.3 Notion-side failures

These come from the host's Notion MCP, not c2n. Common shapes to handle:

- **Auth** — invalid `NOTION_TOKEN`, integration not invited to the parent page. Stop-and-page-ops; do not retry.
- **Rate limit** — Notion returns HTTP 429. Back off with jitter, then retry.
- **`children` size limits** — `append_blocks` caps at 100 children per call. Chunk and retry the remainder.
- **Parent not found** — the configured parent page id is wrong or revoked. Surface to user / ops, do not retry.

c2n has no visibility into these; the host's logging is the source of truth. Once Notion eventually returns a `notionPageId`, calling `c2n_record_migration` closes the loop on the c2n side.

### 7.4 Anything else

`MethodNotFound` from c2n means the tool name is wrong (typo or stale assumption against the [tools/list fixture](../tests/fixtures/mcp/tools-list.json)). Other thrown errors are unexpected and should be surfaced verbatim to ops.

---

## See also

- [`docs/slack-openclaw-c2n-bridge.md`](./slack-openclaw-c2n-bridge.md) — OpenClaw-specific integration handoff (channel routing, approval plumbing, profile store on the OpenClaw host).
- [`.claude/docs/ADR.md`](../.claude/docs/ADR.md) — ADR-007 (MCP read-mostly, Notion writes in host).
- [`src/mcp/README.md`](../src/mcp/README.md) — c2n MCP server internals, credential resolution.
- [`tests/fixtures/mcp/tools-list.json`](../tests/fixtures/mcp/tools-list.json) — pinned MCP tool surface.
