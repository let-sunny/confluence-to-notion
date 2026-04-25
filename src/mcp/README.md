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

`c2n_migrate_page` requires both a Confluence adapter (built from the
`CONFLUENCE_*` env vars) and a Notion adapter (built from `NOTION_TOKEN`); a
missing factory surfaces as an `InvalidRequest` error naming the missing env
contract.

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

The stdio entry (`src/mcp/index.ts`) reads:

| Env var                   | Used for                                                                                       |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| `CONFLUENCE_BASE_URL`     | Builds the Confluence adapter for `c2n_fetch_page` and `c2n_migrate_page`.                     |
| `CONFLUENCE_EMAIL`        | Same.                                                                                          |
| `CONFLUENCE_API_TOKEN`    | Same.                                                                                          |
| `NOTION_TOKEN`            | Builds the Notion adapter for `c2n_migrate_page`.                                              |

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
