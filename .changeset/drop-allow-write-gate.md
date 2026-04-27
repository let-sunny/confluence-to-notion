---
"confluence-to-notion": patch
---

Drop the `c2n_migrate_page` `allowWrite` gate (`C2N_MCP_ALLOW_WRITE=1` env
var). The flag added friction without moving the security boundary —
credentials in the profile store can already write through any Notion
client, so blocking the MCP path was performative. `dryRun: true` remains as
the per-call safety knob; chat-side approval and channel trust are the
right place for "who can ask the bot to migrate." Closes #212.
