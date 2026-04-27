import { Command } from "commander";
import pkg from "../../package.json" with { type: "json" };
import { registerConvertCommands } from "./convert.js";
import { registerDiscoverShim } from "./discover.js";
import { registerEvalHarness } from "./evalHarness.js";
import { registerFetchCommands } from "./fetch.js";
import { registerFinalizeCommands } from "./finalize.js";
import { registerInitCommand } from "./init.js";
import { registerMigrateCommands } from "./migrate.js";
import { registerNotionCommands } from "./notion.js";
import { registerValidateCommands } from "./validate.js";

export function createProgram(): Command {
  const program = new Command();
  program
    .name("c2n")
    .description(
      [
        "confluence-to-notion: auto-discover and apply Confluence → Notion transformation rules.",
        "Load environment variables from a .env file when running locally, e.g. `node --env-file=.env $(pnpm bin)/c2n …`.",
      ].join(" "),
    )
    .version(pkg.version, "-v, --version", "output the current version")
    .option("--verbose", "enable verbose logging")
    .option("--quiet", "suppress non-essential output")
    .option("--no-color", "disable ANSI color output");

  registerInitCommand(program);
  registerFetchCommands(program);
  registerNotionCommands(program);
  registerDiscoverShim(program);
  registerEvalHarness(program);
  registerValidateCommands(program);
  registerFinalizeCommands(program);
  registerConvertCommands(program);
  registerMigrateCommands(program);

  return program;
}
