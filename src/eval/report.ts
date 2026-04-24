import { z } from "zod";

/** Matches `SemanticCoverage` in historical `agents/schemas.py`. */
export const SemanticCoverageSchema = z.object({
  pages_analyzed: z.number().int().positive(),
  sample_elements: z.array(z.string()),
  covered_elements: z.array(z.string()),
  coverage_ratio: z.number().min(0).max(1),
});
export type SemanticCoverage = z.infer<typeof SemanticCoverageSchema>;

/** Matches `BaselineComparison` in historical `agents/schemas.py`. */
export const BaselineComparisonSchema = z.object({
  previous_timestamp: z.string().nullable(),
  coverage_delta: z.number(),
  llm_judge_mean_delta: z.number().nullable(),
  regressions: z.array(z.string()),
  thresholds_used: z.record(z.string(), z.number()),
  is_regression: z.boolean(),
});
export type BaselineComparison = z.infer<typeof BaselineComparisonSchema>;

/** Matches `EvalReport` in historical `agents/schemas.py` (JSON field names). */
export const EvalReportSchema = z.object({
  timestamp: z.string(),
  prompt_changed: z.boolean(),
  semantic_coverage: SemanticCoverageSchema.nullable(),
  llm_judge: z.unknown().nullable().optional(),
  baseline_comparison: BaselineComparisonSchema.nullable(),
});
export type EvalReport = z.infer<typeof EvalReportSchema>;
