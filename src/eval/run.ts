import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { compareToBaseline, loadPreviousEvalReport } from "./baseline.js";
import { runEvalCore } from "./comparator.js";
import { runLlmJudgeIfConfigured } from "./llmJudge.js";
import type { EvalReport } from "./report.js";
import { validateEvalAgentOutputs } from "./schemaValidation.js";

export interface EvalCliArgs {
  outputDir: string;
  evalResultsDir: string;
  samplesDir?: string;
  llmJudge: boolean;
  failOnRegression: boolean;
}

/** Parse argv shaped like `[node, <script>, ...tail]` (no `eval` subcommand token). */
export function parseEvalArgvTail(argv: string[]): EvalCliArgs {
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

export async function runEvalWithArgs(args: EvalCliArgs): Promise<number> {
  const resultsDir = resolve(args.evalResultsDir);
  const previous = await loadPreviousEvalReport(resultsDir);

  if (args.llmJudge && args.samplesDir === undefined) {
    process.stderr.write("--llm-judge requires <samples_dir> as the third positional argument.\n");
    return 1;
  }

  await validateEvalAgentOutputs(args.outputDir);

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
    return 1;
  }
  return 0;
}
