/**
 * TypeScript eval pipeline entry (PR 4/5 — replaces `python -m confluence_to_notion.eval`).
 * This scaffold keeps `scripts/run-eval.sh` on a Node-only path; semantic coverage,
 * baseline diff, and LLM-as-judge ports land in follow-up commits on the same branch.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

interface EvalCliArgs {
  outputDir: string;
  evalResultsDir: string;
  samplesDir: string;
  llmJudge: boolean;
  failOnRegression: boolean;
}

function parseArgs(argv: string[]): EvalCliArgs {
  const rest = argv.slice(2);
  let llmJudge = false;
  let failOnRegression = false;
  const positional: string[] = [];
  for (const a of rest) {
    if (a === "--llm-judge") {
      llmJudge = true;
      continue;
    }
    if (a === "--fail-on-regression") {
      failOnRegression = true;
      continue;
    }
    positional.push(a);
  }
  const [outputDir = "output", evalResultsDir = "eval_results", samplesDir = "samples"] =
    positional;
  return { outputDir, evalResultsDir, samplesDir, llmJudge, failOnRegression };
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv);
  await mkdir(args.evalResultsDir, { recursive: true });
  const stamp = new Date().toISOString().replaceAll(":", "-");
  const outFile = join(args.evalResultsDir, `${stamp}.json`);
  const payload = {
    generatedAt: new Date().toISOString(),
    outputDir: args.outputDir,
    samplesDir: args.samplesDir,
    flags: { llmJudge: args.llmJudge, failOnRegression: args.failOnRegression },
    summary: {
      status: "scaffold",
      message:
        "TS eval harness scaffold — schema validation runs via c2n validate-output in run-eval.sh; semantic coverage, baseline, and LLM judge are not ported in this commit.",
    },
  };
  await writeFile(outFile, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  process.stdout.write(`eval: wrote ${outFile}\n`);
}

main().catch((err: unknown) => {
  process.stderr.write(`eval: ${String(err)}\n`);
  process.exit(1);
});
