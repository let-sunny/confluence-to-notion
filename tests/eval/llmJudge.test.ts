import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runLlmJudgeIfConfigured } from "../../src/eval/llmJudge.js";

describe("runLlmJudgeIfConfigured", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    process.env.ANTHROPIC_API_KEY = undefined;
  });

  it("returns null when ANTHROPIC_API_KEY is unset", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-llm-"));
    await mkdir(dir, { recursive: true });
    await writeFile(
      join(dir, "patterns.json"),
      '{"sample_dir":"s","pages_analyzed":1,"patterns":[]}',
      "utf8",
    );
    const out = await runLlmJudgeIfConfigured({ outputDir: dir, samplesDir: join(dir, "s") });
    expect(out).toBeNull();
  });

  it("parses judge JSON from the Anthropic response shape", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const dir = await mkdtemp(join(tmpdir(), "c2n-llm-"));
    await mkdir(dir, { recursive: true });
    await writeFile(
      join(dir, "patterns.json"),
      JSON.stringify({
        sample_dir: "samples",
        pages_analyzed: 1,
        patterns: [
          {
            pattern_id: "p1",
            pattern_type: "macro",
            description: "d",
            example_snippets: ['<ac:structured-macro ac:name="info"/>'],
            source_pages: ["1"],
            frequency: 1,
          },
        ],
      }),
      "utf8",
    );

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify({
            content: [
              {
                type: "text",
                text: '[{"scores":{"relevance":0.8,"specificity":0.7,"actionability":0.9},"rationale":"ok"}]',
              },
            ],
          }),
      })) as unknown as typeof fetch,
    );

    const out = await runLlmJudgeIfConfigured({ outputDir: dir, samplesDir: join(dir, "samples") });
    expect(Array.isArray(out)).toBe(true);
    const row = (out as Array<{ scores: Record<string, number> }>)[0];
    expect(row?.scores?.relevance).toBeCloseTo(0.8, 5);
  });
});
