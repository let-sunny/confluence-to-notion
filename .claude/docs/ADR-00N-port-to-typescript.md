# ADR-00N: Port to TypeScript

**Status**: Accepted (2026-04-24)
**Supersedes**: none
**Related**: [ADR-00M — CLI surface freeze](./ADR-00M-cli-surface-freeze.md)

## Decision

Replace the Python runtime of `confluence-to-notion` with an idiomatic
TypeScript / Node implementation on the `main` branch. The rewrite is staged
across five PRs (#129 is 1/5):

1. Scaffold + ADRs + docs (this PR).
2. Port the deterministic converter literally against golden-fixture
   equivalence.
3. Port the Confluence / Notion I/O adapters + run directory layout.
4. Rewrite the CLI against the frozen surface captured in ADR-00M and retarget
   `scripts/*.sh` + `.claude/agents/**/*.md` to `pnpm exec c2n …`.
5. Initialise changesets, publish `confluence-to-notion@0.1.0` to npm, flip the
   `release.yml` workflow on.

### Port strategy — hybrid

- **Converter** (`src/converter/` after PR 2): ported literally. The XHTML →
  Notion-block transform is the correctness surface users depend on; we
  preserve semantics via golden-fixture equivalence against `samples/*.xhtml`
  and the `output/converted/` snapshots already checked into the repo.
- **Everything else** (CLI, Confluence/Notion adapters, run directory, eval,
  MCP server): rewritten idiomatically for Node. No 1:1 transliteration — we
  take the freedom to use ESM modules, tagged-template schema helpers, and
  native `fetch`/`undici` instead of shimming Python idioms.

### Toolchain (pinned)

| Concern | Choice |
|---|---|
| Runtime | Node 20 LTS |
| Module system | ESM (`"type": "module"`) |
| Language | TypeScript 5 (strict + `noUncheckedIndexedAccess`) |
| Bundler | tsup (dual-entry: `cli`, `mcp`) |
| Test runner | vitest (+ `@vitest/coverage-v8`) |
| Lint + format | biome |
| CLI | commander |
| Schema validation | zod |
| XHTML parsing | parse5 (XML mode) |
| HTTP | undici / global `fetch` |
| Notion SDK | `@notionhq/client` |
| Anthropic SDK | `@anthropic-ai/sdk` |
| MCP SDK | `@modelcontextprotocol/sdk` |
| Package manager | pnpm |
| Release | changesets (provenance on) |

PR 1 lands pnpm + TypeScript + tsup + vitest + biome + commander. The other
runtime deps land in the PR that first needs them (zod in PR 2, parse5 in PR 2,
`@notionhq/client` in PR 3, etc.).

### Package name

- **Primary**: `confluence-to-notion` (unscoped on npm). Chosen over a scope so
  the install command matches the repo name exactly:
  `npm i -g confluence-to-notion`.
- **Fallback**: `@let-sunny/confluence-to-notion`, used only if the unscoped
  name is squatted before PR 5 ships. The fallback is already the git user's
  GitHub handle, so provenance lines up either way.
- `package.json > name` is set in PR 1 (this one) so the manifest is stable
  long before publish; we do not claim the name on npm until PR 5.

### Binaries

Two CLI entry points, both registered in `package.json > bin`:

- `c2n` → `./dist/cli.js` — user-facing command.
- `c2n-mcp` → `./dist/mcp.js` — stdio MCP server (stubbed in PR 1, filled in
  during PRs 3–5).

`tsup.config.ts` declares both as separate entries so the bundler shebangs them
correctly.

### Repo cutover strategy

- **In-place replacement on `main`.** No `python-archive` tag, no parallel
  branch. The Python history is reachable through git blame / `git log -- src/confluence_to_notion/`;
  anyone who needs the Python variant can check out `main~<n>` directly.
- `samples/` XHTML fixtures stay put through the whole series — PR 2 uses them
  to prove the converter port is equivalence-correct.
- `.claude/agents/**/*.md`, `.claude/rules/*.md`, and `scripts/*.sh` stay
  language-neutral until PR 4 retargets them. ADR-00N is load-bearing here: the
  agents do not assume the runtime language.

## Why

1. **Distribution reach.** The primary install target is `npm i -g c2n` plus
   stdio MCP servers that Claude Code launches with `npx`; both are first-class
   in the Node ecosystem and second-class in Python (`uvx` works but requires
   uv). Meeting users where they are reduces install friction to zero.
2. **MCP ergonomics.** Claude Code MCP servers are overwhelmingly Node — the
   official SDK, the worked examples, and the client integrations all favour
   TypeScript. Staying on Python locks us out of the idiomatic ecosystem.
3. **Owner preference.** The maintainer's daily language is TypeScript; the
   Python implementation was scaffolded to validate the agent pipeline, not as
   a long-term runtime choice.
4. **Converter is the only thing that has to be literal.** The rest is I/O +
   orchestration, where idiomatic Node is a drop-in. Porting literally
   everywhere would drag Python idioms into a TS codebase for no benefit.

## Impact

- PR 1 leaves the repo in a temporarily-inert state: `pnpm install && pnpm build && pnpm test && pnpm lint && pnpm typecheck` pass, but the CLI only answers `--version` / `--help`. The Python runtime is gone. Users cannot migrate until PR 5 publishes — this is documented as a WIP banner on the README and flagged in `CHANGELOG.md`.
- ADR-00M freezes the CLI surface so PR 4 has an authoritative target; any drift fails CI.
- `.github/workflows/ci.yml` (PR 1) runs only `pnpm` jobs. `scripts/*.sh` are excluded from CI until PR 4 retargets them — running them against a `pnpm exec c2n` that does not yet have subcommands would guarantee red builds.
- The release workflow (`release.yml`) ships inert in PR 1: changesets is a no-op when no changeset files exist, so the workflow runs green but publishes nothing until PR 5 initialises it.
- Documentation (`README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.claude/docs/architecture.md`) is rewritten in PR 1 to describe the TS toolchain. Korean prose that was load-bearing (CONTRIBUTING.md in particular) is translated to English per `CLAUDE.md > Language`.
- `pyproject.toml`, `uv.lock`, `.python-version`, and `tests/` are deleted. `samples/` is kept (PR 2 needs it). `output/` is kept — the `output/converted/` snapshots are fixtures for the converter port.
