import type { Command } from "commander";
import { Option } from "commander";
import { notImplemented } from "./stub.js";

export function registerMigrateCommands(program: Command): void {
  program
    .command("migrate")
    .description("Convert XHTML pages and publish to Notion (URL-dispatch or legacy batch).")
    .argument("[confluence_url]", "Confluence source URL (preferred form)")
    .addOption(
      new Option("--to <target>", "Notion parent (page URL or page id)").env("NOTION_ROOT_PAGE_ID"),
    )
    .option("--name <slug>", "override run slug under output/runs/")
    .option("--rediscover", "force re-running scripts/discover.sh", false)
    .option("--dry-run", "fetch + convert only; skip every Notion write", false)
    .option("--rules <path>", "path to rules.json", "output/rules.json")
    .option("--input <path>", "directory of XHTML files", "samples")
    .addOption(
      new Option("--target <id>", "Notion parent page ID (legacy form)").env("NOTION_ROOT_PAGE_ID"),
    )
    .option("--url <url>", "Confluence source URL (required when the positional URL is omitted)")
    .action(notImplemented("migrate"));

  program
    .command("migrate-tree")
    .description("Create an empty Notion page hierarchy mirroring a Confluence tree.")
    .option("--tree <path>", "path to page-tree.json", "output/page-tree.json")
    .addOption(new Option("--target <id>", "Notion parent page ID").env("NOTION_ROOT_PAGE_ID"))
    .requiredOption(
      "--url <url>",
      "Confluence source URL; resolution.json lands under output/runs/<slug>/",
    )
    .action(notImplemented("migrate-tree"));

  program
    .command("migrate-tree-pages")
    .description("Multi-pass migration: tree → table-rule discovery → body upload.")
    .requiredOption("--root-id <id>", "Confluence root page ID")
    .addOption(new Option("--target <id>", "Notion parent page ID").env("NOTION_ROOT_PAGE_ID"))
    .option("--rules <path>", "path to rules.json", "output/rules.json")
    .requiredOption(
      "--url <url>",
      "Confluence source URL; every artifact lands under output/runs/<slug>/",
    )
    .action(notImplemented("migrate-tree-pages"));
}
