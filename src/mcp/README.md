# c2n MCP server

`c2n` ships an MCP (Model Context Protocol) server over stdio so MCP-aware
clients (Claude Desktop, custom MCP clients) can drive Confluence → Notion
migrations through a stable contract. The `tools/list` and
`resources/templates/list` payloads are pinned by a parity gate against
`tests/fixtures/mcp/{tools-list,resource-templates-list}.json`; any change to
the listings requires updating those fixtures in lockstep.

## Tools

All inputs are JSON objects (`additionalProperties: false`).

### Read-only

| Name                  | Required input                       | Returns                                                                                | Notes                                                                                              |
| --------------------- | ------------------------------------ | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `c2n_fetch_page`      | `pageIdOrUrl`                        | JSON text: `{ pageId, title, spaceKey, version, body.storage.{value,representation} }` | Optional `baseUrl` overrides `CONFLUENCE_BASE_URL`. Display-style URLs are rejected.               |
| `c2n_convert_page`    | `xhtml`                              | JSON text: `ConversionResult` (`{ blocks, unresolved, usedRules }`)                    | Optional `pageId` is threaded into unresolved entries so they can be reconciled later.             |
| `c2n_list_runs`       | _(none)_                             | JSON text: sorted array of run slugs                                                   | Optional `rootDir` overrides the default `<cwd>/output/runs`.                                      |
| `c2n_get_run_report`  | `slug`                               | Plain text of `report.md`                                                              | Optional `rootDir` override; `ENOENT` surfaces as `InvalidParams` naming the slug.                 |

### Ingest (write)

Per [ADR-007](../../.claude/docs/ADR.md), the previous `c2n_migrate_page`
write tool is gone: host runtimes compose `c2n_convert_page` with their own
Notion MCP (`create_page` / `append_blocks`) and then post the resulting
Notion page ID back through `c2n_record_migration`, which is the only write
path the c2n MCP server exposes.

| Name                    | Required input                                | Returns                                              | Notes                                                                                                                                            |
| ----------------------- | --------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `c2n_record_migration`  | `confluencePageId`, `notionPageId`, `slug`    | JSON text: the persisted mapping                     | Optional `notionUrl` and `rootDir`. Persists `output/runs/<slug>/mapping.json`; an unknown slug surfaces as `InvalidParams` naming the slug.    |

The ask/answer ingest tools `c2n_list_unresolved`, `c2n_propose_resolution`,
and `c2n_finalize_proposals` land in a follow-up to issue
[#214](https://github.com/let-sunny/confluence-to-notion/issues/214); until
they ship, hosts that need to handle unresolved items keep going through the
CLI.

## Resources

The server exposes four URI templates under the `c2n://runs/{slug}/...`
scheme. Each one resolves to a single artifact under
`<runsRoot>/<slug>/`.

| URI template                              | File on disk                          | mimeType                  |
| ----------------------------------------- | ------------------------------------- | ------------------------- |
| `c2n://runs/{slug}/source`                | `source.json`                         | `application/xhtml+xml`   |
| `c2n://runs/{slug}/report`                | `report.md`                           | `application/json`        |
| `c2n://runs/{slug}/converted/{pageId}`    | `converted/<sanitized-pageId>.json`   | `application/json`        |
| `c2n://runs/{slug}/resolution`            | `resolution.json`                     | `application/json`        |

`{pageId}` is sanitized on read with the same `/[^\w.-]+/g` → `_` rule the
converter writer uses, so reads round-trip cleanly with whatever
`writeConvertedPage` produced.

## Configuration

The stdio entry (`src/mcp/index.ts`) resolves credentials through the same
profile store as the CLI. Resolution order:

1. `--profile <name>` flag (when invoked from a wrapper that passes one)
2. `C2N_PROFILE` env var
3. `currentProfile` recorded in the config file
4. `"default"`

If the resolved profile is missing or incomplete, the entry falls back to
direct env vars so existing deployments keep working:

| Env var                   | Used for                                                                                       |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| `CONFLUENCE_BASE_URL`     | Builds the Confluence adapter for `c2n_fetch_page`.                                            |
| `CONFLUENCE_EMAIL`        | Same.                                                                                          |
| `CONFLUENCE_API_TOKEN`    | Same.                                                                                          |
| `C2N_CONFIG_DIR`          | Override the config-store directory (defaults to `~/.config/c2n`). Useful for tests.           |

Once a user has run `c2n init`, the `env:` block in
`claude_desktop_config.json` becomes optional: the MCP server reads creds from
the store under the resolved profile. Missing creds surface as an
`InvalidRequest` error suggesting `c2n init` or env vars.

`runsRoot` is a constructor option on `createServer` rather than an env var;
the production stdio entry decides how to wire it based on the deployment
context.

## Errors

| Condition                                                  | `ErrorCode`           |
| ---------------------------------------------------------- | --------------------- |
| Required env-driven adapter is unavailable                 | `InvalidRequest`      |
| Unknown run slug or missing run artifact (`ENOENT`)        | `InvalidParams`       |
| Unsupported resource URI scheme or unknown URI shape       | `InvalidParams`       |
| Display-style Confluence URL passed to `c2n_fetch_page`    | `InvalidParams`       |
| Tool name not handled                                      | `MethodNotFound`      |
