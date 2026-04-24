import { Command, Option } from "commander";
import pkg from "../../package.json" with { type: "json" };

const notImplemented = (sub: string): (() => never) => {
  return () => {
    throw new Error(`not implemented: ${sub}`);
  };
};

export function createProgram(): Command {
  const program = new Command();
  program
    .name("c2n")
    .description(
      "confluence-to-notion: auto-discover and apply Confluence → Notion transformation rules",
    )
    .version(pkg.version, "-v, --version", "output the current version")
    .option("--verbose", "enable verbose logging")
    .option("--quiet", "suppress non-essential output")
    .option("--no-color", "disable ANSI color output");

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

  program
    .command("notion-ping")
    .description("Validate the Notion API token by fetching bot user info.")
    .action(notImplemented("notion-ping"));

  program
    .command("discover")
    .description("Reminder shim: prints the correct `bash scripts/discover.sh` invocation.")
    .action(() => {
      process.stdout.write(
        "discover is not a CLI entry point. Run: bash scripts/discover.sh <samples-dir> --url <confluence-url>\n",
      );
      process.exit(1);
    });

  program
    .command("validate-output")
    .description("Validate an agent output file against its schema.")
    .argument("<file>", "JSON file to validate")
    .argument("<schema>", "schema name: discovery | proposer | scout")
    .action(notImplemented("validate-output"));

  program
    .command("finalize")
    .description("Convert proposals.json → rules.json by promoting every rule with enabled=true.")
    .argument("[proposals_file]", "path to proposals.json", "output/proposals.json")
    .option("--out <path>", "output rules.json path", "output/rules.json")
    .action(notImplemented("finalize"));

  program
    .command("convert")
    .description("Convert XHTML pages to Notion blocks using finalized rules.")
    .option("--rules <path>", "path to rules.json", "output/rules.json")
    .option("--input <path>", "directory of XHTML files", "samples")
    .requiredOption(
      "--url <url>",
      "Confluence source URL; converted JSON lands under output/runs/<slug>/converted/",
    )
    .action(notImplemented("convert"));

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

  return program;
}
