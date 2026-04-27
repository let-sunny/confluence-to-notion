import { readFile, readdir } from "node:fs/promises";
import { extname, join } from "node:path";
import type { Command } from "commander";
import { FinalRulesetSchema } from "../agentOutput/finalRuleset.js";
import { convertXhtmlToConversionResult } from "../converter/convertPage.js";
import { finalizeRun, startRun, updateStep, writeConvertedPage } from "../runs/index.js";

export interface ConvertCliOptions {
  rules: string;
  input: string;
  url: string;
  profile?: string;
}

function outputRootDir(): string {
  return join(process.cwd(), "output");
}

export async function runConvertCommand(opts: ConvertCliOptions): Promise<void> {
  const rulesPath = join(process.cwd(), opts.rules);
  const inputDir = join(process.cwd(), opts.input);
  const rulesJson = JSON.parse(await readFile(rulesPath, "utf8")) as unknown;
  const ruleset = FinalRulesetSchema.parse(rulesJson);

  const entries = await readdir(inputDir, { withFileTypes: true });
  const xhtmlFiles = entries.filter(
    (e) => e.isFile() && extname(e.name).toLowerCase() === ".xhtml",
  );

  if (xhtmlFiles.length === 0) {
    process.stderr.write(`convert: no .xhtml files in ${inputDir}\n`);
    process.exit(1);
  }

  const { context } = await startRun({
    outputRoot: outputRootDir(),
    url: opts.url,
    sourceType: "page",
  });
  await updateStep(context, "convert", "running");
  try {
    let n = 0;
    for (const ent of xhtmlFiles) {
      const pageId = ent.name.replace(/\.xhtml$/i, "");
      const xhtml = await readFile(join(inputDir, ent.name), "utf8");
      const result = convertXhtmlToConversionResult(ruleset, xhtml, pageId);
      await writeConvertedPage(context, pageId, result);
      n += 1;
    }
    await updateStep(context, "convert", "done", { count: n });
    await finalizeRun(context);
    process.stdout.write(
      `convert: wrote ${String(n)} conversion(s) under ${context.paths.convertedDir}\n`,
    );
  } catch (e) {
    await updateStep(context, "convert", "failed");
    await finalizeRun(context);
    throw e;
  }
}

export function registerConvertCommands(program: Command): void {
  program
    .command("convert")
    .description("Convert XHTML pages to Notion blocks using finalized rules.")
    .option("--rules <path>", "path to rules.json", "output/rules.json")
    .option("--input <path>", "directory of XHTML files", "samples")
    .requiredOption(
      "--url <url>",
      "Confluence source URL; converted JSON lands under output/runs/<slug>/converted/",
    )
    .option("--profile <name>", "credential profile name (overrides C2N_PROFILE / currentProfile)")
    .action(async function (this: Command) {
      const o = this.opts<ConvertCliOptions>();
      try {
        await runConvertCommand(o);
      } catch (e) {
        process.stderr.write(`convert: ${String(e)}\n`);
        process.exit(1);
      }
    });
}
