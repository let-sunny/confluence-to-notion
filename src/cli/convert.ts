import type { Command } from "commander";
import { notImplemented } from "./stub.js";

export function registerConvertCommands(program: Command): void {
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
}
