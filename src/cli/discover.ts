import type { Command } from "commander";

export function registerDiscoverShim(program: Command): void {
  program
    .command("discover")
    .description("Reminder shim: prints the correct `bash scripts/discover.sh` invocation.")
    .action(() => {
      process.stdout.write(
        "discover is not a CLI entry point. Run: bash scripts/discover.sh <samples-dir> --url <confluence-url>\n",
      );
      process.exit(1);
    });
}
