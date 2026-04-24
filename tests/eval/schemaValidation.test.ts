import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { validateEvalAgentOutputs } from "../../src/eval/schemaValidation.js";

describe("validateEvalAgentOutputs", () => {
  it("rejects when patterns.json is missing", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-schema-"));
    await expect(validateEvalAgentOutputs(dir)).rejects.toThrow(/Cannot read file/);
  });

  it("passes when patterns and proposals validate", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-schema-"));
    const patterns = {
      sample_dir: "samples",
      pages_analyzed: 1,
      patterns: [
        {
          pattern_id: "p1",
          pattern_type: "t",
          description: "d",
          example_snippets: ["<p>x</p>"],
          source_pages: ["1"],
          frequency: 1,
        },
      ],
    };
    const proposals = {
      source_patterns_file: "output/patterns.json",
      rules: [],
    };
    await writeFile(join(dir, "patterns.json"), JSON.stringify(patterns), "utf8");
    await writeFile(join(dir, "proposals.json"), JSON.stringify(proposals), "utf8");
    await expect(validateEvalAgentOutputs(dir)).resolves.toBeUndefined();
  });
});
