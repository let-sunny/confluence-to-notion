# Architecture Overview

> **Status: TypeScript port in progress (#129).** The PR 1 scaffold lives at
> `src/cli.ts` / `src/mcp.ts` / `src/index.ts`. The modules listed below under
> `src/converter/`, `src/confluence/`, `src/notion/`, `src/runs/`, and
> `src/eval/` are placeholders filled in across PRs 2–5. See
> [ADR-00N](ADR-00N-port-to-typescript.md) for the port strategy and
> [ADR-00M](ADR-00M-cli-surface-freeze.md) for the frozen CLI surface PR 4
> targets.

## System Diagram

```mermaid
graph TD
    subgraph "Data Prep (TS CLI)"
        CF[Confluence REST API]
        FETCH["pnpm exec c2n fetch --pages ..."]
        SAMPLES[samples/*.xhtml]
    end

    subgraph "Orchestration (bash script)"
        SCRIPT[scripts/discover.sh]
    end

    subgraph "Agent Pipeline (independent claude -p sessions)"
        D["claude -p · pattern-discovery"]
        P["claude -p · rule-proposer"]
        C["claude -p · rule-critic"]
        A["claude -p · rule-arbitrator"]
    end

    subgraph "Output"
        R[output/rules.json]
        CV[Deterministic Converter]
        N[Notion API]
    end

    CF -->|REST API| FETCH
    FETCH --> SAMPLES

    SCRIPT -->|step 1| D
    SCRIPT -->|step 2| P
    SCRIPT -->|step 3| C
    SCRIPT -->|step 4| A

    SAMPLES --> D
    D -->|output/patterns.json| P
    P -->|output/proposals.json| C
    C -->|output/critiques.json| A
    A --> R

    R --> CV
    SAMPLES --> CV
    CV --> N
```

## Execution Model

Two runtime layers, each with a clear responsibility:

### 1. TypeScript CLI (`pnpm exec c2n ...`)

Handles I/O with external APIs. Deterministic, testable, typed.

- `fetch --pages <ids>` — download specific Confluence pages as XHTML
- `fetch --space <key>` — download pages from a space (paginated)
- `notion-ping` — validate Notion API token
- `convert` — apply `rules.json` to transform pages
- `migrate` / `migrate-tree` / `migrate-tree-pages` — publish to Notion

The frozen flag list is authoritative in
[ADR-00M](ADR-00M-cli-surface-freeze.md).

### 2. Bash script + `claude -p` (Agent Pipeline)

Handles LLM-powered reasoning. Each agent runs in **its own clean `claude -p` session**.

```bash
bash scripts/discover.sh samples/
```

Internally this runs:

```
Step 1: claude -p "..." (pattern-discovery)  → output/patterns.json
Step 2: claude -p "..." (rule-proposer)      → output/proposals.json
Step 3: claude -p "..." (rule-critic)        → output/critiques.json
Step 4: claude -p "..." (rule-arbitrator)    → output/rules.json
```

### Why script-based orchestration?

| | Delegated (Claude commands) | Explicit (bash script) |
|---|---|---|
| **Orchestrator** | Claude session (LLM judgment) | Bash script (deterministic code) |
| **Context** | Accumulates in one window | Clean per step |
| **Debugging** | Hard to trace where it broke | Step 3 fails → rerun step 3 |
| **Intermediate output** | In Claude's memory | Files on disk |
| **Retry** | Rerun entire pipeline | Rerun failed step only |
| **Flow changes** | Edit .md, hope Claude follows | Edit one line of bash |

The pipeline is **linear** (Discovery → Proposer → Critic → Arbitrator). No dynamic branching needed. A script is the right tool.

## Data Flow

1. **Fetch**: `c2n fetch --pages <ids>` downloads XHTML from Confluence → `samples/`
2. **Discovery**: `pattern-discovery` agent reads `samples/*.xhtml` → `output/patterns.json`
3. **Propose**: `rule-proposer` agent reads `output/patterns.json` → `output/proposals.json`
4. **Critique**: `rule-critic` validates against `samples/` → `output/critiques.json`
5. **Arbitrate**: `rule-arbitrator` resolves conflicts → `output/rules.json`
6. **Convert**: Deterministic converter applies `rules.json` to transform all pages → `output/runs/<slug>/converted/`
7. **Publish**: Converted Notion blocks pushed via the Notion API; run state recorded under `output/runs/<slug>/`

## Per-Run Artifact Layout

Every `convert` / `migrate` / `migrate-tree` / `migrate-tree-pages` invocation allocates a fresh run directory under `output/runs/<slug>/` (collisions get `-2`, `-3`, …). The slug is derived from the `--url` argument by `slugForUrl()`.

```
output/runs/<slug>/
├── source.json         # SourceInfo: url, type (page|tree|space|...), root_id, notion_target
├── status.json         # RunStatus: per-step StepRecord (fetch / discover / convert / migrate)
├── report.md           # Rendered by finalizeRun() from source.json + status.json
├── resolution.json     # page_link:<title> → notion_page_id (migrate-tree / migrate-tree-pages)
├── converted/          # <page_id>.json Notion-block payloads (convert / migrate-tree-pages)
├── samples/            # XHTML bodies fetched during migrate-tree-pages Pass 1.5
├── page-tree.json      # Confluence tree snapshot (migrate-tree-pages)
└── rules/
    └── table-rules.json  # Operator-classified table rules (migrate-tree-pages)
```

Contract highlights (see `src/runs/` after PR 3):

- **`source.json`** — persisted on first touch of a run via `startRun()`; carries the origin URL plus optional `root_id` and `notion_target`.
- **`status.json`** — one `StepRecord` per phase (`fetch`, `discover`, `convert`, `migrate`); each record tracks `status`, `at` (ISO-8601), and optional `count` / `warnings`. Mutated via `updateStep()`.
- **`report.md`** — rendered by `finalizeRun()` from the two files above. When a caller passes `rulesSummary`, an optional `## Rules usage` section is appended (sorted `- <rule_id>: <count>` lines).

Legacy repo-root sinks (`output/converted/`, `output/resolution.json`, `output/rules/table-rules.json`) are no longer written.

## Module Responsibility Map

| Location | Layer | Responsibility |
|---|---|---|
| `scripts/discover.sh` | Bash | Pipeline orchestration (flow control) |
| `.claude/agents/*.md` | Subagent | LLM-powered reasoning (one agent per file) |
| `output/*.json` | Data | Inter-agent communication (file-based) |
| `src/config.ts` | TypeScript | Environment-based configuration |
| `src/confluence/client.ts` | TypeScript | Confluence REST API client |
| `src/notion/client.ts` | TypeScript | Notion API wrapper |
| `src/cli.ts` | TypeScript | CLI entry points for data prep |
| `src/runs/` | TypeScript | Run directory layout, status/source schemas, report rendering |
| `src/converter/` | TypeScript | XHTML → Notion-block transform + zod schemas |
| `src/eval/` | TypeScript | Semantic coverage + baseline diff merge gate |
| `src/mcp.ts` | TypeScript | Stdio MCP server (`c2n-mcp` bin) |

> The TS modules above are filled in across PRs 2–5; only `src/cli.ts`, `src/mcp.ts`, and `src/index.ts` exist in the PR 1 scaffold.

## Key Design Decisions

- **Script-based orchestration**: Deterministic, debuggable, step-level retry. Each `claude -p` gets a clean context.
- **File-based communication**: Agents read/write JSON. Simple, inspectable, versionable.
- **zod as contract**: JSON schemas define what agents must produce. TypeScript validates; agents generate.
- **undici / native fetch for Confluence**: Direct REST for pagination, auth, async control.
- **TypeScript for I/O only**: `src/` handles API calls and deterministic conversion. LLM reasoning stays in subagents.

See [ADR.md](ADR.md) for architecture decision records.
