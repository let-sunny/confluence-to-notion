import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { Command } from "commander";
import { finalRulesetFromProposerOutput } from "../agentOutput/finalRuleset.js";
import { ProposerOutputSchema } from "../agentOutput/schemas.js";

export async function finalizeProposalsToRules(
  proposalsPath: string,
  rulesOutPath: string,
): Promise<{ ruleCount: number }> {
  let raw: string;
  try {
    raw = await readFile(proposalsPath, "utf8");
  } catch (e) {
    throw new Error(`Cannot read proposals file: ${proposalsPath}: ${String(e)}`);
  }
  let json: unknown;
  try {
    json = JSON.parse(raw) as unknown;
  } catch (e) {
    throw new SyntaxError(`Invalid JSON in ${proposalsPath}: ${String(e)}`);
  }
  const proposer = ProposerOutputSchema.parse(json);
  const ruleset = finalRulesetFromProposerOutput(proposer);
  await mkdir(dirname(rulesOutPath), { recursive: true });
  await writeFile(rulesOutPath, `${JSON.stringify(ruleset, null, 2)}\n`, "utf8");
  return { ruleCount: ruleset.rules.length };
}

export function registerFinalizeCommands(program: Command): void {
  program
    .command("finalize")
    .description("Convert proposals.json → rules.json by promoting every rule with enabled=true.")
    .argument("[proposals_file]", "path to proposals.json", "output/proposals.json")
    .option("--out <path>", "output rules.json path", "output/rules.json")
    .action(async function (this: Command, proposalsFile: string) {
      const opts = this.opts<{ out: string }>();
      try {
        const { ruleCount } = await finalizeProposalsToRules(proposalsFile, opts.out);
        process.stdout.write(`Finalized ${String(ruleCount)} rules → ${opts.out}\n`);
      } catch (e) {
        process.stderr.write(`finalize: ${String(e)}\n`);
        process.exit(1);
      }
    });
}
