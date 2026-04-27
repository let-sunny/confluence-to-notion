---
"confluence-to-notion": minor
---

Add `c2n init` and profile-based credential storage.

- New `c2n init` interactive setup that writes Confluence + Notion credentials to a per-user config file (no more re-exporting env vars in every shell).
- New `c2n auth confluence` / `c2n auth notion` for updating one side of an existing profile.
- Named profiles via `--profile <name>` and `C2N_PROFILE`, plus `c2n profiles list` and `c2n use <name>` for inspection and switching.
- Profile-aware credential resolution wired through every data-prep subcommand: `fetch`, `fetch-tree`, `notion-ping`, `convert`, `migrate`, `migrate-tree`, and `migrate-tree-pages`.
- The MCP server (`c2n-mcp` / `src/mcp/server.ts`) now reads credentials through the same profile store, so the `env:` block in `claude_desktop_config.json` becomes optional once `c2n init` has been run.

See [ADR-00M](./.claude/docs/ADR-00M-cli-surface-freeze.md) for the authoritative spec.
