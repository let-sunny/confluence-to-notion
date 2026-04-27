# skills/c2n-migrate

Ready-to-use skill bundle that drives a Confluence → Notion migration through two MCP servers in tandem: the [c2n MCP server](../../src/mcp/README.md) (read-mostly: fetch / convert / Q&A / bookkeeping) and the host's Notion MCP server (page creation). The bundle is in Claude Code skill format (`SKILL.md` with YAML frontmatter) and is also accepted by OpenClaw's plugin runtime.

The skill itself is a runbook; the full flow lives in [`docs/migration-playbook.md`](../../docs/migration-playbook.md). This README only covers how to install the bundle and a smoke walk-through.

## Install

Copy this directory (`skills/c2n-migrate/`) into the host's skill location, then make sure both `c2n` and a Notion MCP server are registered (see [playbook §1](../../docs/migration-playbook.md#1-setup--register-both-mcp-servers)).

| Host                | Drop the bundle into                                                                    |
| ------------------- | --------------------------------------------------------------------------------------- |
| **Claude Code**     | `~/.claude/skills/c2n-migrate/` (user-level) or `<repo>/.claude/skills/c2n-migrate/` (project-level). Restart the CLI. |
| **OpenClaw**        | The plugin runtime accepts the same `<bundle>/SKILL.md` layout. Drop the directory under your OpenClaw skills root and reload. |
| **Claude Desktop**  | `~/Library/Application Support/Claude/skills/c2n-migrate/` on macOS (or the equivalent app data dir on other OSes). Restart the app. |
| **Codex / Cursor / custom** | If the host supports Claude Code skill bundles, point its skill loader at this directory. Otherwise, use `SKILL.md` as the system prompt and register `c2n` + Notion MCP via the host's MCP config. |

Out of scope for this bundle: npm publish / clawhub publish workflows, and multi-tenant / multi-workspace setups (the skill assumes a single c2n profile + a single Notion workspace per session). Both are tracked separately.

> **Distribution note**: `skills/` is not in the npm tarball (`package.json` `files` whitelist excludes it), so `npm i -g confluence-to-notion` does not install this bundle. Clone or download the repo to get it.

## Smoke walk-through (single page)

Once both MCP servers are registered and the skill bundle is loaded:

1. In a new chat, paste a Confluence page URL: `https://example.atlassian.net/wiki/spaces/ENG/pages/123456789/Onboarding`. Ask "migrate this to Notion under <parent page>".
2. The skill calls `c2n_fetch_page`, then `c2n_convert_page`. If `unresolved` is empty, it skips to step 4. Otherwise it surfaces the open questions in plain language and waits for your answers, calling `c2n_propose_resolution` per answer and then `c2n_finalize_proposals` before re-converting.
3. The skill calls the host's Notion MCP `create_page` (under the parent you named) and `append_blocks` (chunked at 100 children) to write the page.
4. The skill calls `c2n_record_migration` so the run mapping is persisted under `output/runs/<slug>/mapping.json`.
5. Verify: open the new Notion page, then check that `output/runs/<slug>/mapping.json` shows `confluencePageId` → `notionPageId`. A subsequent ask to migrate the same Confluence URL should hit the dedup path and surface the existing `notionPageId` instead of creating a duplicate.

For sub-tree migrations, see [playbook §5](../../docs/migration-playbook.md#5-tree-migration) — the skill drives the per-page flow in a loop after `c2n fetch-tree` produces the manifest.

## See also

- [`SKILL.md`](./SKILL.md) — the runbook the host loads.
- [`docs/migration-playbook.md`](../../docs/migration-playbook.md) — full flow with tool inputs/outputs and error tables.
- [`tests/fixtures/mcp/tools-list.json`](../../tests/fixtures/mcp/tools-list.json) — pinned c2n MCP tool surface.
