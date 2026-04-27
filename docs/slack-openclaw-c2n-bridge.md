# OpenClaw · confluence-to-notion bridge — agent handoff

This note is for internal agent / implementation teams wiring **chat-driven
Confluence → Notion migration** through OpenClaw. The repository
(`confluence-to-notion`, **c2n**) supplies the **migration engine and MCP
server**; OpenClaw supplies the **channel routing, runtime, and approval
plumbing** that surfaces those tools inside whichever chat surface a team
already uses (Slack, Telegram, iMessage, Discord, WhatsApp, Microsoft Teams,
Matrix, Google Chat, …).

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
3. The runtime calls c2n MCP tools to **fetch Confluence XHTML, convert to
   Notion blocks, list/inspect prior runs, or migrate a page** (write).
4. Results flow back through OpenClaw to the originating channel — usually as
   a preview first, then a write after explicit approval.
5. The ideal is **"I only replied in chat and Notion is already updated."** In
   practice, **read-only previews + explicit approval before
   `c2n_migrate_page`** is the realistic default for compliance and quality.

---

## 2. What this repo does / does not do

### 2.1 What this repo provides

- **stdio MCP server** `c2n-mcp` (`src/mcp/index.ts`). The exact tool surface
  is pinned by `tests/fixtures/mcp/tools-list.json`:

  | Tool                   | Type      | Required input                         | Notes                                                                                       |
  | ---------------------- | --------- | -------------------------------------- | ------------------------------------------------------------------------------------------- |
  | `c2n_fetch_page`       | read      | `pageIdOrUrl`                          | Optional `baseUrl` overrides `CONFLUENCE_BASE_URL`. Display URLs are rejected.              |
  | `c2n_convert_page`     | read      | `xhtml`                                | Returns `{ blocks, unresolved, usedRules }`. Optional `pageId`, `title`.                    |
  | `c2n_list_runs`        | read      | _(none)_                               | Lists slugs under `<rootDir>/output/runs/`. Optional `rootDir`.                             |
  | `c2n_get_run_report`   | read      | `slug`                                 | Returns `report.md` text.                                                                   |
  | `c2n_migrate_page`     | **write** | `pageIdOrUrl`, `parentNotionPageId`    | `dryRun: true` runs the conversion only and skips the Notion API call (per-call safety).   |

  The earlier draft of this doc listed `c2n_resolve_url`, `c2n_migrate`,
  `c2n_discover`, `c2n_fetch`, `c2n_convert`, and `c2n_status` — none of those
  exist in the published 0.1.3 server. Use the table above.

- **CLI** `c2n` — `init`, `auth`, `use`, `profiles`, `fetch`, `fetch-tree`,
  `notion-ping`, `validate-output`, `finalize`, `convert`, `eval`, `migrate`,
  `migrate-tree`, `migrate-tree-pages`. Install with
  `npm i -g confluence-to-notion`, or invoke ad-hoc with
  `npx -p confluence-to-notion c2n …`.

- **Rule materialization**: `c2n finalize output/proposals.json` →
  `rules.json` (plus `c2n validate-output …` for schema checks).

- **Migration**: `c2n migrate --url <confluence-url>` or MCP
  `c2n_migrate_page` writes Notion pages from rules + XHTML.

### 2.2 What this repo does not provide out of the box

- There is **no** pipeline that builds `rules.json` **from chat thread text
  alone**.
- **Discover** (automatic rule discovery) is driven by Confluence samples /
  XHTML and `scripts/discover.sh`; it does **not** consume chat logs as
  input.
- The MCP server does not own access control. `c2n_migrate_page` is callable
  whenever Confluence + Notion credentials resolve; gating "who can ask the
  bot to migrate" belongs in the OpenClaw skill / channel-trust layer.

So **"chat conversation → rules"** is the **bridge** that the integrator's
OpenClaw skill / agent code is responsible for.

---

## 3. What you can build with this integration

Concrete shapes that fall out of c2n MCP + OpenClaw routing. Each one is
buildable with the five tools above plus OpenClaw's standard channel/agent
plumbing — no fork of c2n required.

### 3.1 Read-only preview / triage bot

User pastes a Confluence URL in chat → the agent calls `c2n_fetch_page` then
`c2n_convert_page` and replies with:

- block count, unresolved-macro count, list of `usedRules`
- a short summary of which converters fired

Useful before a real migration to spot pages that need rule work first.
Strictly read-only, no `allowWrite` required.

### 3.2 Approval-gated migration

Same as 3.1, but with a follow-up confirmation step:

1. Agent posts a preview of `c2n_convert_page` output (or calls
   `c2n_migrate_page` with `dryRun: true` to also exercise the fetch path).
2. Agent surfaces an approval request (OpenClaw exposes
   `permissions_list_open` / `permissions_respond` for runtimes that support
   it; otherwise a simple chat "yes/no" reply works).
3. On `allow-once` or explicit yes, the agent calls `c2n_migrate_page` with
   `dryRun: false` and the Notion parent page ID configured for that channel
   or workspace.

`dryRun: true` is the only built-in safety knob on the c2n side — it runs
fetch + convert end-to-end and reports `blockCount` / `unresolvedCount`
without calling the Notion API. Approval / channel trust live in the
OpenClaw layer.

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

- Requestor in Telegram pastes a URL → agent records a pending migration with
  the Notion parent ID.
- Approver in Slack receives the preview + approval prompt.
- On approve, the agent calls `c2n_migrate_page` and notifies both threads.

This needs a small piece of state in the OpenClaw skill (pending requests),
not in c2n.

### 3.6 Cron-triggered drift / smoke

OpenClaw has cron jobs (`docs/automation/cron-jobs.md`). Schedule a periodic:

- `c2n fetch-tree` against a known root → `c2n_convert_page` over each →
  surface any new unresolved macros to a Slack channel.

Detects "someone added a new macro to Confluence that we don't have a rule
for" before a real migration breaks.

### 3.7 Combine with other MCP servers in the same agent

Because OpenClaw's `mcp.servers` is a flat registry, the same agent can hold:

- `c2n` for migration
- `context7` (or similar) for live docs lookup
- a custom Notion-search MCP for "does this already exist in Notion?" before
  migrating

The agent decides which tool to call; c2n only owns the migration leg.

### 3.8 Chat-to-rules bridge (advanced)

The earlier "Slack bridge" framing. OpenClaw skill gathers conversation
distillations, the skill writes a valid `output/proposals.json`, then calls
`c2n finalize` followed by `c2n_migrate_page`. c2n does not own this leg —
schema validity and the human review loop are on the integrator. See §7.

---

## 4. Discover and Claude Code CLI (still relevant)

- `scripts/discover.sh` runs **`claude -p` (Claude Code CLI)** as a
  subprocess. That is **separate** from whichever LLM OpenClaw's runtime
  uses. To run discover, the host needs the **`claude` CLI installed and
  signed in**.
- If **`output/rules.json` already exists** and you only convert/migrate, you
  can run the runtime path **without** Claude CLI when you are not using
  `--rediscover`.
- The MCP server itself does **not** require the `claude` CLI — the five
  tools in §2.1 work without it.

**Bridge design options for rule sourcing**

| Strategy                | Description                                                                                                                                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A. Conversation-only    | OpenClaw skill authors `proposals.json` (LLM-assisted or hand-edited) → `c2n finalize` → `c2n_migrate_page`. Discover may be skipped; schema and quality are owned by the skill.                                                                                                      |
| B. Combine with discover | Run `discover.sh` on Confluence samples → `rules.json`, plus a **merge policy** with bridge-produced proposals if needed.                                                                                                                                                            |
| C. Read-only first       | Skip rule authoring entirely for v1: only expose `c2n_fetch_page`, `c2n_convert_page`, `c2n_list_runs`, `c2n_get_run_report`. Defer migration writes until a `proposals.json` workflow exists. This is the lowest-risk starting point.                                              |

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

- `c2n_list_runs` and `c2n_get_run_report` — these read from
  `<cwd>/output/runs/` by default. If you want the bot to surface real
  migration history, point `cwd` at the directory where prior runs were
  written (or pass `rootDir` per call).
- Future write tooling that materializes artifacts under `output/` (none of
  the current write tools require this, but it is the natural place to grow).

If you do not need run-history reads, omit `cwd`.

### 5.4 Env-safety filter (gotcha)

OpenClaw's stdio transport rejects interpreter-startup env keys (e.g.
`NODE_OPTIONS`, `PYTHONSTARTUP`, `PYTHONPATH`) inside a server's `env` block.
**Ordinary credentials and proxies pass through unchanged** —
`CONFLUENCE_API_TOKEN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_BASE_URL`,
`NOTION_TOKEN`, `HTTP_PROXY`, custom `*_API_KEY`, etc. are unaffected. Only
the runtime-control variables are blocked, and they should be set on the
gateway host process if they are genuinely needed.

### 5.5 Write safety

`c2n_migrate_page` is always callable when Confluence + Notion credentials
resolve. There is no server-side on/off gate (issue #212 dropped the prior
`allowWrite` / `C2N_MCP_ALLOW_WRITE` flag — it added friction without moving
the security boundary anywhere useful, since anyone who can read the profile
store can already write through any Notion client).

For staged rollout and tests, the safety primitive is the per-call
`dryRun: true` argument: it runs fetch + convert end-to-end and reports
`{ blockCount, unresolvedCount, sourcePageId, title, dryRun: true }` without
touching the Notion API. Pair that with the OpenClaw approval layer
(`permissions_respond`, sender allowlist, channel trust) for the actual
"who can ask the bot to migrate" decision.

If a host genuinely needs a Notion-side hard stop, scope the configured
Notion integration's page access — the c2n MCP server cannot do anything the
underlying Notion token cannot.

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
| `CONFLUENCE_BASE_URL`   | Builds the Confluence adapter for `c2n_fetch_page` / `c2n_migrate_page`. |
| `CONFLUENCE_EMAIL`      | Same.                                                                 |
| `CONFLUENCE_API_TOKEN`  | Same.                                                                 |
| `NOTION_TOKEN`          | Builds the Notion adapter for `c2n_migrate_page`.                     |
| `C2N_CONFIG_DIR`        | Override the config-store directory (defaults to `~/.config/c2n`).    |
| `C2N_PROFILE`           | Pick a non-default profile.                                           |

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

1. The OpenClaw skill writes **`output/proposals.json`** (valid schema) from
   chat / approval state.
2. `c2n finalize output/proposals.json` → **`rules.json`**.
3. Validate with `c2n validate-output …` (see CLI / README).
4. `c2n migrate --url …` (CLI) **or** MCP `c2n_migrate_page` (write,
   `allowWrite` + `dryRun: true` first) to push to Notion.

Optional later improvements: MCP tools that accept proposal payloads inline,
subcommands to merge or repair proposals, code-level merge rules with
discover output, etc.

---

## 9. Operational guardrails

- Chat-derived rule JSON will **not** always validate → expect retry loops
  and human review on schema failure.
- **Which Confluence URLs or scopes** to migrate stays ambiguous if only
  inferred from chat → keep explicit URL lists, spaces, or an approval step.
- Scope **secrets and logging** so sensitive data (tokens, page bodies) does
  not leak to LLMs or logs against company policy. The c2n profile store
  keeps credentials out of MCP `env` blocks; OpenClaw's
  channel-trust + sender-allowlist controls keep the MCP entry from being
  callable by arbitrary users.
- For writes, prefer the staged path: `dryRun: true` → human approval →
  `dryRun: false`. The OpenClaw-side approval step is the load-bearing
  control; the c2n server itself does not enforce who can call write tools.

---

## 10. Glossary

| Term                       | Meaning                                                                                                     |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- |
| OpenClaw                   | Multi-channel personal/team agent runtime (`openclaw/openclaw`). Routes Slack, Telegram, iMessage, etc.     |
| `mcp.servers`              | OpenClaw's outbound MCP server registry — where c2n is registered (`openclaw mcp set …`).                   |
| `openclaw mcp serve`       | Separate command: exposes OpenClaw conversations *as* an MCP server. Not what this doc wires.               |
| c2n / confluence-to-notion | This repository: Confluence XHTML → Notion blocks, conversion, MCP server.                                  |
| Discover                   | Rule proposal pipeline: `discover.sh` + Claude Code CLI. Independent of OpenClaw.                           |
| Bridge                     | Integrator's OpenClaw skill: chat ↔ proposals / finalize / migrate.                                         |
| Profile store              | `~/.config/c2n/config.json` populated by `c2n init`; replaces per-shell `.env` exports for c2n credentials. |

---

## 11. References

- This repo: `README.md`, `src/mcp/README.md`, `CLAUDE.md`,
  `tests/fixtures/mcp/tools-list.json`, `scripts/discover.sh`.
- OpenClaw repo (`openclaw/openclaw`): `docs/cli/mcp.md`,
  `docs/automation/cron-jobs.md`, `docs/plugins/plugin.md`.

---

*This document is a handoff summary. Prefer the latest README and
`c2n --help` when implementing.*
