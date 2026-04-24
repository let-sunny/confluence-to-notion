import type { Command } from "commander";
import { notImplemented } from "./stub.js";

export function registerFetchCommands(program: Command): void {
  program
    .command("fetch")
    .description("Fetch Confluence pages and save XHTML to disk.")
    .option("--space <key>", "Confluence space key (paginates with --limit)")
    .option("--pages <ids>", "comma-separated Confluence page IDs")
    .option("--limit <n>", "max pages when using --space", "25")
    .option("--out-dir <path>", "output directory for XHTML", "samples")
    .option("--url <url>", "Confluence source URL; writes artifacts under output/runs/<slug>/")
    .action(notImplemented("fetch"));

  program
    .command("fetch-tree")
    .description("Fetch the Confluence page tree starting from a root page.")
    .requiredOption("--root-id <id>", "Confluence root page ID")
    .option("--output <path>", "output JSON path", "output/page-tree.json")
    .option("--url <url>", "Confluence source URL (overrides --output placement)")
    .action(notImplemented("fetch-tree"));
}
