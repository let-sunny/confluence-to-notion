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
uv run c2n notion-ping
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

One command does the whole thing — fetch, discover rules (if needed), convert,
and publish to Notion. Pass any Confluence URL (single page or space root):

```bash
# Single page
uv run c2n migrate https://cwiki.apache.org/confluence/display/KAFKA/Home

# Entire space (recursive, preserves hierarchy)
uv run c2n migrate https://cwiki.apache.org/confluence/spaces/KAFKA

# Override the Notion parent (URL or raw page id)
uv run c2n migrate <confluence-url> --to https://notion.so/My-Target-abc123...

# Fetch + convert only, no Notion writes — inspect output/runs/<slug>/ first
uv run c2n migrate <confluence-url> --dry-run

# Force re-discovering rules instead of reusing output/rules.json
uv run c2n migrate <confluence-url> --rediscover
```

`c2n migrate` classifies the URL (new-Cloud `/spaces/<KEY>/pages/<id>/...`,
legacy `/display/<SPACE>/<Title>`, or space-root `/spaces/<KEY>`), runs
`scripts/discover.sh` if `output/rules.json` is missing, converts, and publishes
everything under `output/runs/<slug>/` (source.json, status.json, report.md,
converted/, resolution.json for trees).

### Low-level escape hatch

The individual stages are still available for advanced workflows (inspecting
intermediate artifacts, re-running a single step, wiring into CI):

```bash
# Fetch-only
uv run c2n fetch --space KAFKA --limit 25
uv run c2n fetch --pages 27846297,27838103

# Run just the discover pipeline
bash scripts/discover.sh samples/ --url <confluence-url>

# Finalize + convert offline
uv run c2n finalize output/proposals.json
uv run c2n convert --rules output/rules.json --input samples/ --url <confluence-url>

# Publish with the legacy migrate form (takes --rules/--input/--target)
uv run c2n migrate --url <confluence-url> --rules output/rules.json --input samples/

# 2-pass tree migration (create empty pages, then upload bodies)
uv run c2n fetch-tree --url <confluence-url> --root-id 27846297
uv run c2n migrate-tree-pages --url <confluence-url> --root-id 27846297 --rules output/rules.json
```

`migrate-tree-pages` persists a `title → notion_page_id` map to
`output/runs/<slug>/resolution.json`, which the converter uses to turn
Confluence internal links into Notion page mentions.

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

Run `uv run c2n <command> --help` for the full option list.

## MCP 설치

`c2n` 는 stdio transport 기반 MCP 서버(`c2n-mcp`) 를 번들한다. Claude Code 에서
`.mcp.json` 을 레포 루트에 두고 아래 스니펫을 추가하면 로컬 세션에서 바로 연결된다.

```json
{
  "mcpServers": {
    "c2n": {
      "command": "uv",
      "args": ["run", "c2n-mcp"]
    }
  }
}
```

현재 read-only 범위:

- Tools: `c2n_list_runs`, `c2n_status`, `c2n_resolve_url`
- Resources: `c2n://runs`, `c2n://runs/<slug>/status|report|converted/<page>`,
  `c2n://rules`

Write-side tool (`c2n_migrate`) 와 low-level tools (`c2n_fetch` / `c2n_discover` /
`c2n_convert` / `c2n_push`) 는 후속 이슈에서 추가 예정이다.

## Development

```bash
uv sync                          # Install dependencies
uv run pytest                    # Run tests
uv run ruff check src/ tests/    # Lint
uv run mypy src/                 # Type check (strict on src/)
uv run c2n --help                # CLI usage
bash scripts/run-eval.sh         # Agent output eval pipeline
```

See `CLAUDE.md` and `.claude/rules/*.md` for project conventions, agent
orchestration rules, and prompt-management guidelines.

## License

MIT
