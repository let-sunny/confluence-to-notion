# confluence-to-notion

Auto-discover Confluence → Notion transformation rules using a multi-agent
pipeline powered by Claude. Instead of hand-coding migration rules for every
Confluence macro and layout pattern, this tool analyzes your wiki pages and
derives the rules for you.

## Why

Migrating a Confluence wiki to Notion is painful. Confluence stores content as
XHTML with proprietary macros; Notion uses a block-based model. Existing tools
either lose structure or require extensive manual mapping. This project uses
Claude to discover patterns in your Confluence pages, proposes transformation
rules, and then applies them deterministically so the same wiki always migrates
the same way.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Claude Code CLI (`claude`) — required to run the discovery agents
- A Notion integration token with access to a target parent page
- For private Confluence Cloud: Atlassian email + API token.
  Public wikis (e.g. `cwiki.apache.org`) need only the base URL.

## Setup

```bash
git clone https://github.com/<your-org>/confluence-to-notion.git
cd confluence-to-notion
uv sync
cp .env.example .env
```

Edit `.env`:

```dotenv
# Confluence — public wikis need only the base URL
CONFLUENCE_BASE_URL=https://cwiki.apache.org/confluence
# CONFLUENCE_EMAIL=you@example.com          # private Cloud only
# CONFLUENCE_API_TOKEN=xxxxxxxxxxxxxxxx     # private Cloud only
# CONFLUENCE_API_PATH=/rest/api             # override for self-hosted

# Notion
NOTION_API_TOKEN=ntn_xxxxxxxxxxxxxxxxxxxx
NOTION_ROOT_PAGE_ID=your-notion-parent-page-id
```

Verify the Notion token is valid:

```bash
uv run cli notion-ping
```

## Pipeline stages

A migration flows through four stages. Stages 1–2 populate local files from
your wiki and derive rules; stage 3 turns XHTML into Notion blocks; stage 4
pushes the result to Notion.

| Stage      | What happens                                       | Produces                                         |
|------------|----------------------------------------------------|--------------------------------------------------|
| 1. fetch   | Pull Confluence XHTML (and optionally the tree).   | `samples/*.xhtml`, `output/page-tree.json`       |
| 2. discover| Claude agents propose transformation rules.        | `output/patterns.json`, `output/proposals.json`  |
| 3. convert | Deterministic converter maps XHTML → Notion blocks.| `output/rules.json`, `output/converted/*.json`   |
| 4. migrate | Create Notion pages and upload converted bodies.   | Pages under `NOTION_ROOT_PAGE_ID`                |

The discovery stage is orchestrated by a bash script, not by a Claude command —
each agent runs as an independent `claude -p` session and communicates via
files on disk.

## Migration walkthrough (Apache cwiki → Notion)

The example below migrates a subtree of `cwiki.apache.org` rooted at a known
page ID. Swap the ID and Notion target for your own.

### 1. Fetch representative samples for rule discovery

```bash
# Fetch a handful of pages from a space to let the agents see real content
uv run cli fetch --space KAFKA --limit 25

# Or fetch specific page IDs
uv run cli fetch --pages 27846297,27838103
```

### 2. Discover transformation rules

```bash
bash scripts/discover.sh samples/ --url https://cwiki.apache.org/confluence/display/KAFKA/Home
```

This runs the 2-agent pipeline (pattern-discovery → rule-proposer) and writes
`output/patterns.json` and `output/proposals.json`, then runs `finalize` +
`convert` (step 4 lands converted JSON under `output/runs/<slug>/converted/`
— the slug is derived from `--url`). Resume a specific step with `--from N`.

### 3. Finalize rules and convert offline

```bash
uv run cli finalize output/proposals.json
uv run cli convert --rules output/rules.json --input samples/ --url <confluence-url>
```

Converted JSON lands in `output/runs/<slug>/converted/`. Inspect it before
pushing anything to Notion.

### 4. Migrate to Notion

For a flat set of pages:

```bash
uv run cli migrate --rules output/rules.json --input samples/
# --target <page-id> overrides NOTION_ROOT_PAGE_ID
```

For a full subtree with internal links preserved (2-pass: create empty pages
first, then upload bodies so `[[page-link]]` resolves to Notion mentions):

```bash
uv run cli fetch-tree --root-id 27846297 --output output/page-tree.json
uv run cli migrate-tree-pages --root-id 27846297 --rules output/rules.json
```

`migrate-tree-pages` persists a `title → notion_page_id` map to
`output/resolution.json`, which the converter uses to turn Confluence internal
links into Notion page mentions.

## CLI reference

```text
fetch               Fetch Confluence pages and save XHTML to disk
fetch-tree          Fetch the Confluence page tree from a root page ID
notion-ping         Validate the Notion API token
discover            Reminder to run bash scripts/discover.sh
finalize            proposals.json → rules.json
convert             XHTML → Notion blocks (offline)
migrate             Convert and publish to Notion
migrate-tree        Create an empty Notion hierarchy mirroring a Confluence tree
migrate-tree-pages  Full 2-pass tree migration (create, then upload)
validate-output     Validate an agent output file against its Pydantic schema
```

Run `uv run cli <command> --help` for the full option list.

## Development

```bash
uv sync                          # Install dependencies
uv run pytest                    # Run tests
uv run ruff check src/ tests/    # Lint
uv run mypy src/                 # Type check (strict on src/)
uv run cli --help                # CLI usage
bash scripts/run-eval.sh         # Agent output eval pipeline
```

See `CLAUDE.md` and `.claude/rules/*.md` for project conventions, agent
orchestration rules, and prompt-management guidelines.

## License

MIT
