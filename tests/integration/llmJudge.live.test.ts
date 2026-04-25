import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";
import { runLlmJudgeIfConfigured } from "../../src/eval/llmJudge.js";

// Mirrors the EvalReport.llm_judge consumer contract: an array of rows with a
// numeric score map plus an optional rationale.
const JudgeResponseSchema = z.array(
  z.object({
    scores: z.record(z.number()),
    rationale: z.string().optional(),
  }),
);

const hasKey =
  typeof process.env.ANTHROPIC_API_KEY === "string" &&
  process.env.ANTHROPIC_API_KEY.trim().length > 0;

let tmpDir: string | null = null;

afterEach(async () => {
  if (tmpDir !== null) {
    await rm(tmpDir, { recursive: true, force: true });
    tmpDir = null;
  }
});

describe("runLlmJudgeIfConfigured (live Anthropic)", () => {
  it.skipIf(!hasKey)(
    "returns rows that match the EvalReport.llm_judge shape against the real API",
    async () => {
      tmpDir = await mkdtemp(join(tmpdir(), "c2n-llm-live-"));
      const samplesDir = join(tmpDir, "samples");
      await mkdir(samplesDir, { recursive: true });
      await writeFile(
        join(tmpDir, "patterns.json"),
        JSON.stringify({
          sample_dir: "samples",
          pages_analyzed: 1,
          patterns: [
            {
              pattern_id: "p1",
              pattern_type: "macro",
              description: "Confluence info macro should map to a Notion callout block.",
              example_snippets: ['<ac:structured-macro ac:name="info"/>'],
              source_pages: ["1"],
              frequency: 1,
            },
          ],
        }),
        "utf8",
      );

      const out = await runLlmJudgeIfConfigured({ outputDir: tmpDir, samplesDir });
      expect(out).not.toBeNull();
      const parsed = JudgeResponseSchema.safeParse(out);
      expect(parsed.success, parsed.success ? "" : parsed.error.message).toBe(true);
    },
    60_000,
  );
});
