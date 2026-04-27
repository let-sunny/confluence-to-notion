import { Client } from "@notionhq/client";
import type { Command } from "commander";
import { ConfigStoreError, type ConfigStoreOptions, getNotionCreds } from "../configStore.js";

interface NotionPingOptions {
  profile?: string;
}

function resolveConfigDirOpts(): ConfigStoreOptions {
  const dir = process.env.C2N_CONFIG_DIR?.trim();
  return dir !== undefined && dir.length > 0 ? { configDir: dir } : {};
}

export function registerNotionCommands(program: Command): void {
  program
    .command("notion-ping")
    .description("Validate the Notion API token by fetching bot user info.")
    .option("--profile <name>", "credential profile name (overrides C2N_PROFILE / currentProfile)")
    .action(async function (this: Command) {
      const opts = this.opts<NotionPingOptions>();
      let token: string;
      try {
        ({ token } = getNotionCreds(opts.profile, resolveConfigDirOpts()));
      } catch (e) {
        if (e instanceof ConfigStoreError) {
          process.stderr.write(`${e.message}\n`);
          process.exit(1);
        }
        throw e;
      }
      try {
        const client = new Client({ auth: token });
        await client.users.me({});
        process.stdout.write("notion-ping: ok\n");
      } catch (e) {
        process.stderr.write(`notion-ping: Notion API error: ${String(e)}\n`);
        process.exit(1);
      }
    });
}
