import { Client } from "@notionhq/client";
import type { Command } from "commander";

function readNotionToken(): string | undefined {
  const a = process.env.NOTION_API_TOKEN;
  const b = process.env.NOTION_TOKEN;
  if (typeof a === "string" && a.length > 0) return a;
  if (typeof b === "string" && b.length > 0) return b;
  return undefined;
}

function readNotionRootPageId(): string | undefined {
  const v = process.env.NOTION_ROOT_PAGE_ID;
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

export function registerNotionCommands(program: Command): void {
  program
    .command("notion-ping")
    .description("Validate the Notion API token by fetching bot user info.")
    .action(async () => {
      const token = readNotionToken();
      if (token === undefined) {
        process.stderr.write(
          "Missing NOTION_API_TOKEN (or legacy NOTION_TOKEN). See CONTRIBUTING.md and ADR-00M.\n",
        );
        process.exit(1);
      }
      if (readNotionRootPageId() === undefined) {
        process.stderr.write(
          "Missing NOTION_ROOT_PAGE_ID (required by the frozen CLI contract).\n",
        );
        process.exit(1);
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
