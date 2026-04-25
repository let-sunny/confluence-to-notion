import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runLlmJudgeIfConfigured } from "../../src/eval/llmJudge.js";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const llmJudgeSourcePath = join(repoRoot, "src/eval/llmJudge.ts");

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

  it("sends a prompt that pins JSON-only instruction wording, the three current dimensions, and the 0..1 score range", async () => {
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

    const fetchSpy = vi.fn(async (_url: unknown, _init?: unknown) => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          content: [
            {
              type: "text",
              text: '[{"scores":{"relevance":0.5,"specificity":0.5,"actionability":0.5},"rationale":"x"}]',
            },
          ],
        }),
    }));
    vi.stubGlobal("fetch", fetchSpy as unknown as typeof fetch);

    await runLlmJudgeIfConfigured({ outputDir: dir, samplesDir: join(dir, "samples") });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const call = fetchSpy.mock.calls[0];
    const init = call?.[1] as RequestInit | undefined;
    expect(typeof init?.body).toBe("string");
    const body = JSON.parse(init?.body as string) as {
      messages: Array<{ role: string; content: string }>;
    };
    const prompt = body.messages[0]?.content ?? "";

    // (a-1) JSON-only instruction wording — pinned verbatim.
    expect(prompt).toContain("Return ONLY a JSON array (no markdown fences)");
    // (a-2) Three current scoring dimensions appear verbatim.
    expect(prompt).toContain("relevance");
    expect(prompt).toContain("specificity");
    expect(prompt).toContain("actionability");
    // (a-3) Score range is 0..1 floats.
    expect(prompt).toContain("0 (worst) to 1 (best)");
  });

  it("documents historical-parity deltas in the source header (commit 15c53d3, 4 Korean dimensions, language/target/score-scale/SDK)", async () => {
    const source = await readFile(llmJudgeSourcePath, "utf8");
    // The doc-block must live near the top of the file (before the first export).
    const exportIdx = source.indexOf("export ");
    expect(exportIdx).toBeGreaterThan(0);
    const header = source.slice(0, exportIdx);

    // Citation of historical commit + Python source.
    expect(header).toContain("15c53d3");
    expect(header.toLowerCase()).toContain("llm_judge.py");

    // Original 4 Korean dimensions, named verbatim.
    expect(header).toContain("information_preservation");
    expect(header).toContain("notion_idiom");
    expect(header).toContain("structure");
    expect(header).toContain("readability");

    // Original 1-5 integer score scale.
    expect(header).toMatch(/1[\s-]*5/);

    // Intentional deltas: language (CLAUDE.md > Language), target (post-#86 patterns),
    // score scale (0..1 floats), and the fetch-over-SDK budget decision.
    expect(header).toMatch(/CLAUDE\.md.*Language/);
    expect(header).toContain("#86");
    expect(header).toContain("0..1");
    expect(header).toContain("@anthropic-ai/sdk");
    expect(header).toContain("cli-distribution.test.ts");
  });
});
