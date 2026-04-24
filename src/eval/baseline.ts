import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { type BaselineComparison, type EvalReport, EvalReportSchema } from "./report.js";

const DEFAULT_COVERAGE_THRESHOLD = 0.05;
const DEFAULT_LLM_JUDGE_THRESHOLD = 0.3;

/** Newest valid snapshot in `resultsDir`, or null. Skips corrupt files. */
export async function loadPreviousEvalReport(resultsDir: string): Promise<EvalReport | null> {
  let names: string[];
  try {
    names = await readdir(resultsDir);
  } catch {
    return null;
  }
  const snapshots = names.filter((n) => n.endsWith(".json")).sort((a, b) => a.localeCompare(b));
  for (let i = snapshots.length - 1; i >= 0; i -= 1) {
    const name = snapshots[i];
    if (name === undefined) continue;
    try {
      const raw = await readFile(join(resultsDir, name), "utf8");
      const parsed = EvalReportSchema.safeParse(JSON.parse(raw) as unknown);
      if (parsed.success) return parsed.data;
    } catch {}
  }
  return null;
}

function llmJudgeGrandMean(judge: unknown): number | null {
  if (!Array.isArray(judge) || judge.length === 0) return null;
  const values: number[] = [];
  for (const row of judge) {
    if (row && typeof row === "object" && "scores" in row) {
      const scores = (row as { scores?: Record<string, unknown> }).scores;
      if (scores && typeof scores === "object") {
        for (const v of Object.values(scores)) {
          if (typeof v === "number") values.push(v);
        }
      }
    }
  }
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

export function compareToBaseline(
  current: EvalReport,
  previous: EvalReport | null,
  coverageThreshold = DEFAULT_COVERAGE_THRESHOLD,
  llmJudgeThreshold = DEFAULT_LLM_JUDGE_THRESHOLD,
): BaselineComparison {
  const thresholds_used: Record<string, number> = {
    semantic_coverage: coverageThreshold,
    llm_judge: llmJudgeThreshold,
  };

  if (previous === null) {
    return {
      previous_timestamp: null,
      coverage_delta: 0.0,
      llm_judge_mean_delta: null,
      regressions: [],
      thresholds_used,
      is_regression: false,
    };
  }

  const regressions: string[] = [];

  const curCov = current.semantic_coverage?.coverage_ratio ?? null;
  const prevCov = previous.semantic_coverage?.coverage_ratio ?? null;
  let coverage_delta = 0.0;
  if (curCov !== null && prevCov !== null) {
    coverage_delta = curCov - prevCov;
    if (coverage_delta <= -coverageThreshold) {
      regressions.push("semantic_coverage");
    }
  }

  const curJ = llmJudgeGrandMean(current.llm_judge);
  const prevJ = llmJudgeGrandMean(previous.llm_judge);
  let llm_judge_mean_delta: number | null = null;
  if (curJ !== null && prevJ !== null) {
    llm_judge_mean_delta = curJ - prevJ;
    if (llm_judge_mean_delta <= -llmJudgeThreshold) {
      regressions.push("llm_judge");
    }
  }

  return {
    previous_timestamp: previous.timestamp,
    coverage_delta,
    llm_judge_mean_delta,
    regressions,
    thresholds_used,
    is_regression: regressions.length > 0,
  };
}
