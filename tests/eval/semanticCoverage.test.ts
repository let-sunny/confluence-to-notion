import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { DiscoveryOutput } from "../../src/agentOutput/schemas.js";
import { analyzeCoverage } from "../../src/eval/semanticCoverage.js";

function minimalPatterns(snippets: string[]): DiscoveryOutput {
  return {
    sample_dir: "samples",
    pages_analyzed: 1,
    patterns: [
      {
        pattern_id: "p1",
        pattern_type: "macro",
        description: "test",
        example_snippets: snippets,
        source_pages: ["1"],
        frequency: 1,
      },
    ],
  };
}

describe("analyzeCoverage", () => {
  it("reports full coverage when sample keys appear in pattern snippets", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-semcov-"));
    await writeFile(join(dir, "a.xhtml"), '<ac:structured-macro ac:name="info" />', "utf8");
    const patterns = minimalPatterns(['<ac:structured-macro ac:name="info" />']);
    const report = await analyzeCoverage(dir, patterns);
    expect(report.pages_analyzed).toBe(1);
    expect(report.sample_elements).toContain("macro:info");
    expect(report.covered_elements).toContain("macro:info");
    expect(report.coverage_ratio).toBe(1);
  });

  it("reports partial coverage when samples use macros missing from patterns", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-semcov-"));
    await writeFile(join(dir, "a.xhtml"), '<ac:structured-macro ac:name="panel" />', "utf8");
    const patterns = minimalPatterns(['<ac:structured-macro ac:name="info" />']);
    const report = await analyzeCoverage(dir, patterns);
    expect(report.sample_elements).toContain("macro:panel");
    expect(report.covered_elements).not.toContain("macro:panel");
    expect(report.coverage_ratio).toBe(0);
  });

  it("throws when the samples directory has no .xhtml files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-semcov-"));
    await expect(analyzeCoverage(dir, minimalPatterns([]))).rejects.toThrow(/no \.xhtml files/);
  });
});
