/**
 * TypeScript eval pipeline (PR 4/5). Produces `EvalReport`-shaped JSON under
 * `eval_results/<timestamp>.json`, matching the historical Python comparator path.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { compareToBaseline, loadPreviousEvalReport } from "./baseline.js";
import { runEvalCore } from "./comparator.js";
import { runLlmJudgeIfConfigured } from "./llmJudge.js";
import type { EvalReport } from "./report.js";

interface EvalCliArgs {
  outputDir: string;
  evalResultsDir: string;
  samplesDir?: string;
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
  const [outputDir = "output", evalResultsDir = "eval_results", samplesDir] = positional;
  const base = { outputDir, evalResultsDir, llmJudge, failOnRegression };
  return samplesDir !== undefined ? { ...base, samplesDir } : base;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv);
  const resultsDir = resolve(args.evalResultsDir);
  const previous = await loadPreviousEvalReport(resultsDir);

  if (args.llmJudge && args.samplesDir === undefined) {
    process.stderr.write("--llm-judge requires <samples_dir> as the third positional argument.\n");
    process.exit(1);
  }

  const core = await runEvalCore(args.outputDir, args.samplesDir);

  let llm_judge: unknown = null;
  if (args.llmJudge && args.samplesDir !== undefined) {
    llm_judge = await runLlmJudgeIfConfigured({
      outputDir: resolve(args.outputDir),
      samplesDir: resolve(args.samplesDir),
    });
  }

  const beforeBaseline: EvalReport = {
    ...core,
    llm_judge,
    baseline_comparison: null,
  };
  const report: EvalReport = {
    ...beforeBaseline,
    baseline_comparison: compareToBaseline(beforeBaseline, previous),
  };

  await mkdir(resultsDir, { recursive: true });
  const stamp = report.timestamp.replaceAll(":", "-").replaceAll("+", "_");
  const outFile = join(resultsDir, `${stamp}.json`);
  await writeFile(outFile, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`eval: wrote ${outFile}\n`);

  if (args.failOnRegression && report.baseline_comparison?.is_regression) {
    process.stderr.write("eval: regression detected (--fail-on-regression).\n");
    process.exit(1);
  }
}

main().catch((err: unknown) => {
  process.stderr.write(`eval: ${String(err)}\n`);
  process.exit(1);
});
