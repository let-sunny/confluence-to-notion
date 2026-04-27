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

### Write

| Name                | Required input                              | Returns                                                                                              | Notes                                                                                                                                   |
| ------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `c2n_migrate_page`  | `pageIdOrUrl`, `parentNotionPageId`         | JSON text: `{ notionPageId?, sourcePageId, title, blockCount, unresolvedCount, dryRun? }`            | Disabled unless the server is started with `allowWrite: true`. With `dryRun: true` the converter still runs but Notion is not called. |

`c2n_migrate_page` requires both a Confluence adapter and a Notion adapter
(see [Configuration](#configuration) for the resolution order). A missing
credential surfaces as an `InvalidRequest` error suggesting `c2n init` or the
matching env var.

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
| `CONFLUENCE_BASE_URL`     | Builds the Confluence adapter for `c2n_fetch_page` and `c2n_migrate_page`.                     |
| `CONFLUENCE_EMAIL`        | Same.                                                                                          |
| `CONFLUENCE_API_TOKEN`    | Same.                                                                                          |
| `NOTION_TOKEN`            | Builds the Notion adapter for `c2n_migrate_page`.                                              |
| `C2N_CONFIG_DIR`          | Override the config-store directory (defaults to `~/.config/c2n`). Useful for tests.           |

Once a user has run `c2n init`, the `env:` block in
`claude_desktop_config.json` becomes optional: the MCP server reads creds from
the store under the resolved profile. Missing creds surface as an
`InvalidRequest` error suggesting `c2n init` or env vars.

`allowWrite` and `runsRoot` are constructor options on `createServer` rather
than env vars; the production stdio entry decides how to wire them based on
the deployment context.

## Errors

| Condition                                                  | `ErrorCode`           |
| ---------------------------------------------------------- | --------------------- |
| Write tool invoked while `allowWrite` is `false`           | `InvalidRequest`      |
| Required env-driven adapter is unavailable                 | `InvalidRequest`      |
| Unknown run slug or missing run artifact (`ENOENT`)        | `InvalidParams`       |
| Unsupported resource URI scheme or unknown URI shape       | `InvalidParams`       |
| Display-style Confluence URL passed to `c2n_fetch_page`    | `InvalidParams`       |
| Tool name not handled                                      | `MethodNotFound`      |
