# OpenClaw · confluence-to-notion bridge — agent handoff

This note is for internal agent / implementation teams wiring **chat-driven
Confluence → Notion migration** through OpenClaw. The repository
(`confluence-to-notion`, **c2n**) supplies the **read-mostly migration
engine and MCP server**; OpenClaw supplies the **channel routing, runtime,
and approval plumbing** that surfaces those tools inside whichever chat
surface a team already uses (Slack, Telegram, iMessage, Discord, WhatsApp,
Microsoft Teams, Matrix, Google Chat, …). Notion writes themselves run
through the host runtime's Notion MCP — see ADR-007.

The shorthand "Slack bridge" in earlier drafts is misleading: OpenClaw is
multi-channel, and the integration described below is identical regardless of
which channel a user types into. Anywhere this doc says "chat", read it as
"any OpenClaw-routed conversation".

> Versions referenced: `confluence-to-notion@0.1.3` (npm) and OpenClaw
> `mcp.servers` config shape as documented at
> `openclaw/openclaw → docs/cli/mcp.md`.

---

## 1. Target user flow (intent)

1. A user asks for review, clarification, migration, or status in **any
   channel OpenClaw routes**.
2. **OpenClaw** receives the message, picks the appropriate runtime/agent, and
   exposes c2n tools to that runtime via its **`mcp.servers`** registry.
3. The runtime calls c2n MCP tools to **fetch Confluence XHTML, convert it
   to Notion blocks, list/inspect prior runs, list unresolved questions,
   append rule proposals, finalize the ruleset, or record a Notion page id
   produced by the host's Notion MCP**.
4. Results flow back through OpenClaw to the originating channel — usually as
   a preview first, then a write through the host's Notion MCP after
   explicit approval.
5. The ideal is **"I only replied in chat and Notion is already updated."**
   In practice, **read-only previews + explicit approval before the host
   Notion MCP `create_page` / `append_blocks` runs** is the realistic
   default for compliance and quality.

---

## 2. What this repo does / does not do

### 2.1 What this repo provides

- **stdio MCP server** `c2n-mcp` (`src/mcp/index.ts`). The exact tool surface
  is pinned by `tests/fixtures/mcp/tools-list.json`:

  | Tool                       | Type      | Required input                                                                                                                          | Notes                                                                                                                                                  |
  | -------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
  | `c2n_fetch_page`           | read      | `pageIdOrUrl`                                                                                                                           | Optional `baseUrl` overrides `CONFLUENCE_BASE_URL`. Display URLs are rejected.                                                                          |
  | `c2n_convert_page`         | read      | `xhtml`                                                                                                                                 | Returns `{ blocks, unresolved, usedRules }`. Optional `pageId`, `title`.                                                                                |
  | `c2n_list_runs`            | read      | _(none)_                                                                                                                                | Lists slugs under `<rootDir>/output/runs/`. Optional `rootDir`.                                                                                         |
  | `c2n_get_run_report`       | read      | `slug`                                                                                                                                  | Returns `report.md` text.                                                                                                                               |
  | `c2n_list_unresolved`      | ask       | `slug`                                                                                                                                  | Returns parsed `output/runs/<slug>/resolution.json` entries — the questions to ask the human. Optional `rootDir`.                                       |
  | `c2n_propose_resolution`   | ask       | `rule_id`, `source_pattern_id`, `source_description`, `notion_block_type`, `mapping_description`, `example_input`, `example_output`, `confidence` | Appends to `output/proposals.json` (override with `proposalsPath`); creates the file when missing. Duplicate `rule_id` is rejected.                    |
  | `c2n_finalize_proposals`   | ask       | _(none)_                                                                                                                                | Materializes `output/proposals.json` → `output/rules.json`. Same logic as `c2n finalize`. Optional `proposalsPath` and `rulesOutPath` overrides.        |
  | `c2n_record_migration`     | **write** | `confluencePageId`, `notionPageId`, `slug`                                                                                              | Logs the host-created Notion page id under `output/runs/<slug>/mapping.json`. Optional `notionUrl`, `rootDir`. **The only write tool the c2n MCP exposes.** |

  The earlier draft of this doc listed `c2n_resolve_url`, `c2n_migrate`,
  `c2n_discover`, `c2n_fetch`, `c2n_convert`, and `c2n_status` — none of
  those exist. It also documented a `c2n_migrate_page` write tool that has
  since been dropped (issues #213, #218); use the table above.

- **CLI** `c2n` — `init`, `auth`, `use`, `profiles`, `fetch`, `fetch-tree`,
  `notion-ping`, `validate-output`, `finalize`, `convert`, `eval`, `migrate`,
  `migrate-tree`, `migrate-tree-pages`. Install with
  `npm i -g confluence-to-notion`, or invoke ad-hoc with
  `npx -p confluence-to-notion c2n …`.

- **Rule materialization**: `c2n finalize output/proposals.json` →
  `rules.json` (plus `c2n validate-output …` for schema checks). The MCP
  `c2n_finalize_proposals` tool delegates to the same code path so chat
  flows can stay inside MCP.

- **Notion writes** stay in the **host runtime's Notion MCP**. c2n hands
  off `c2n_convert_page` blocks; the host calls `create_page` /
  `append_blocks`; c2n records the resulting Notion page id via
  `c2n_record_migration`. The CLI `c2n migrate` path still writes to Notion
  directly with `NOTION_TOKEN` for batch / cron use, but the MCP surface
  does not.

### 2.2 What this repo does not provide out of the box

- There is **no** pipeline that builds `rules.json` **from chat thread text
  alone**.
- **Discover** (automatic rule discovery) is driven by Confluence samples /
  XHTML and `scripts/discover.sh`; it does **not** consume chat logs as
  input.
- The MCP server does not own access control. `c2n_record_migration`,
  `c2n_propose_resolution`, and `c2n_finalize_proposals` are callable
  whenever Confluence credentials resolve; gating "who can ask the bot to
  migrate or write rules" belongs in the OpenClaw skill / channel-trust
  layer.
- The MCP server does not own the Notion write side either — that
  responsibility sits with the host runtime's Notion MCP.

So **"chat conversation → rules → Notion"** is the **bridge** that the
integrator's OpenClaw skill / agent code is responsible for.

---

## 3. What you can build with this integration

Concrete shapes that fall out of c2n MCP + OpenClaw routing. Each one is
buildable with the eight tools above plus OpenClaw's standard channel/agent
plumbing — no fork of c2n required.

### 3.1 Read-only preview / triage bot

User pastes a Confluence URL in chat → the agent calls `c2n_fetch_page` then
`c2n_convert_page` and replies with:

- block count, unresolved-macro count, list of `usedRules`
- a short summary of which converters fired

Useful before a real migration to spot pages that need rule work first.
Strictly read-only.

### 3.2 Approval-gated migration

Same as 3.1, but with a follow-up confirmation step:

1. Agent calls `c2n_fetch_page` and `c2n_convert_page`, posts a preview of
   the resulting blocks plus unresolved-item summary.
2. Agent surfaces an approval request (OpenClaw exposes
   `permissions_list_open` / `permissions_respond` for runtimes that support
   it; otherwise a simple chat "yes/no" reply works).
3. On `allow-once` or explicit yes, the **host runtime's Notion MCP** is
   invoked: `create_page` (with the configured parent) and `append_blocks`
   for the converted blocks.
4. Once Notion returns the new page id, the agent calls
   `c2n_record_migration` with `{ confluencePageId, notionPageId, slug }` so
   the c2n run records the mapping under
   `output/runs/<slug>/mapping.json`.

Approval / channel trust live in the OpenClaw layer; the previous
`c2n_migrate_page` / `dryRun: true` knob is gone (`c2n_convert_page` itself
is the dry run, since it never touches Notion).

### 3.3 Run-history Q&A in chat

OpenClaw routes operational questions to an agent that exposes
`c2n_list_runs` + `c2n_get_run_report`. Common shapes:

- "어제 마이그레이션 결과 알려줘" → `c2n_list_runs` → pick most recent → `c2n_get_run_report`
- "왜 X 페이지가 unresolved 가 많이 떴어?" → fetch report → quote the relevant section back

This is read-only and works without any write credentials wired.

### 3.4 Multi-channel ops console

A single `mcp.servers.c2n` definition is consumed by every OpenClaw-routed
channel at once. The same agent that answers in Slack also answers in
Telegram or iMessage; the channel just changes who can talk to it. No
separate per-channel bridge.

### 3.5 Cross-team approval split

Requestor in one channel, approver in another, same MCP server underneath.
Pattern:

- Requestor in Telegram pastes a URL → agent calls `c2n_fetch_page` /
  `c2n_convert_page` and stages a pending request with the Notion parent id.
- Approver in Slack receives the preview + approval prompt.
- On approve, the agent calls the **host Notion MCP**'s `create_page` /
  `append_blocks`, then `c2n_record_migration` to log the result, and
  notifies both threads.

This needs a small piece of state in the OpenClaw skill (pending requests),
not in c2n.

### 3.6 Cron-triggered drift / smoke

OpenClaw has cron jobs (`docs/automation/cron-jobs.md`). Schedule a periodic:

- `c2n fetch-tree` against a known root → `c2n_convert_page` over each →
  surface any new unresolved macros to a Slack channel.

Detects "someone added a new macro to Confluence that we don't have a rule
for" before a real migration breaks. No write tool is needed for this loop.

### 3.7 Combine with other MCP servers in the same agent

Because OpenClaw's `mcp.servers` is a flat registry, the same agent can hold:

- `c2n` for fetch / convert / propose / finalize / record
- the host Notion MCP for `create_page` / `append_blocks`
- `context7` (or similar) for live docs lookup
- a custom Notion-search MCP for "does this already exist in Notion?" before
  migrating

The agent decides which tool to call; c2n only owns the read + ask/answer
+ record legs.

### 3.8 Chat-to-rules bridge

The earlier "Slack bridge" framing. The new path stays inside MCP:

1. Agent calls `c2n_list_unresolved` for the current run to get the open
   questions.
2. For each one, the agent (with human input from chat) authors a proposal
   and calls `c2n_propose_resolution`:

   ```jsonc
   // tool call sketch
   {
     "name": "c2n_propose_resolution",
     "arguments": {
       "rule_id": "rule:jira-link",
       "source_pattern_id": "pattern:jira-macro",
       "source_description": "Confluence Jira inline link macro",
       "notion_block_type": "bookmark",
       "mapping_description": "Map ac:link macros pointing at Jira to Notion bookmarks.",
       "example_input": "<ac:link>…</ac:link>",
       "example_output": { "type": "bookmark", "url": "…" },
       "confidence": "high"
     }
   }
   ```

3. When the chat thread is done, the agent calls `c2n_finalize_proposals`
   to write `output/rules.json`. The next `c2n_convert_page` call uses the
   new ruleset.

Schema validity and the human review loop are still on the integrator, but
no `proposals.json` hand-edit and no out-of-band CLI invocation is required.

---

## 4. Discover and Claude Code CLI (still relevant)

- `scripts/discover.sh` runs **`claude -p` (Claude Code CLI)** as a
  subprocess. That is **separate** from whichever LLM OpenClaw's runtime
  uses. To run discover, the host needs the **`claude` CLI installed and
  signed in**.
- If **`output/rules.json` already exists** and you only convert/migrate, you
  can run the runtime path **without** Claude CLI when you are not using
  `--rediscover`.
- The MCP server itself does **not** require the `claude` CLI — the eight
  tools in §2.1 work without it.

**Bridge design options for rule sourcing**

| Strategy                | Description                                                                                                                                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. Conversation-only    | OpenClaw skill drives `c2n_propose_resolution` (one call per resolved question) + `c2n_finalize_proposals` to materialize `rules.json`. Discover may be skipped; schema and quality are owned by the skill, with the MCP tools enforcing the schema at submission time.              |
| B. Combine with discover | Run `discover.sh` on Confluence samples → `rules.json`, plus a **merge policy** with bridge-produced proposals if needed.                                                                                                                                                            |
| C. Read-only first       | Skip rule authoring entirely for v1: only expose `c2n_fetch_page`, `c2n_convert_page`, `c2n_list_runs`, `c2n_get_run_report`. Defer rule writes and Notion writes until the host pipeline is ready. This is the lowest-risk starting point.                                          |

---

## 5. OpenClaw MCP integration

OpenClaw stores outbound MCP server definitions under **`mcp.servers.<name>`**
in OpenClaw config. Runtimes (embedded Pi, Claude Code, Gemini, …) consume
that registry — they do not each keep their own list. The CLI surface is
`openclaw mcp list | show | set | unset` (see `docs/cli/mcp.md` in
openclaw/openclaw).

> **Heads-up.** `openclaw mcp serve` is a separate command that exposes
> OpenClaw conversations *as* an MCP server. That is **not** what we use
> here — we are registering c2n as an MCP server **for** OpenClaw runtimes.

### 5.1 Stdio transport keys (verified)

| Field                      | Description                       |
| -------------------------- | --------------------------------- |
| `command`                  | Executable to spawn (required)    |
| `args`                     | Array of command-line arguments   |
| `env`                      | Extra environment variables       |
| `cwd` / `workingDirectory` | Working directory for the process |

### 5.2 Recommended c2n entry (npx, no repo clone needed)

```bash
openclaw mcp set c2n '{"command":"npx","args":["-p","confluence-to-notion","c2n-mcp"]}'
```

Equivalent in config form:

```json
{
  "mcp": {
    "servers": {
      "c2n": {
        "command": "npx",
        "args": ["-p", "confluence-to-notion", "c2n-mcp"]
      }
    }
  }
}
```

For pinning, prefer `["-p", "confluence-to-notion@0.1.3", "c2n-mcp"]` so a
publish-time regression cannot surprise the runtime.

### 5.3 When `cwd` matters

`cwd` is **not** required for the read-only tools (`c2n_fetch_page`,
`c2n_convert_page`) once 0.1.3's profile-aware credential resolution is in
place — the server reads creds from the per-user store and does not need a
repo clone.

`cwd` **does** matter for:

- `c2n_list_runs`, `c2n_get_run_report`, `c2n_list_unresolved`, and
  `c2n_record_migration` — these read from / write to
  `<cwd>/output/runs/` by default. Point `cwd` at the directory where the
  c2n run artifacts live (or pass `rootDir` per call).
- `c2n_propose_resolution` and `c2n_finalize_proposals` — these read from /
  write to `<cwd>/output/proposals.json` and `<cwd>/output/rules.json` by
  default. Point `cwd` at the directory where the discover-pipeline outputs
  live (or pass `proposalsPath` / `rulesOutPath` per call).

If you do not need any of those, omit `cwd`.

### 5.4 Env-safety filter (gotcha)

OpenClaw's stdio transport rejects interpreter-startup env keys (e.g.
`NODE_OPTIONS`, `PYTHONSTARTUP`, `PYTHONPATH`) inside a server's `env` block.
**Ordinary credentials and proxies pass through unchanged** —
`CONFLUENCE_API_TOKEN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_BASE_URL`,
`HTTP_PROXY`, custom `*_API_KEY`, etc. are unaffected. Only the
runtime-control variables are blocked, and they should be set on the gateway
host process if they are genuinely needed.

### 5.5 Write safety

The c2n MCP server has **no Notion write tool**. Page creation runs through
the host runtime's Notion MCP (`create_page` / `append_blocks`); approval
lives in the host runtime's permissions layer (OpenClaw's
`permissions_respond`, sender allowlist, channel trust);
`c2n_record_migration` is post-write bookkeeping that logs the resulting
Notion page id against the c2n run.

The previous `allowWrite` env gate and per-call `dryRun` argument are gone
(issues #213, #218): there is nothing to gate on the c2n side, and the
"dry run" mode is now just calling `c2n_convert_page` without invoking the
host Notion MCP afterwards.

If a host genuinely needs a Notion-side hard stop, scope the configured
Notion integration's page access — neither c2n nor the host's Notion MCP
can do anything the underlying Notion token cannot.

---

## 6. Credentials (0.1.3 profile store)

`c2n init` writes credentials into a per-user config file
(`~/.config/c2n/config.json` by default; override with `C2N_CONFIG_DIR`). The
MCP server reads them through the same store, so the `env:` block in the
OpenClaw MCP definition becomes optional once init has run.

**Resolution order inside `c2n-mcp`** (see `src/mcp/README.md`):

1. `--profile <name>` flag (when a wrapper passes one)
2. `C2N_PROFILE` env var
3. `currentProfile` recorded in the config file
4. `"default"`

If the resolved profile is missing or incomplete, the entry falls back to
direct env vars so existing deployments keep working:

| Env var                 | Used for                                                              |
| ----------------------- | --------------------------------------------------------------------- |
| `CONFLUENCE_BASE_URL`   | Builds the Confluence adapter for `c2n_fetch_page`.                   |
| `CONFLUENCE_EMAIL`      | Same.                                                                 |
| `CONFLUENCE_API_TOKEN`  | Same.                                                                 |
| `C2N_CONFIG_DIR`        | Override the config-store directory (defaults to `~/.config/c2n`).    |
| `C2N_PROFILE`           | Pick a non-default profile.                                           |

`NOTION_TOKEN` is no longer consumed by the c2n MCP server (no MCP write
path remains). The CLI `c2n migrate` family still uses it for batch / cron
writes outside the MCP surface.

**Recommended setup on the OpenClaw host:**

```bash
# One-time, interactive: writes ~/.config/c2n/config.json
npx -p confluence-to-notion c2n init

# Verify
npx -p confluence-to-notion c2n profiles list
npx -p confluence-to-notion c2n notion-ping
```

After this, the OpenClaw `mcp.servers.c2n` entry can stay credential-free —
the server picks up the profile automatically. Multiple profiles
(`--profile staging`, `--profile prod`) can be selected by setting
`C2N_PROFILE` in the OpenClaw `env` block per channel/workspace.

---

## 7. Windows + security posture (native Windows, no WSL)

- **Discover** needs **`bash scripts/discover.sh`** → **Bash** must be
  available. Use **Git for Windows (Git Bash)** or another approved Bash
  where `bash` is on `PATH`.
- The MCP server itself is pure Node — no Bash needed at runtime.
- Prefer repo paths and `cwd` values **without spaces or non-ASCII**.
- Runtime is **Node 20 LTS** (this repo was ported from Python; there is no
  `uv` / Python toolchain anymore).
- Run OpenClaw, Claude Code CLI (only if discover is used), and Node on the
  **same machine** and align MCP `cwd` with that layout.

---

## 8. MVP bridge — minimal changes to this repo

You can ship a first version **without forking c2n**:

1. The OpenClaw skill walks `c2n_list_unresolved` for the active run and
   collects answers from chat.
2. For each answered question, the skill calls `c2n_propose_resolution` to
   append to `output/proposals.json`.
3. Once the skill is done, it calls `c2n_finalize_proposals` (or
   `c2n finalize` / `c2n validate-output …` from the CLI for parity
   debugging) to write `output/rules.json`.
4. To migrate a page, the skill calls `c2n_fetch_page` →
   `c2n_convert_page`, then asks the **host runtime's Notion MCP** to run
   `create_page` + `append_blocks` against the configured parent, and
   finally calls `c2n_record_migration` to log the new Notion page id
   against the c2n run.

Optional later improvements: code-level merge rules with discover output,
batch ingest endpoints, etc.

---

## 9. Operational guardrails

- Chat-derived rule JSON will **not** always validate → expect retry loops
  and human review on schema failure. `c2n_propose_resolution` enforces the
  `ProposedRule` schema at submission time, so invalid payloads surface as
  `InvalidParams` immediately.
- **Which Confluence URLs or scopes** to migrate stays ambiguous if only
  inferred from chat → keep explicit URL lists, spaces, or an approval step.
- Scope **secrets and logging** so sensitive data (tokens, page bodies) does
  not leak to LLMs or logs against company policy. The c2n profile store
  keeps credentials out of MCP `env` blocks; OpenClaw's
  channel-trust + sender-allowlist controls keep the MCP entry from being
  callable by arbitrary users.
- For writes, prefer the staged path: `c2n_convert_page` preview → human
  approval → host Notion MCP `create_page` / `append_blocks` →
  `c2n_record_migration`. The OpenClaw-side approval step is the
  load-bearing control; neither the c2n server nor the host's Notion MCP
  enforces who can call write tools.

---

## 10. Glossary

| Term                       | Meaning                                                                                                     |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- |
| OpenClaw                   | Multi-channel personal/team agent runtime (`openclaw/openclaw`). Routes Slack, Telegram, iMessage, etc.     |
| `mcp.servers`              | OpenClaw's outbound MCP server registry — where c2n is registered (`openclaw mcp set …`).                   |
| `openclaw mcp serve`       | Separate command: exposes OpenClaw conversations *as* an MCP server. Not what this doc wires.               |
| c2n / confluence-to-notion | This repository: Confluence XHTML → Notion blocks, conversion, MCP server.                                  |
| Discover                   | Rule proposal pipeline: `discover.sh` + Claude Code CLI. Independent of OpenClaw.                           |
| Bridge                     | Integrator's OpenClaw skill: chat ↔ list_unresolved / propose_resolution / finalize_proposals / record_migration. |
| Profile store              | `~/.config/c2n/config.json` populated by `c2n init`; replaces per-shell `.env` exports for c2n credentials. |

---

## 11. References

- This repo: `README.md`, `src/mcp/README.md`, `CLAUDE.md`,
  `tests/fixtures/mcp/tools-list.json`, `scripts/discover.sh`,
  `.claude/docs/ADR.md` (ADR-007).
- OpenClaw repo (`openclaw/openclaw`): `docs/cli/mcp.md`,
  `docs/automation/cron-jobs.md`, `docs/plugins/plugin.md`.

---

*This document is a handoff summary. Prefer the latest README and
`c2n --help` when implementing.*
