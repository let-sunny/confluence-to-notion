# Slack · OpenClaw · confluence-to-notion bridge — agent handoff

This note is for internal agent / implementation teams wiring **chat-driven rule
updates + Confluence → Notion migration**. The repository (`confluence-to-notion`,
**c2n**) supplies the **migration engine and MCP**; the **Slack conversation →
rules JSON** bridge is built **outside** this repo.

---

## 1. Target user flow (intent)

1. Users ask for review, clarification, or policy in **Slack** (or any channel
   OpenClaw is connected to).
2. **OpenClaw** handles the thread and, when needed, runs the next steps (write
   files, shell, MCP calls).
3. Requirements distilled from chat feed into **migration rules** (artifacts
   that become `rules.json`).
4. The same rules drive **internal Confluence → Notion** conversion.
5. The ideal is **“I only replied in chat and Notion is already updated,”** but
   for security and quality, **`dry_run` plus a human approval step** is the
   realistic default.

---

## 2. What this repo does / does not do

### 2.1 What this repo provides

- **stdio MCP server** `c2n-mcp`: tools such as `c2n_resolve_url`, `c2n_migrate`,
  `c2n_discover`, `c2n_fetch`, `c2n_convert`, `c2n_list_runs`, `c2n_status` (see
  README **MCP** section).
- **CLI**: `uv run c2n …` — `finalize`, `migrate`, `convert`, `validate-output`, etc.
- **Rule materialization**: `uv run c2n finalize output/proposals.json` →
  `rules.json` (plus validation paths).
- **Migration**: Notion updates from a Confluence URL + `rules.json`.

### 2.2 What this repo does not provide out of the box

- There is **no** pipeline that builds `rules.json` **from Slack thread text alone**.
- **Discover** (automatic rule discovery) is driven by **Confluence samples /
  XHTML** and `scripts/discover.sh`; it does **not** take chat logs as input.

So **“conversation → rules”** is the **bridge** (your code or OpenClaw skills).

---

## 3. Discover and Claude Code CLI (important)

- `scripts/discover.sh` runs **`claude -p` (Claude Code CLI)** as a subprocess.
- That is **separate** from whichever chat LLM OpenClaw uses (e.g. GPT). To run
  discover, the host needs the **`claude` CLI installed and signed in**.
- If **`output/rules.json` already exists** and you only migrate, you can often
  run convert/migrate **without** Claude CLI at runtime when you are not using
  `--rediscover`.

**Bridge design options**

| Strategy | Description |
|----------|-------------|
| A. Conversation-only rules | Author `proposals.json` with an LLM or editor → `finalize` → `migrate`. Discover may be skipped (schema and quality are on your team). |
| B. Combine with discover | Run `discover.sh` on Confluence samples → `rules.json`, plus **merge policy** with bridge-produced proposals if needed. |

---

## 4. OpenClaw and MCP (concept)

- Register the stdio server under **`mcp.servers`** in OpenClaw config.
- **`cwd` (or `workingDirectory`) must be this repository’s root** — `c2n-mcp`
  runs child processes from the repo root (see README MCP section).
- Example shape (exact keys depend on your OpenClaw version):

```json
{
  "mcp": {
    "servers": {
      "c2n": {
        "command": "uv",
        "args": ["run", "c2n-mcp"],
        "cwd": "C:\\path\\to\\confluence-to-notion"
      }
    }
  }
}
```

- Place **`.env`** at the repo root (Confluence / Notion credentials, etc.).

---

## 5. Windows + security posture (native Windows, no WSL)

- **Discover** needs **`bash scripts/discover.sh`** → **Bash** must be available.
- Use **Git for Windows (Git Bash)** or another approved Bash where `bash` is on
  `PATH`.
- Prefer repo paths **without spaces or non-ASCII** characters.
- Run OpenClaw, Claude Code CLI, and `uv` on the **same machine** and align MCP
  `cwd` with that layout.

---

## 6. MVP bridge — minimal changes to this repo

You can ship a first version **without forking c2n**:

1. The bridge writes **`output/proposals.json`** (valid schema) from chat /
   approval.
2. `uv run c2n finalize output/proposals.json` → **`rules.json`**.
3. Validate with `uv run c2n validate-output …` (see CLI / README).
4. `uv run c2n migrate --url …` or MCP `c2n_migrate` to push to Notion (prefer
   `dry_run` first).

Optional later improvements: MCP tools that accept proposal payloads inline,
subcommands to merge or repair proposals, code-level merge rules with discover
output, etc.

---

## 7. Operational guardrails

- Chat-derived rule JSON will **not** always validate → retry loops and human
  review on schema failure.
- **Which Confluence URLs or scopes** to migrate stay ambiguous if only inferred
  from chat → keep explicit URL lists, spaces, or an approval step.
- Scope **secrets and logging** so sensitive data does not leak to LLMs or logs
  against company policy.

---

## 8. Glossary

| Term | Meaning |
|------|---------|
| OpenClaw | Agent runtime for individuals or teams (same family of projects formerly known as Moltbot, etc.). Extends with channels, MCP, and skills. |
| c2n / confluence-to-notion | This repository: Confluence XHTML → Notion block rules, conversion, MCP. |
| Discover | Rule proposal pipeline: `discover.sh` + Claude Code CLI. |
| Bridge | Your orchestration layer: **Slack/OpenClaw ↔ proposals / finalize / migrate**. |

---

## 9. References inside the repo

- `README.md` — MCP setup, CLI, workflows.
- `CLAUDE.md` — agents, discover, eval policy.
- `scripts/discover.sh` — `claude -p` invocation.

---

*This document is a handoff summary. Prefer the latest README and `uv run c2n --help` when implementing.*
