# confluence-to-notion

Auto-discover Confluence → Notion transformation rules using a multi-agent
pipeline powered by Claude. Instead of hand-coding migration rules for every
Confluence macro and layout pattern, this tool analyzes your wiki pages and
derives the rules for you.

## Why

Migrating a Confluence wiki to Notion is painful. Confluence stores content as
XHTML with proprietary macros; Notion uses a block-based model. Existing tools
either lose structure or require extensive manual mapping. This project uses
Claude to automatically discover patterns in your Confluence pages and generate
transformation rules, which are then applied deterministically for reproducible
migrations.

## Status

Day 1 of active development — project harness and I/O connectivity established.
Remove this section before public release.

## Quickstart

```bash
git clone https://github.com/<your-org>/confluence-to-notion.git
cd confluence-to-notion
cp .env.example .env
# Fill in your API credentials in .env
uv sync
uv run cli notion-ping
```

## Roadmap

- [x] Day 1: Project harness, config, Confluence/Notion clients, CLI skeleton
- [ ] Day 2: Pattern Discovery Agent + Rule Proposer Agent
- [ ] Day 3: Rule Critic + Arbitrator Agents, deterministic converter
- [ ] Day 4: End-to-end pipeline, eval framework
- [ ] Day 5: Polish, docs, edge cases, release prep

## Development

```bash
uv sync                          # Install dependencies
uv run pytest                    # Run tests
uv run ruff check src/ tests/    # Lint
uv run mypy src/                 # Type check
uv run cli --help                # CLI usage
```

## License

MIT
