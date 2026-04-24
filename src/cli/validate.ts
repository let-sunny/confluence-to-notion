import type { Command } from "commander";
import { notImplemented } from "./stub.js";

export function registerValidateCommands(program: Command): void {
  program
    .command("validate-output")
    .description("Validate an agent output file against its schema.")
    .argument("<file>", "JSON file to validate")
    .argument("<schema>", "schema name: discovery | proposer | scout")
    .action(notImplemented("validate-output"));
}
