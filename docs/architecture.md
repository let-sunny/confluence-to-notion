# Architecture Overview

## System Diagram

```mermaid
graph TD
    subgraph "Data Prep (Python CLI)"
        CF[Confluence REST API]
        FETCH["cli fetch --pages ..."]
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

### 1. Python CLI (`uv run cli ...`)

Handles I/O with external APIs. Deterministic, testable, typed.

- `fetch --pages <ids>` — download specific Confluence pages as XHTML
- `fetch --space <key>` — download pages from a space (paginated)
- `notion-ping` — validate Notion API token
- `convert` (future) — apply rules.json to transform pages
- `publish` (future) — push converted pages to Notion

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

1. **Fetch**: `cli fetch --pages <ids>` downloads XHTML from Confluence → `samples/`
2. **Discovery**: `pattern-discovery` agent reads `samples/*.xhtml` → `output/patterns.json`
3. **Propose**: `rule-proposer` agent reads `output/patterns.json` → `output/proposals.json`
4. **Critique**: `rule-critic` validates against `samples/` → `output/critiques.json`
5. **Arbitrate**: `rule-arbitrator` resolves conflicts → `output/rules.json`
6. **Convert**: Deterministic converter applies `rules.json` to transform all pages
7. **Publish**: Converted Notion blocks pushed via the Notion API

## Module Responsibility Map

| Location | Layer | Responsibility |
|---|---|---|
| `scripts/discover.sh` | Bash | Pipeline orchestration (flow control) |
| `.claude/agents/*.md` | Subagent | LLM-powered reasoning (one agent per file) |
| `output/*.json` | Data | Inter-agent communication (file-based) |
| `src/config.py` | Python | Environment-based configuration |
| `src/confluence/client.py` | Python | Async Confluence REST API client |
| `src/notion/client.py` | Python | Async Notion API wrapper |
| `src/cli.py` | Python | CLI entry points for data prep |
| `src/**/schemas.py` | Python | Pydantic models = contracts for agent I/O |

## Key Design Decisions

- **Script-based orchestration**: Deterministic, debuggable, step-level retry. Each `claude -p` gets a clean context.
- **File-based communication**: Agents read/write JSON. Simple, inspectable, versionable.
- **Pydantic as contract**: JSON schemas define what agents must produce. Python validates; agents generate.
- **httpx for Confluence**: Direct REST for pagination, auth, async control.
- **Python for I/O only**: `src/` handles API calls and deterministic conversion. LLM reasoning stays in subagents.

See [ADR-001](adr/001-multi-agent-pattern.md) for the multi-agent pipeline decision.
