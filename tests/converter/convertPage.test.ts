import { describe, expect, it } from "vitest";
import type { FinalRuleset } from "../../src/agentOutput/finalRuleset.js";
import { convertXhtmlToConversionResult } from "../../src/converter/convertPage.js";

const emptyRuleset: FinalRuleset = { source: "test", rules: [] };

describe("convertXhtmlToConversionResult", () => {
  it("preserves inline annotations from the real converter", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "<p>Hello <b>world</b></p>", "42");
    expect(result.blocks).toHaveLength(1);
    expect(result.blocks[0]).toMatchObject({
      type: "paragraph",
      paragraph: {
        rich_text: [
          { type: "text", text: { content: "Hello " } },
          { type: "text", text: { content: "world" }, annotations: { bold: true } },
        ],
      },
    });
  });

  it("emits one paragraph per <p> rather than concatenating them", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "<p>a</p><p>b</p>", "1");
    expect(result.blocks).toHaveLength(2);
    expect(result.blocks[0]).toMatchObject({
      type: "paragraph",
      paragraph: { rich_text: [{ type: "text", text: { content: "a" } }] },
    });
    expect(result.blocks[1]).toMatchObject({
      type: "paragraph",
      paragraph: { rich_text: [{ type: "text", text: { content: "b" } }] },
    });
  });

  it("returns zero blocks for whitespace-only input", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "   \n\t  ", "99");
    expect(result.blocks).toEqual([]);
  });

  it("returns empty usedRules and unresolved for a plain paragraph", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "<p>x</p>", "1");
    expect(result.unresolved).toEqual([]);
    expect(result.usedRules).toEqual({});
  });
});
