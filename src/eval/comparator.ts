import { execSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { DiscoveryOutputSchema } from "../agentOutput/schemas.js";
import type { EvalReport } from "./report.js";
import { analyzeCoverage } from "./semanticCoverage.js";

export function detectPromptChanges(): boolean {
  try {
    const out = execSync("git diff --name-only HEAD~1 -- .claude/agents/", {
      encoding: "utf8",
      stdio: ["pipe", "pipe", "ignore"],
    });
    return out.trim().length > 0;
  } catch {
    return false;
  }
}

export async function runEvalCore(
  outputDir: string,
  samplesDir?: string,
): Promise<Pick<EvalReport, "timestamp" | "prompt_changed" | "semantic_coverage" | "llm_judge">> {
  const outAbs = resolve(outputDir);
  const patternsPath = join(outAbs, "patterns.json");
  const raw = await readFile(patternsPath, "utf8");
  const patterns = DiscoveryOutputSchema.parse(JSON.parse(raw) as unknown);
  const semantic_coverage =
    samplesDir !== undefined ? await analyzeCoverage(resolve(samplesDir), patterns) : null;
  return {
    timestamp: new Date().toISOString(),
    prompt_changed: detectPromptChanges(),
    semantic_coverage,
    llm_judge: null,
  };
}
