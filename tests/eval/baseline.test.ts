import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { compareToBaseline, loadPreviousEvalReport } from "../../src/eval/baseline.js";
import type { EvalReport, SemanticCoverage } from "../../src/eval/report.js";

function coverage(ratio: number): SemanticCoverage {
  return {
    pages_analyzed: 1,
    sample_elements: ["macro:x"],
    covered_elements: ratio >= 0.5 ? ["macro:x"] : [],
    coverage_ratio: ratio,
  };
}

function report(partial: Omit<EvalReport, "baseline_comparison">): EvalReport {
  return { ...partial, baseline_comparison: null };
}

describe("compareToBaseline", () => {
  it("treats missing previous snapshot as no regression", () => {
    const current = report({
      timestamp: "t1",
      prompt_changed: false,
      semantic_coverage: coverage(1),
      llm_judge: null,
    });
    const cmp = compareToBaseline(current, null);
    expect(cmp.is_regression).toBe(false);
    expect(cmp.previous_timestamp).toBeNull();
    expect(cmp.regressions).toEqual([]);
  });

  it("detects semantic coverage regression beyond the default threshold", () => {
    const previous = report({
      timestamp: "t0",
      prompt_changed: false,
      semantic_coverage: coverage(1),
      llm_judge: null,
    });
    const current = report({
      timestamp: "t1",
      prompt_changed: false,
      semantic_coverage: coverage(0.89),
      llm_judge: null,
    });
    const cmp = compareToBaseline(current, previous);
    expect(cmp.is_regression).toBe(true);
    expect(cmp.regressions).toContain("semantic_coverage");
    expect(cmp.coverage_delta).toBeCloseTo(-0.11, 5);
  });
});

describe("loadPreviousEvalReport", () => {
  it("returns the newest parseable snapshot and skips corrupt files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "c2n-eval-"));
    await writeFile(join(dir, "old.json"), "not json", "utf8");
    const good: EvalReport = {
      timestamp: "2026-01-02T00:00:00.000Z",
      prompt_changed: false,
      semantic_coverage: null,
      llm_judge: null,
      baseline_comparison: null,
    };
    await writeFile(join(dir, "2026-01-02.json"), JSON.stringify(good), "utf8");
    await writeFile(join(dir, "newer-bad.json"), "{", "utf8");
    const loaded = await loadPreviousEvalReport(dir);
    expect(loaded?.timestamp).toBe(good.timestamp);
  });
});
