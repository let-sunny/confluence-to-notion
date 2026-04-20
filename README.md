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
레포 루트에 `.mcp.json` 을 두고 아래 스니펫을 추가하면 로컬 세션에서 바로 연결된다.

`c2n-mcp` 는 `uv run c2n …` / `discover.sh` 자식 프로세스를 **항상 레포 루트를 `cwd` 로**
실행한다(JSON-RPC용 stdout 에 Rich/쉘 로그가 섞이지 않도록, 자식 stdout/stderr 는 캡처).
클라이언트 cwd 와 무관하게 `output/`, `samples/` 등은 레포 기준 경로로 해석된다.

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

### Tools (요약)

| Tool | 역할 |
|------|------|
| `c2n_list_runs` | `output/runs/` 아래 런 요약 |
| `c2n_status` | 특정 slug의 `status.json` (또는 slug 생략 시 목록) |
| `c2n_resolve_url` | Confluence URL → `source_type` / `identifier` |
| `c2n_migrate` | `uv run c2n migrate <url>` 서브프로세스(MCP stdio 보호). 선택 인자: `to`(Notion 부모 URL·page id), `name`(런 슬러그), `rediscover`, `dry_run`. 성공 시 `{returncode, stdout}` |
| `c2n_fetch` | `uv run c2n fetch` (`space` 또는 `pages`, 선택 `url`) → `{returncode, stdout}` |
| `c2n_discover` | `bash scripts/discover.sh <samples> --url <url>` → `{returncode, stdout}` |
| `c2n_convert` | `uv run c2n convert --rules … --input … --url …` → `{returncode, stdout}` |
| `c2n_push` | `uv run c2n migrate --url … --rules … --input … --target …` (레거시 배치) → `{returncode, stdout}` |

### Resources

- `c2n://runs`, `c2n://runs/<slug>/status|report|converted/<page>`, `c2n://rules`

### 예제 워크플로우 (Claude Code)

1. `.env` 를 채우고 `uv sync` 로 의존성을 맞춘다.
2. MCP 패널에서 `c2n_resolve_url` 로 붙여넣은 Confluence URL 분류를 확인한다.
3. `c2n_migrate` 에 같은 URL을 넘겨 한 번에 fetch → discover(필요 시) → convert → Notion 까지 돌린다 (`dry_run: true` 로 먼저 아티팩트만 확인할 수 있다).
4. `c2n_list_runs` 로 방금 생긴 런의 **slug** 를 확인한 뒤, `c2n_status(slug=…)` 또는 `c2n://runs/<slug>/report` 리소스로 상태·리포트를 읽는다. (도구 응답은 `{returncode, stdout}` 이므로 slug는 목록/리소스에서 회수한다.)

저수준 단계만 쪼개서 돌리려면 `c2n_fetch` → `c2n_discover` → `c2n_convert` → `c2n_push` 순으로 호출하면 CLI와 동일한 파이프라인을 재구성할 수 있다.

### 수동 검증 (PR 시 기재)

Claude Code 에서 stdio MCP 연결 후, 위 예제 중 **한 페이지 URL**에 대해 `c2n_migrate`(또는 `dry_run` → 실제 push)가 끝까지 성공하는지, 그리고 `c2n_status` / `c2n://…/report` 로 해당 런이 보이는지 확인한다. 실패 시 MCP 에러 메시지와 `output/runs/<slug>/report.md` 를 함께 첨부한다.

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
