/**
 * Zod contracts for discover-pipeline agent JSON files (patterns, proposals, scout sources).
 * Aligned with `.claude/agents/discover/*.md` embedded schemas and the historical Python
 * `agents/schemas.py` models.
 */
import { z } from "zod";

export const DiscoveryPatternSchema = z.object({
  pattern_id: z.string().min(1),
  pattern_type: z.string().min(1),
  description: z.string().min(1),
  example_snippets: z.array(z.string()).min(1),
  source_pages: z.array(z.string()).min(1),
  frequency: z.number().int().positive(),
});
export type DiscoveryPattern = z.infer<typeof DiscoveryPatternSchema>;

export const DiscoveryOutputSchema = z.object({
  sample_dir: z.string().min(1),
  pages_analyzed: z.number().int().positive(),
  patterns: z.array(DiscoveryPatternSchema).default([]),
});
export type DiscoveryOutput = z.infer<typeof DiscoveryOutputSchema>;

export const ProposedRuleSchema = z.object({
  rule_id: z.string().min(1),
  source_pattern_id: z.string().min(1),
  source_description: z.string().min(1),
  notion_block_type: z.string().min(1),
  mapping_description: z.string().min(1),
  example_input: z.string(),
  example_output: z.record(z.string(), z.unknown()),
  confidence: z.enum(["high", "medium", "low"]),
});
export type ProposedRule = z.infer<typeof ProposedRuleSchema>;

export const ProposerOutputSchema = z.object({
  source_patterns_file: z.string().min(1),
  rules: z.array(ProposedRuleSchema).default([]),
});
export type ProposerOutput = z.infer<typeof ProposerOutputSchema>;

export const ScoutSourceSchema = z.object({
  wiki_url: z.string().min(1),
  space_key: z.string().min(1),
  macro_density: z.number().min(0).max(1),
  sample_macros: z.array(z.string()),
  page_count: z.number().int().min(0),
  accessible: z.boolean(),
  fetched_at: z.string().nullable().optional(),
});
export type ScoutSource = z.infer<typeof ScoutSourceSchema>;

export const ScoutOutputSchema = z.object({
  sources: z.array(ScoutSourceSchema).default([]),
});
export type ScoutOutput = z.infer<typeof ScoutOutputSchema>;

export const AgentOutputSchemaNameSchema = z.enum(["discovery", "proposer", "scout"]);
export type AgentOutputSchemaName = z.infer<typeof AgentOutputSchemaNameSchema>;

export function parseAgentOutput(schema: AgentOutputSchemaName, data: unknown): unknown {
  switch (schema) {
    case "discovery":
      return DiscoveryOutputSchema.parse(data);
    case "proposer":
      return ProposerOutputSchema.parse(data);
    case "scout":
      return ScoutOutputSchema.parse(data);
    default: {
      const _exhaustive: never = schema;
      return _exhaustive;
    }
  }
}
