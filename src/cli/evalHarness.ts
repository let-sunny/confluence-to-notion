import type { Command } from "commander";
import { type EvalCliArgs, runEvalWithArgs } from "../eval/run.js";

export function registerEvalHarness(program: Command): void {
  program
    .command("eval")
    .description(
      "Run semantic coverage, optional LLM-as-judge, and baseline comparison; writes eval_results/<timestamp>.json.",
    )
    .argument("[output_dir]", "discovery output root (patterns.json, proposals.json)", "output")
    .argument("[eval_results_dir]", "directory for JSON snapshots", "eval_results")
    .argument("[samples_dir]", "sample XHTML directory (required when using --llm-judge)")
    .option("--fail-on-regression", "exit 1 when baseline comparison reports a regression", false)
    .option("--llm-judge", "run Anthropic judge when ANTHROPIC_API_KEY is set", false)
    .action(async function (
      this: Command,
      output_dir: string,
      eval_results_dir: string,
      samples_dir: string | undefined,
    ) {
      const o = this.opts<{ llmJudge?: boolean; failOnRegression?: boolean }>();
      const baseArgs = {
        outputDir: output_dir,
        evalResultsDir: eval_results_dir,
        llmJudge: Boolean(o.llmJudge),
        failOnRegression: Boolean(o.failOnRegression),
      };
      const args: EvalCliArgs =
        samples_dir !== undefined && samples_dir.length > 0
          ? { ...baseArgs, samplesDir: samples_dir }
          : baseArgs;
      try {
        const code = await runEvalWithArgs(args);
        process.exit(code);
      } catch (e) {
        process.stderr.write(`eval: ${String(e)}\n`);
        process.exit(1);
      }
    });
}
