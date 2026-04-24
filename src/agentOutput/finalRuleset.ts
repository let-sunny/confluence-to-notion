/**
 * `output/rules.json` contract produced by `c2n finalize` from `output/proposals.json`.
 * Mirrors the historical `FinalRuleset` / `FinalRule` Pydantic models.
 */
import { z } from "zod";
import type { ProposedRule, ProposerOutput } from "./schemas.js";

export const FinalRuleSchema = z.object({
  rule_id: z.string().min(1),
  source_pattern_id: z.string().min(1),
  source_description: z.string().min(1),
  notion_block_type: z.string().min(1),
  mapping_description: z.string().min(1),
  example_input: z.string(),
  example_output: z.record(z.string(), z.unknown()),
  confidence: z.enum(["high", "medium", "low"]),
  enabled: z.boolean(),
});
export type FinalRule = z.infer<typeof FinalRuleSchema>;

export const FinalRulesetSchema = z.object({
  source: z.string().min(1),
  rules: z.array(FinalRuleSchema).default([]),
});
export type FinalRuleset = z.infer<typeof FinalRulesetSchema>;

function proposedToFinal(proposed: ProposedRule): FinalRule {
  return {
    ...proposed,
    enabled: true,
  };
}

export function finalRulesetFromProposerOutput(output: ProposerOutput): FinalRuleset {
  return {
    source: output.source_patterns_file,
    rules: output.rules.map(proposedToFinal),
  };
}
