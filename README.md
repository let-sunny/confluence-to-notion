# confluence-to-notion

> Auto-discover Confluence → Notion transformation rules with a Claude
> multi-agent pipeline, then apply them with a deterministic TypeScript
> converter.

[![npm version](https://img.shields.io/npm/v/confluence-to-notion.svg)](https://www.npmjs.com/package/confluence-to-notion)
[![npm downloads](https://img.shields.io/npm/dm/confluence-to-notion.svg)](https://www.npmjs.com/package/confluence-to-notion)
[![CI](https://img.shields.io/github/actions/workflow/status/let-sunny/confluence-to-notion/ci.yml?branch=main&label=CI)](https://github.com/let-sunny/confluence-to-notion/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Node 20+](https://img.shields.io/badge/node-%3E%3D20-brightgreen.svg)](./.nvmrc)

Migrating a Confluence wiki to Notion is painful: Confluence stores content as
XHTML with proprietary macros, Notion uses a block-based model, and existing
tools either lose structure or require extensive manual mapping. This project
asks Claude to discover patterns in your Confluence pages, propose
transformation rules, and then apply them deterministically — so the same
wiki always migrates the same way.

## Install

```bash
npm i -g confluence-to-notion
# exposes `c2n` and `c2n-mcp` binaries
```

Or run without installing:

```bash
npx confluence-to-notion c2n --help
```

Requires Node 20 LTS or newer.

## Quickstart

Migrate an entire Confluence subtree (pages + bodies) into a Notion parent
page:

```bash
export CONFLUENCE_BASE_URL="https://your-org.atlassian.net/wiki"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="<atlassian-api-token>"
export NOTION_API_TOKEN="ntn_..."
export NOTION_ROOT_PAGE_ID="<notion-page-id>"

c2n notion-ping                                 # verify the Notion token
c2n migrate-tree-pages \
  --root-id <confluence-root-page-id> \
  --url "https://your-org.atlassian.net/wiki/spaces/DOC/pages/<id>"
```

For a single page see
[`examples/migrate-single-page.md`](./examples/migrate-single-page.md).

## Configuration

All configuration is via environment variables loaded from `.env` (or the
shell). The full table — required vs. optional, defaults, and self-hosted
overrides — lives in
[`CONTRIBUTING.md` § 1](./CONTRIBUTING.md#1-development-environment-setup).

Public wikis (e.g. `cwiki.apache.org`) only need `CONFLUENCE_BASE_URL`.
Private Atlassian Cloud wikis additionally need `CONFLUENCE_EMAIL` +
`CONFLUENCE_API_TOKEN`. Any command that writes to Notion needs
`NOTION_API_TOKEN` and `NOTION_ROOT_PAGE_ID`.

## Commands

The CLI surface is frozen by
[ADR-00M](./.claude/docs/ADR-00M-cli-surface-freeze.md); each subcommand below
is a stable contract.

| Command | Purpose |
| --- | --- |
| `c2n fetch` | Fetch Confluence pages by space or page IDs and save XHTML to disk. |
| `c2n fetch-tree` | Fetch the Confluence page tree starting from a root page. |
| `c2n notion-ping` | Validate the Notion API token by fetching the bot user. |
| `c2n validate-output` | Validate an agent output JSON file against its schema. |
| `c2n finalize` | Promote `proposals.json` → `rules.json` for enabled rules. |
| `c2n convert` | Convert XHTML pages to Notion blocks using finalized rules. |
| `c2n eval` | Run schema validation, semantic coverage, optional LLM judge, and baseline diff. |
| `c2n migrate` | Convert XHTML and publish to Notion (single page or URL-dispatched fan-out). |
| `c2n migrate-tree` | Create an empty Notion page hierarchy mirroring a Confluence tree. |
| `c2n migrate-tree-pages` | Multi-pass tree migration: tree → table-rule discovery → body upload. |

Run `c2n <command> --help` for flags, or see
[ADR-00M](./.claude/docs/ADR-00M-cli-surface-freeze.md) for the authoritative
spec.

## MCP setup

`c2n-mcp` runs an MCP (Model Context Protocol) server over stdio so MCP-aware
clients (Claude Desktop, custom MCP clients) can drive Confluence → Notion
migrations through a stable contract.

A ready-to-paste Claude Desktop config snippet lives at
[`examples/mcp/claude-desktop.json`](./examples/mcp/claude-desktop.json).
The full tool / resource / error contract is documented in
[`src/mcp/README.md`](./src/mcp/README.md).

## Architecture

See [`.claude/docs/architecture.md`](./.claude/docs/architecture.md) for the
system diagram, execution model, and per-run artifact layout. The Python →
TypeScript port that produced the current package is documented in
[`.claude/docs/ADR-00N-port-to-typescript.md`](./.claude/docs/ADR-00N-port-to-typescript.md).

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for development setup, the agent
prompt-change policy, the eval-gate rules, testing, and PR conventions.

## License

[MIT](./LICENSE)
