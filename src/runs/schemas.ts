import { z } from "zod";

export const StepStatusSchema = z.enum(["pending", "running", "done", "skipped", "failed"]);
export type StepStatus = z.infer<typeof StepStatusSchema>;

export const StepRecordSchema = z.object({
  status: StepStatusSchema,
  at: z.string().nullable(),
  count: z.number().nullable(),
  warnings: z.number().nullable(),
});
export type StepRecord = z.infer<typeof StepRecordSchema>;

export const RunStepNameSchema = z.enum(["fetch", "discover", "convert", "migrate"]);
export type RunStepName = z.infer<typeof RunStepNameSchema>;

export const RunStatusSchema = z.object({
  fetch: StepRecordSchema,
  discover: StepRecordSchema,
  convert: StepRecordSchema,
  migrate: StepRecordSchema,
});
export type RunStatus = z.infer<typeof RunStatusSchema>;

export const RulesSourceSchema = z.enum(["reused", "regenerated", "generated"]);
export type RulesSource = z.infer<typeof RulesSourceSchema>;

export const SourceInfoSchema = z
  .object({
    url: z.string(),
    type: z.string(),
    root_id: z.string().nullable().optional(),
    notion_target: z.record(z.string(), z.unknown()).nullable().optional(),
    rules_source: RulesSourceSchema.nullable().optional(),
    rules_generated_at: z.string().nullable().optional(),
  })
  .passthrough();
export type SourceInfo = z.infer<typeof SourceInfoSchema>;

export const RunResolutionSchema = z.record(z.string(), z.string());
export type RunResolution = z.infer<typeof RunResolutionSchema>;

export const MappingSchema = z.object({
  confluencePageId: z.string().min(1),
  notionPageId: z.string().min(1),
  notionUrl: z.string().optional(),
  recordedAt: z.coerce.date().default(() => new Date()),
});
export type Mapping = z.infer<typeof MappingSchema>;

export function defaultRunStatus(): RunStatus {
  const pending = (): StepRecord => ({
    status: "pending",
    at: null,
    count: null,
    warnings: null,
  });
  return {
    fetch: pending(),
    discover: pending(),
    convert: pending(),
    migrate: pending(),
  };
}
