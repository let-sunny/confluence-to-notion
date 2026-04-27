# Changelog

All notable changes to this project are documented here. This project adheres
to [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and, once
published, [Semantic Versioning](https://semver.org/).

## [0.1.4] - 2026-04-28

### Changed

- **MCP architecture (ADR-007): the `c2n-mcp` server is now read-mostly.**
  Notion writes move out of c2n and into whichever Notion MCP the host
  runtime already runs. The previous `allowWrite` gate
  (`C2N_MCP_ALLOW_WRITE=1`) is gone — it added friction without moving the
  security boundary, since the Notion token in the profile store can write
  through any other client.

### Added

- Four new MCP tools that expose ADR-005's "ask the human, persist as a
  rule" loop directly on the wire:
  - `c2n_list_unresolved` — surface ambiguities the converter could not
    resolve.
  - `c2n_propose_resolution` — append an answered proposal to
    `output/proposals.json`.
  - `c2n_finalize_proposals` — promote enabled proposals into
    `output/rules.json`.
  - `c2n_record_migration` — ingest the Notion page ID the host created;
    persisted at `output/runs/<slug>/mapping.json` so re-runs can detect
    duplicates.
- `docs/migration-playbook.md` — vendor-neutral end-to-end runbook
  covering setup, single-page flow, question/answer loop, re-run dedup,
  tree migration, schemas, and failure modes.
- `skills/c2n-migrate/` reference skill bundle (Claude Code skill format,
  also accepted by OpenClaw's plugin runtime). Drives the playbook
  autonomously when dropped into the host's skill directory.

### Removed

- `c2n_migrate_page` MCP tool. Hosts compose `c2n_convert_page` (returns
  Notion-block payload) with their Notion MCP's `create_page` +
  `append_blocks`. The CLI `c2n migrate` keeps the in-package Notion
  adapter for batch / non-bot use cases.

### Notes

- Final MCP surface: 8 tools (4 read, 3 ask/answer, 1 ingest).
- Breaking: hosts that called `c2n_migrate_page` get `MethodNotFound`.
  Migration path is in [`docs/migration-playbook.md`](./docs/migration-playbook.md).
- Architecture rationale in
  [ADR-007](./.claude/docs/ADR.md#adr-007-mcp-surface--read-mostly-notion-writes-live-in-the-host).
- Tracked across [#212](https://github.com/let-sunny/confluence-to-notion/issues/212),
  [#214](https://github.com/let-sunny/confluence-to-notion/issues/214),
  [#215](https://github.com/let-sunny/confluence-to-notion/issues/215),
  [#216](https://github.com/let-sunny/confluence-to-notion/issues/216),
  [#219](https://github.com/let-sunny/confluence-to-notion/issues/219).

## [0.1.3] - 2026-04-27

### Added

- `c2n init` interactive setup writes Confluence + Notion credentials to a
  per-user config file (no more re-exporting env vars in every shell).
- `c2n auth confluence` / `c2n auth notion` update one side of an existing
  profile.
- Named profiles via `--profile <name>` and `C2N_PROFILE`, plus
  `c2n profiles list` and `c2n use <name>` for inspection and switching.
- Profile-aware credential resolution wired through every data-prep
  subcommand: `fetch`, `fetch-tree`, `notion-ping`, `convert`, `migrate`,
  `migrate-tree`, and `migrate-tree-pages`.
- The MCP server (`c2n-mcp` / `src/mcp/server.ts`) now reads credentials
  through the same profile store, so the `env:` block in
  `claude_desktop_config.json` becomes optional once `c2n init` has been run.

See [ADR-00M](./.claude/docs/ADR-00M-cli-surface-freeze.md) for the
authoritative spec.

## [0.1.2] - 2026-04-26

### Fixed

- `c2n` and `c2n-mcp` bins are no-ops when launched through the npm bin
  symlink (`node_modules/.bin/<bin>`). The direct-invocation guard compared
  `process.argv[1]` (symlink path) to `import.meta.url` (real path) without
  resolving symlinks, so the guard was always false. Both entrypoints now
  resolve `realpath` on each side before comparing. Affects every consumer
  using `npm i -g`, `npx`, or any local install — 0.1.0 / 0.1.1 silently
  exited 0 with no output. Adds a regression test that invokes the built
  CLI through a symlink to catch this in the future.

## [0.1.1] - 2026-04-26

First post-release patch. No user-visible behaviour changes; verifies the
tag-driven trusted-publisher OIDC release workflow end-to-end.

### Changed

- Converter now matches the Python baseline for unknown macros, emitting a
  `[<macro>] <text>` paragraph instead of a typed `unsupportedMacro` block
  ([#184](https://github.com/let-sunny/confluence-to-notion/pull/184)).
  `KNOWN_FAILING_IDS` in the equivalence test is empty — all 30+ converter
  fixtures now match the baseline natively.
- Integration tests build `dist/cli.js` exactly once per `vitest run` via a
  shared `tests/globalSetup.ts`, replacing duplicated `beforeAll` blocks
  ([#183](https://github.com/let-sunny/confluence-to-notion/pull/183)).

## [0.1.0] - 2026-04-26

Initial public release. `confluence-to-notion` is now a Node 20 / TypeScript
package on npm. This is the baseline of the rewrite tracked by
[#129](https://github.com/let-sunny/confluence-to-notion/issues/129); it
ships the full migration pipeline (fetch → convert → upload), the deterministic
XHTML → Notion converter, the eval harness, and a read-only MCP server.

### Added

- TypeScript runtime (Node 20 LTS, ESM, strict + `noUncheckedIndexedAccess`)
  with `tsup` bundling to `dist/cli.js` + `dist/mcp.js`.
- Frozen CLI surface per
  [ADR-00M](./.claude/docs/ADR-00M-cli-surface-freeze.md): `fetch`,
  `fetch-tree`, `notion-ping`, `validate-output`, `finalize`, `convert`,
  `eval`, `migrate`, `migrate-tree`, `migrate-tree-pages`.
- Deterministic XHTML → Notion converter with a golden-fixture parity gate
  ([#163](https://github.com/let-sunny/confluence-to-notion/pull/163),
  [#164](https://github.com/let-sunny/confluence-to-notion/pull/164)) and an
  end-to-end `--url` integration covering converted artifacts
  ([#168](https://github.com/let-sunny/confluence-to-notion/pull/168)).
- Eval harness with schema validation, semantic coverage, baseline diff, and
  LLM-as-judge parity
  ([#151](https://github.com/let-sunny/confluence-to-notion/pull/151),
  [#170](https://github.com/let-sunny/confluence-to-notion/pull/170)).
- MCP server with a parity gate
  ([#171](https://github.com/let-sunny/confluence-to-notion/pull/171)) and
  read-only tool handlers `c2n_convert_page`, `c2n_fetch_page`,
  `c2n_list_runs`, `c2n_get_run_report`
  ([#173](https://github.com/let-sunny/confluence-to-notion/pull/173)).
- CI workflow (`.github/workflows/ci.yml`) running `pnpm lint` /
  `pnpm typecheck` / `pnpm test` / `pnpm build` on Linux, macOS, and Windows.
- Release workflow (`.github/workflows/release.yml`) wired to
  `changesets/action@v1` with `--provenance`
  ([#149](https://github.com/let-sunny/confluence-to-notion/pull/149)).

### Removed

- `src/confluence_to_notion/` Python package.
- `pyproject.toml`, `uv.lock`, and the legacy `tests/` (Python/pytest) suite.

### Notes

- First npm publish. `0.1.0` is the public TypeScript baseline; the package
  follows [Semantic Versioning](https://semver.org/) from this release on.
- MCP write tools (`c2n_migrate_page`) and resource content
  (`c2n://runs/<slug>/...`) land in a follow-up issue carved out of
  [#172](https://github.com/let-sunny/confluence-to-notion/issues/172).
