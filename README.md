# confluence-to-notion

> **Work in progress.** `confluence-to-notion` is being rewritten from Python
> to TypeScript across PRs #129 → #133. PR 1/5 replaces the Python scaffold
> with a Node/TS toolchain; the CLI, converter, and MCP server are filled in
> over PRs 2–5. The package is **not yet published** — do not run
> `npm i -g confluence-to-notion` until PR 5 lands.

Auto-discover Confluence → Notion transformation rules using a multi-agent
pipeline powered by Claude. Instead of hand-coding migration rules for every
Confluence macro and layout pattern, this tool analyses your wiki pages and
derives the rules for you. A deterministic TypeScript converter then applies
them so the same wiki always migrates the same way.

## Intended install (post-PR-5)

```bash
npm i -g confluence-to-notion
# => exposes `c2n` and `c2n-mcp` binaries
```

Until PR 5 publishes, clone the repo and run `pnpm` scripts directly (see
below).

## Why

Migrating a Confluence wiki to Notion is painful. Confluence stores content as
XHTML with proprietary macros; Notion uses a block-based model. Existing tools
either lose structure or require extensive manual mapping. This project asks
Claude to discover patterns in your Confluence pages, propose transformation
rules, and then apply them deterministically.

## Prerequisites

- Node 20 LTS (see `.nvmrc`)
- [pnpm](https://pnpm.io/) 9+
- [Claude Code CLI](https://docs.claude.com/claude-code) (`claude`) — required
  to run the discovery agents
- A Notion integration token with access to a target parent page
- For private Confluence Cloud: Atlassian email + API token. Public wikis
  (e.g. `cwiki.apache.org`) need only the base URL.

## Development setup

```bash
git clone https://github.com/let-sunny/confluence-to-notion.git
cd confluence-to-notion
pnpm install

pnpm test       # vitest
pnpm lint       # biome
pnpm typecheck  # tsc --noEmit
pnpm build      # tsup → dist/cli.js + dist/mcp.js
```

`pnpm build` produces `./dist/cli.js`, which you can invoke directly:

```bash
node ./dist/cli.js --version
```

The CLI currently only answers `--version` / `--help`; subcommands land in PR 4
of #129. Tracking issue: <https://github.com/let-sunny/confluence-to-notion/issues/129>.

## Architecture

See [`.claude/docs/architecture.md`](.claude/docs/architecture.md) for the
full system diagram, execution model, and per-run artifact layout.

Load-bearing ADRs:

- [`.claude/docs/ADR-00N-port-to-typescript.md`](.claude/docs/ADR-00N-port-to-typescript.md)
  — Python → TypeScript port strategy.
- [`.claude/docs/ADR-00M-cli-surface-freeze.md`](.claude/docs/ADR-00M-cli-surface-freeze.md)
  — frozen CLI surface that PR 4 will reimplement.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT
