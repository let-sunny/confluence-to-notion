import type { Command } from "commander";
import { notImplemented } from "./stub.js";

export function registerFinalizeCommands(program: Command): void {
  program
    .command("finalize")
    .description("Convert proposals.json → rules.json by promoting every rule with enabled=true.")
    .argument("[proposals_file]", "path to proposals.json", "output/proposals.json")
    .option("--out <path>", "output rules.json path", "output/rules.json")
    .action(notImplemented("finalize"));
}
