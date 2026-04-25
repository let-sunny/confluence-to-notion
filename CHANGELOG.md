# Changelog

All notable changes to this project are documented here. This project adheres
to [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and, once
published, [Semantic Versioning](https://semver.org/).

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
