import { Command } from "commander";
import pkg from "../package.json" with { type: "json" };

export function createProgram(): Command {
  const program = new Command();
  program
    .name("c2n")
    .description(
      "confluence-to-notion: auto-discover and apply Confluence → Notion transformation rules",
    )
    .version(pkg.version, "-v, --version", "output the current version");
  return program;
}

const isDirectInvocation =
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith("/dist/cli.js") === true;

if (isDirectInvocation) {
  createProgram().parse(process.argv);
}
