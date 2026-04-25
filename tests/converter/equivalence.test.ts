// End-to-end equivalence gate for the deterministic XHTML → Notion
// converter. Each `tests/fixtures/converter/<id>.xhtml` is paired with a
// `<id>.expected.json` capturing the Notion blocks emitted by the Python
// converter at HEAD `112afeb~1`. The TS port must reproduce the same
// blocks for every page in the corpus, ordering of object keys aside —
// that's what the `toMatchNotionBlocks` matcher (registered in
// `tests/util/notionMatchers.ts` via vitest setupFiles) normalises.
//
// All fixtures share a single deterministic MockResolver instance. The
// converter only depends on the resolver for resolved-link short-circuits
// (page mentions, synced blocks); leaving the resolver empty forces the
// "unresolved → placeholder" code paths the Python baseline also exercised.
//
// The Python baseline was generated with every macro/element rule enabled
// (see `output/dev/preflight-drift.md`), so we mirror that here with
// `BASELINE_RULESET`. Without it, the converter would emit
// `unsupportedMacro` blocks for `code`, `info`, `expand`, etc., which the
// Python baseline never does.
//
// We also enforce the issue-157 acceptance criterion that the full corpus
// runs in under 30 seconds.

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FinalRuleset } from "../../src/agentOutput/finalRuleset.js";
import { convertXhtmlToNotionBlocks } from "../../src/converter/converter.js";
import { createMockResolver } from "../fixtures/mockResolver.js";

function ruleEntry(rule_id: string): FinalRuleset["rules"][number] {
  return {
    rule_id,
    source_pattern_id: rule_id.replace(/^rule:/, ""),
    source_description: "baseline rule",
    notion_block_type: "paragraph",
    mapping_description: "baseline equivalence",
    example_input: "<x/>",
    example_output: { type: "paragraph", paragraph: { rich_text: [] } },
    confidence: "high",
    enabled: true,
  };
}

const BASELINE_RULESET: FinalRuleset = {
  source: "tests/fixtures/converter (baseline equivalence)",
  rules: [
    "rule:element:heading",
    "rule:element:paragraph",
    "rule:element:list",
    "rule:element:ac-image",
    "rule:macro:toc",
    "rule:macro:jira",
    "rule:macro:code",
    "rule:macro:expand",
    "rule:macro:info",
    "rule:macro:note",
    "rule:macro:warning",
    "rule:macro:tip",
  ].map(ruleEntry),
};

const here = path.dirname(fileURLToPath(import.meta.url));
const fixturesDir = path.resolve(here, "..", "fixtures", "converter");

const MAX_DURATION_MS = 30_000;

function discoverFixtures(): { id: string; xhtmlPath: string; expectedPath: string }[] {
  const entries = readdirSync(fixturesDir);
  const xhtmlIds = entries
    .filter((name) => name.endsWith(".xhtml"))
    .map((name) => name.slice(0, -".xhtml".length))
    .sort();

  const expectedSet = new Set(
    entries
      .filter((name) => name.endsWith(".expected.json"))
      .map((name) => name.slice(0, -".expected.json".length)),
  );

  const missing = xhtmlIds.filter((id) => !expectedSet.has(id));
  if (missing.length > 0) {
    throw new Error(
      `Missing .expected.json for fixtures: ${missing.join(", ")} — every <id>.xhtml needs a paired <id>.expected.json`,
    );
  }

  return xhtmlIds.map((id) => ({
    id,
    xhtmlPath: path.join(fixturesDir, `${id}.xhtml`),
    expectedPath: path.join(fixturesDir, `${id}.expected.json`),
  }));
}

const fixtures = discoverFixtures();

// Fixture `29130800` still diverges from the Python baseline because the TS
// port emits a typed `unsupportedMacro` block for unknown macros (e.g. the
// `drawio` macro in this fixture), while the Python converter falls through
// to a paragraph with `[macro_name] text`. That's a deliberate TS-port
// design choice (see the `unsupportedMacro` fallback in
// `src/converter/converter.ts`) — not a parser issue. Tracking the broader
// fallback alignment as a separate follow-up; re-enable `29130800` once the
// fallback behaviour is reconciled.
//
// The other three fixtures previously pinned (27821303, 90000001, 90000007)
// were CDATA-handling divergences caused by parse5 running in HTML5 mode;
// after the parser swap to `@xmldom/xmldom` in `text/xml` mode (issue #165)
// they match the Python baseline and have been unpinned.
const KNOWN_FAILING_IDS = new Set(["29130800"]);

describe("converter equivalence vs Python baseline", () => {
  let suiteStart = 0;

  beforeAll(() => {
    expect(fixtures.length).toBeGreaterThanOrEqual(30);
    suiteStart = Date.now();
  });

  afterAll(() => {
    const elapsed = Date.now() - suiteStart;
    expect(elapsed).toBeLessThan(MAX_DURATION_MS);
  });

  it.each(fixtures)("$id", ({ id, xhtmlPath, expectedPath }) => {
    const xhtml = readFileSync(xhtmlPath, "utf8");
    const expected = JSON.parse(readFileSync(expectedPath, "utf8")) as unknown;
    const result = convertXhtmlToNotionBlocks(xhtml, {
      resolver: createMockResolver(),
      ruleset: BASELINE_RULESET,
      pageId: id,
    });
    if (KNOWN_FAILING_IDS.has(id)) {
      // Pin known divergence as a *failed equality* — if the converter
      // ever starts matching Python on this fixture, this assertion will
      // flip and prompt removing the id from KNOWN_FAILING_IDS.
      expect(() => expect(result.blocks).toMatchNotionBlocks(expected)).toThrow(
        /Notion blocks did not match/,
      );
      return;
    }
    expect(result.blocks).toMatchNotionBlocks(expected);
  });
});
