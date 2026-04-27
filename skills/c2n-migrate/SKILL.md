---
name: c2n-migrate
description: Migrate a Confluence page or page tree into Notion by composing the c2n MCP server (fetch + convert + Q/A loop + bookkeeping) with the host's Notion MCP server (page creation). Trigger when the user asks to migrate, port, copy, or move Confluence content to Notion — typically by pasting a Confluence page URL or a Confluence page ID, or by referring to a sub-tree under one of those.
---

# c2n-migrate

End-to-end runbook for moving Confluence content to Notion using two MCP servers in tandem:

- **c2n** — read-mostly: fetches Confluence, converts XHTML to Notion blocks, accumulates rules, records mappings.
- **Notion MCP** (host's choice, e.g. `@notionhq/notion-mcp-server`) — performs the actual `create_page` / `append_blocks` writes against the workspace.

This skill is a runbook, not a copy. The authoritative flow lives in [`docs/migration-playbook.md`](../../docs/migration-playbook.md); load it for full detail (per-tool inputs/outputs, error codes, schema references) when you need it. The sections below mirror its numbering so you can jump back and forth.

## When to invoke

Trigger on any of:

- The user pastes a Confluence page URL (`/spaces/<KEY>/pages/<ID>/...`) and asks to migrate, port, copy, or move it.
- The user gives a Confluence page ID and the target system is Notion.
- The user asks to migrate a sub-tree, child pages, or a whole space rooted at a given page.

Do not trigger on generic "Confluence vs Notion" comparison questions or on Notion-only edits.

## Preconditions

Both MCP servers must already be registered on the host (see playbook §1). c2n credentials are resolved through the c2n profile store (`c2n init`) or `CONFLUENCE_*` env vars. Notion writes use the host's configured `NOTION_TOKEN`. If either side is missing, surface to ops and stop — do not retry from chat.

## Single-page flow (playbook §2)

Run these in order. Each numbered step is one tool call.

1. **Resolve the input.** If the user gave a display URL (`/display/...`) or a non-pages link, ask for a page ID or a `/pages/<ID>/...` URL — `c2n_fetch_page` rejects anything else as `InvalidParams`.
2. **Fetch.** Call `c2n_fetch_page` with `{ pageIdOrUrl }`. Capture `pageId`, `title`, `body.storage.value`.
3. **Convert.** Call `c2n_convert_page` with `{ xhtml: body.storage.value, pageId, title }`. Capture `blocks` and `unresolved`.
4. **If `unresolved.length > 0` →** branch into the [Q/A loop](#qa-loop-playbook-3) below. Re-run step 3 once new rules land. Default policy: do not create the Notion page until `unresolved` is empty (most teams want zero-unresolved). If the user explicitly opts into a partial migration, proceed and surface the gap in your final summary.
5. **Create the Notion page.** Call the host's Notion MCP `create_page` with `{ parent, properties: { title } }`. Capture the returned page id as `notionPageId`.
6. **Append blocks.** Call the host's Notion MCP `append_blocks` with `{ block_id: notionPageId, children: blocks }`. **Chunk `children` at 100 per call** — Notion's API rejects more in a single request. Loop until all blocks land.
7. **Record the mapping.** Call `c2n_record_migration` with `{ confluencePageId: pageId, notionPageId, slug }` and optionally `notionUrl` if the Notion MCP returned one. The `slug` must already exist as a directory under `<rootDir>/output/runs/`; if it does not, ask the user to create the run via the c2n CLI (`c2n migrate ...`) or `mkdir -p output/runs/<slug>` first. Without this step, the dedup check in §4 cannot see the page.

When you finish, summarize: source URL, `notionPageId`, run slug, count of unresolved that were resolved during the session, and any partial-migration gaps.

## Q/A loop (playbook §3)

Triggered when `c2n_convert_page` returns a non-empty `unresolved` list.

1. Call `c2n_list_unresolved` with `{ slug }` (and `rootDir` if the host's `cwd` is not the workspace). The result is a `Record<string, string>` keyed by unresolved-item id.
2. **Surface the open questions to the human in plain language**, one bullet per id. Quote the macro / construct name and the snippet so the human can answer without opening the playbook. Wait for answers — do not invent rules autonomously when meaning is ambiguous.
3. For each answer, call `c2n_propose_resolution` with the full `ProposedRule` payload (`rule_id`, `source_pattern_id`, `source_description`, `notion_block_type`, `mapping_description`, `example_input`, `example_output`, `confidence`). Each `rule_id` must be unique within `proposals.json`; on `InvalidParams` ask the human whether to pick a new id or replace.
4. Once all answers have been proposed, call `c2n_finalize_proposals` (no required arguments). This materializes `output/proposals.json` → `output/rules.json`.
5. Re-run `c2n_convert_page` with the same XHTML. `unresolved` should shrink. Iterate until it is empty (or the user accepts the remaining gap).

This loop is how the ruleset grows over time — never hand-edit `output/rules.json`.

## Re-run and dedup (playbook §4)

Before fetching, on any user request that names a Confluence page already in scope of an earlier run:

1. Call `c2n_list_runs` (optionally with `rootDir`) to get the list of slugs.
2. For each slug, read its `mapping.json` via the run directory and look for `confluencePageId === <new page>`. (`c2n_get_run_report` gives a human-readable summary if you want context.)
3. Decide with the user (do not auto-pick):
   - **Skip** if the team's policy is "migrate once, never re-migrate" — surface the existing `notionPageId` / `notionUrl` and stop.
   - **Replace** if the source has changed and the policy is "always overwrite" — clear the existing Notion page using the host's Notion MCP (`update_block` / `delete_block` / archive flow) and re-run the append. c2n itself never mutates Notion.
   - **New copy** — create a fresh Notion page and call `c2n_record_migration` again; the same `confluencePageId` may end up with multiple mappings across runs (intentional, versioned).

The dedup policy is a host concern; c2n only exposes the data.

## Tree migration (playbook §5)

There is no `c2n_migrate_tree` MCP tool by design (ADR-007 — the MCP surface is read-mostly). For a sub-tree:

1. Ask the user to enumerate the tree from the CLI first:
   ```bash
   npx -p confluence-to-notion c2n fetch-tree --root-id <pageId> --output output/page-tree.json
   ```
   `--root-id` is required and must be a page ID, not a URL. Optionally pass `--url <url>` to record the source URL in the manifest.
2. For each entry in `page-tree.json`, run the [single-page flow](#single-page-flow-playbook-2). Maintain a `confluencePageId → notionPageId` map across iterations so child pages get created under the right Notion parent (use the parent's `notionPageId` from the running map).
3. Skip pages already migrated using the [dedup decision](#re-run-and-dedup-playbook-4). Tree re-runs are the common case where dedup matters most.

For headless / cron tree runs that bypass MCP entirely, point at the CLI `c2n migrate-tree` family instead.

## Tools used

c2n MCP (this skill orchestrates all of these): `c2n_fetch_page`, `c2n_convert_page`, `c2n_list_unresolved`, `c2n_propose_resolution`, `c2n_finalize_proposals`, `c2n_record_migration`, `c2n_list_runs`. (`c2n_get_run_report` is optional, used for human-readable run summaries during dedup.)

Notion MCP (host): `create_page`, `append_blocks`. Other Notion MCP implementations may name these differently — adapt to the registered server's tool list rather than guessing. Do not invent c2n tool names; the authoritative surface is [`tests/fixtures/mcp/tools-list.json`](../../tests/fixtures/mcp/tools-list.json).

## Failure handling (playbook §7)

- **`InvalidParams` from c2n** — input the caller can fix (bad URL shape, duplicate `rule_id`, missing run slug). Ask the user with a specific correction; do not loop on the same input.
- **`InvalidRequest` from c2n** — host-side misconfiguration (Confluence creds unresolved). Surface to ops and stop.
- **Notion auth / parent-not-found** — stop and surface; never retry blindly.
- **Notion 429** — back off with jitter, then retry.
- **`children > 100`** — chunk and retry the remainder; never escalate to the user.
- **`MethodNotFound` from c2n** — the tool name is wrong (typo or stale assumption). Re-check against `tools-list.json`.

## See also

- [`docs/migration-playbook.md`](../../docs/migration-playbook.md) — full flow with request/response shapes and error tables.
- [`README.md`](./README.md) — bundle install per host and a smoke walk-through.
