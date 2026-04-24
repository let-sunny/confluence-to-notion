import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { FinalRulesetSchema } from "../../src/agentOutput/finalRuleset.js";
import { finalizeProposalsToRules } from "../../src/cli/finalize.js";

let tmp: string | null = null;

afterEach(async () => {
  if (tmp) {
    await rm(tmp, { recursive: true, force: true });
    tmp = null;
  }
});

describe("finalizeProposalsToRules", () => {
  it("writes rules.json with enabled rules from proposals", async () => {
    tmp = await mkdtemp(join(tmpdir(), "c2n-fin-"));
    const proposalsPath = join(tmp, "proposals.json");
    const rulesPath = join(tmp, "rules.json");
    const proposals = {
      source_patterns_file: "output/patterns.json",
      rules: [
        {
          rule_id: "rule:macro:toc",
          source_pattern_id: "macro:toc",
          source_description: "TOC macro",
          notion_block_type: "table_of_contents",
          mapping_description: "Map to TOC block",
          example_input: '<ac:structured-macro ac:name="toc"/>',
          example_output: { type: "table_of_contents", table_of_contents: { color: "default" } },
          confidence: "high" as const,
        },
      ],
    };
    await writeFile(proposalsPath, JSON.stringify(proposals), "utf8");

    const { ruleCount } = await finalizeProposalsToRules(proposalsPath, rulesPath);
    expect(ruleCount).toBe(1);

    const raw = await readFile(rulesPath, "utf8");
    const parsed = FinalRulesetSchema.parse(JSON.parse(raw));
    expect(parsed.source).toBe("output/patterns.json");
    expect(parsed.rules).toHaveLength(1);
    expect(parsed.rules[0]?.enabled).toBe(true);
    expect(parsed.rules[0]?.rule_id).toBe("rule:macro:toc");
  });
});
