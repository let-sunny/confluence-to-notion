# Changelog

All notable changes to this project are documented here. This project adheres
to [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and, once
published, [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Port to TypeScript (in progress).** The Python runtime has been removed and
  replaced with a Node 20 / TypeScript scaffold as the first of five PRs that
  rewrite `confluence-to-notion`. See issue
  [#129](https://github.com/let-sunny/confluence-to-notion/issues/129) for the
  full series and
  [`.claude/docs/ADR-00N-port-to-typescript.md`](./.claude/docs/ADR-00N-port-to-typescript.md)
  for the port strategy.

### Added

- TypeScript toolchain: `tsup`, `vitest`, `biome`, `commander`, pinned
  TypeScript 5 and Node 20 LTS via `.nvmrc`.
- CI workflow (`.github/workflows/ci.yml`) running `pnpm lint` / `pnpm typecheck`
  / `pnpm test` / `pnpm build` on Linux + macOS + Windows.
- Release workflow (`.github/workflows/release.yml`) wired to
  `changesets/action@v1` with `--provenance`. Inert until PR 5 initialises
  changesets.
- Frozen CLI surface inventory in
  [`.claude/docs/ADR-00M-cli-surface-freeze.md`](./.claude/docs/ADR-00M-cli-surface-freeze.md)
  that PR 4 will reimplement verbatim.

### Removed

- `src/confluence_to_notion/` Python package.
- `pyproject.toml`, `uv.lock`, and `tests/` (Python/pytest).

### Note

This release is **not published**. Users cannot install or run the migration
pipeline until PR 5 ships; the CLI currently answers only `--version` and
`--help`.
