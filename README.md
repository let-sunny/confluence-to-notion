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
- Claude Code CLI (`claude`) — required to run the discovery agents (`claude -p`)
- A Notion integration token with access to a target parent page
- For private Confluence Cloud: Atlassian email + API token.
  Public wikis (e.g. `cwiki.apache.org`) need only the base URL.
- **Windows:** `scripts/discover.sh` requires **Bash** (e.g. Git Bash). Run MCP and
  CLI from an environment where `bash`, `uv`, and `claude` are on `PATH`.

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

A full migration moves through the stages below. Stages 1–2 pull wiki data and
run agents; stage 3 turns proposals into `rules.json`; stage 4 converts XHTML
offline; stage 5 publishes to Notion (often wrapped in a single `migrate`
command).

| Stage        | What happens                                              | Produces                                                |
|--------------|-----------------------------------------------------------|---------------------------------------------------------|
| 1. fetch     | Pull Confluence XHTML (and optionally the tree).          | `samples/*.xhtml`, `output/page-tree.json`              |
| 2. discover  | Claude agents emit patterns and proposed rules.           | `output/patterns.json`, `output/proposals.json`         |
| 3. finalize  | Deterministic step: proposals → migration rules.          | `output/rules.json`                                     |
| 4. convert   | Deterministic converter maps XHTML → Notion block JSON.     | `output/runs/<slug>/converted/*.json`                   |
| 5. migrate   | Create or update Notion pages and upload bodies.          | Pages under `NOTION_ROOT_PAGE_ID`                       |

The discovery path is orchestrated by **`bash scripts/discover.sh`**, not by a
Claude slash command — each agent runs as an independent `claude -p` session
and communicates via files on disk. The script runs finalize (step 3) and
convert (step 4) after the agents finish.

If `output/rules.json` already exists, you can skip re-discovery and run
convert/migrate only (see `--rediscover` on `migrate`).

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
everything under `output/runs/<slug>/` (`source.json`, `status.json`, `report.md`,
`converted/`, `resolution.json` for trees).

### Low-level escape hatch

The individual stages are still available for advanced workflows (inspecting
intermediate artifacts, re-running a single step, wiring into CI):

```bash
# Fetch-only
uv run c2n fetch --space KAFKA --limit 25
uv run c2n fetch --pages 27846297,27838103

# Run just the discover pipeline (agents + finalize + convert)
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

## MCP (Claude Code, OpenClaw, other clients)

The repo ships a **stdio MCP server** entrypoint: `c2n-mcp` (via `uv run c2n-mcp`).

- **Child processes** (`uv run c2n …`, `discover.sh`) always run with the **repository root as the working directory**, so `output/`, `samples/`, and `.env` resolve correctly regardless of the MCP client’s cwd. Rich and shell logs from children are captured so they do not corrupt JSON-RPC on stdout.
- **Claude Code:** add a `.mcp.json` at the repo root:

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

- **OpenClaw** (and similar gateways): register the same command in your MCP
  registry, and set **`cwd` / `workingDirectory` to this repo’s absolute path**
  if the client does not implicitly use the project folder. Example shape (see
  your OpenClaw version for exact keys):

```json
{
  "mcp": {
    "servers": {
      "c2n": {
        "command": "uv",
        "args": ["run", "c2n-mcp"],
        "cwd": "/absolute/path/to/confluence-to-notion"
      }
    }
  }
}
```

For **Slack / chat–driven orchestration** and custom bridges (proposals from
outside the default discover flow), see `docs/slack-openclaw-c2n-bridge.md`.

### Tools (summary)

| Tool | Role |
|------|------|
| `c2n_list_runs` | Summarize runs under `output/runs/` |
| `c2n_status` | Read `status.json` for a slug (or list when slug omitted) |
| `c2n_resolve_url` | Confluence URL → `source_type` / `identifier` |
| `c2n_migrate` | Runs `uv run c2n migrate <url>` in a subprocess (stdio-safe). Optional: `to` (Notion parent URL or page id), `name` (run slug), `rediscover`, `dry_run`. Returns `{returncode, stdout}` on success |
| `c2n_fetch` | `uv run c2n fetch` (`space` or `pages`, optional `url`) → `{returncode, stdout}` |
| `c2n_discover` | `bash scripts/discover.sh <samples> --url <url>` → `{returncode, stdout}` |
| `c2n_convert` | `uv run c2n convert --rules … --input … --url …` → `{returncode, stdout}` |
| `c2n_push` | Legacy batch form: `uv run c2n migrate --url … --rules … --input … --target …` → `{returncode, stdout}` |

### Resources

- `c2n://runs`, `c2n://runs/<slug>/status|report|converted/<page>`, `c2n://rules`

### Example workflow (MCP client)

1. Fill `.env` and run `uv sync`.
2. Call `c2n_resolve_url` with a Confluence URL to see how it is classified.
3. Call `c2n_migrate` with the same URL to run fetch → discover (if needed) → convert → Notion. Use `dry_run: true` first to inspect artifacts only.
4. Use `c2n_list_runs` to get the run **slug**, then `c2n_status(slug=…)` or the `c2n://runs/<slug>/report` resource. Tool responses are `{returncode, stdout}`; recover the slug from list/resources.

To mirror the CLI pipeline step by step: `c2n_fetch` → `c2n_discover` → `c2n_convert` → `c2n_push`.

### Manual verification (for PRs)

With stdio MCP connected, confirm that for **one page URL**, `c2n_migrate` (or
`dry_run` then a real push) completes, and that `c2n_status` / `c2n://…/report`
shows the run. On failure, attach the MCP error and `output/runs/<slug>/report.md`.

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
