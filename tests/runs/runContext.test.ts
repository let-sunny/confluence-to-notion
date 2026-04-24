import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  appendLog,
  finalizeRun,
  formatRulesSummary,
  startRun,
  updateStep,
  writeConvertedPage,
  writeResolution,
  writeTableRules,
} from "../../src/runs/index.js";
import { rmTempOutputRoot, tempOutputRoot } from "./testUtils.js";

afterEach(async () => {
  vi.useRealTimers();
  await rmTempOutputRoot();
});

describe("run lifecycle", () => {
  it("persists source and status, updates a step, and renders report.md", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-19T10:53:24.391Z"));

    const outputRoot = await tempOutputRoot();
    const { context, source } = await startRun({
      outputRoot,
      url: "https://cwiki.apache.org/confluence/display/TEST/Integration+Page",
      sourceType: "page",
      rootId: null,
      notionTarget: { page_id: "test-parent-page-id" },
    });

    expect(source.url).toContain("cwiki.apache.org");
    await updateStep(context, "migrate", "done", { count: 2 });

    await finalizeRun(context);

    const report = await readFile(context.paths.reportMd, "utf8");
    expect(report).toContain("# Run Report");
    expect(report).toContain("**migrate**: done");
    expect(report).toContain("count=2");
    expect(report).toContain("2026-04-19T10:53:24.391Z");
  });

  it("allocates -2 suffix when the slug directory already exists", async () => {
    const outputRoot = await tempOutputRoot();
    const url = "https://cwiki.apache.org/confluence/display/TEST/Integration+Page";
    const first = await startRun({ outputRoot, url, sourceType: "page" });
    const second = await startRun({ outputRoot, url, sourceType: "page" });

    expect(first.context.slug).toBe("cwiki-integration-page");
    expect(second.context.slug).toBe("cwiki-integration-page-2");
  });

  it("writes resolution, converted JSON, table rules, and log lines under the run tree", async () => {
    const outputRoot = await tempOutputRoot();
    const { context } = await startRun({
      outputRoot,
      url: "https://example.atlassian.net/wiki/spaces/ENG/pages/1/T",
      sourceType: "tree",
    });

    await writeResolution(context, { "page_link:Foo": "notion-page-1" });
    await writeConvertedPage(context, "12345", { blocks: [{ object: "block" }] });
    await writeTableRules(context, { rules: {} });
    await appendLog(context, "migrate", "line one");
    await appendLog(context, "migrate", "line two");

    const resolution = JSON.parse(await readFile(context.paths.resolutionJson, "utf8")) as Record<
      string,
      string
    >;
    expect(resolution["page_link:Foo"]).toBe("notion-page-1");

    const converted = JSON.parse(
      await readFile(join(context.paths.convertedDir, "12345.json"), "utf8"),
    ) as { blocks: unknown[] };
    expect(converted.blocks).toHaveLength(1);

    const rules = JSON.parse(await readFile(context.paths.tableRulesJson, "utf8")) as {
      rules: Record<string, unknown>;
    };
    expect(rules.rules).toEqual({});

    const logText = await readFile(join(context.paths.logsDir, "migrate.log"), "utf8");
    expect(logText.trim().split("\n")).toEqual(["line one", "line two"]);
  });

  it("formatRulesSummary returns sorted lines or null when empty", () => {
    expect(formatRulesSummary({})).toBeNull();
    expect(formatRulesSummary({ b: 2, a: 1 })).toBe("- a: 1\n- b: 2");
  });

  it("finalizeRun appends Rules usage when rulesSummary is provided", async () => {
    const outputRoot = await tempOutputRoot();
    const { context } = await startRun({
      outputRoot,
      url: "https://example.atlassian.net/wiki/spaces/X/pages/1",
      sourceType: "page",
    });
    await finalizeRun(context, { rulesSummary: "- rule-a: 3\n- rule-b: 1" });
    const report = await readFile(context.paths.reportMd, "utf8");
    expect(report).toContain("## Rules usage");
    expect(report).toContain("- rule-a: 3");
  });
});
