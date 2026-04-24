// Port of `src/confluence_to_notion/converter/schemas.py` (see
// `git show 112afeb^:src/confluence_to_notion/converter/schemas.py`).
// The Python Pydantic models are the behavioural contract. Field names move
// from snake_case to camelCase at the TS boundary — the on-disk JSON contract
// still follows what the Python side emitted, so downstream JSON readers
// expecting snake_case will need a separate adapter (out of scope for this
// slice).

import { z } from "zod";

export const NotionPropertyTypeSchema = z.enum([
  "title",
  "rich_text",
  "select",
  "date",
  "people",
  "url",
]);
export type NotionPropertyType = z.infer<typeof NotionPropertyTypeSchema>;

export const ResolutionEntrySchema = z.object({
  resolvedBy: z.enum(["user_input", "ai_inference", "api_call", "auto_lookup", "notion_migration"]),
  value: z.record(z.string(), z.unknown()),
  confidence: z.number().min(0).max(1).optional(),
  resolvedAt: z.coerce.date().default(() => new Date()),
});
export type ResolutionEntry = z.infer<typeof ResolutionEntrySchema>;

export const UnresolvedItemSchema = z.object({
  kind: z.enum(["macro", "jira_server", "page_link", "synced_block", "table"]),
  identifier: z.string(),
  sourcePageId: z.string(),
  contextXhtml: z.string().nullable().optional(),
});
export type UnresolvedItem = z.infer<typeof UnresolvedItemSchema>;

export const ResolutionDataSchema = z.object({
  entries: z.record(z.string(), ResolutionEntrySchema).default({}),
});
export type ResolutionData = z.infer<typeof ResolutionDataSchema>;

export const ConversionResultSchema = z.object({
  blocks: z.array(z.record(z.string(), z.unknown())).default([]),
  unresolved: z.array(UnresolvedItemSchema).default([]),
  usedRules: z.record(z.string(), z.number()).default({}),
});
export type ConversionResult = z.infer<typeof ConversionResultSchema>;

export const TableRuleSchema = z.object({
  isDatabase: z.boolean(),
  titleColumn: z.string().nullable().optional(),
  columnTypes: z.record(z.string(), NotionPropertyTypeSchema).nullable().optional(),
});
export type TableRule = z.infer<typeof TableRuleSchema>;

export const TableRuleSetSchema = z
  .object({
    rules: z.record(z.string(), TableRuleSchema).default({}),
  })
  .superRefine((data, ctx) => {
    for (const [key, rule] of Object.entries(data.rules)) {
      if (key === "") {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["rules", key],
          message: "TableRuleSet rule key must be a non-empty signature",
        });
        continue;
      }
      if (rule.titleColumn != null) {
        const columns = key.split("|");
        if (!columns.includes(rule.titleColumn)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["rules", key, "titleColumn"],
            message: `titleColumn '${rule.titleColumn}' not in signature columns [${columns
              .map((c) => `'${c}'`)
              .join(", ")}]`,
          });
        }
      }
    }
  });
export type TableRuleSet = z.infer<typeof TableRuleSetSchema>;
