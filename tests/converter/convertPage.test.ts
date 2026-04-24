import { describe, expect, it } from "vitest";
import type { FinalRuleset } from "../../src/agentOutput/finalRuleset.js";
import { convertXhtmlToConversionResult } from "../../src/converter/convertPage.js";

const emptyRuleset: FinalRuleset = { source: "test", rules: [] };

describe("convertXhtmlToConversionResult", () => {
  it("strips markup into a single paragraph block", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "<p>Hello <b>world</b></p>", "42");
    expect(result.blocks).toHaveLength(1);
    expect(result.blocks[0]).toMatchObject({
      type: "paragraph",
      paragraph: {
        rich_text: [{ type: "text", text: { content: "Hello world" } }],
      },
    });
  });

  it("drops script and style bodies", () => {
    const result = convertXhtmlToConversionResult(
      emptyRuleset,
      "<p>a</p><script>evil()</script><style>.x{}</style><p>b</p>",
      "1",
    );
    expect(result.blocks[0]).toMatchObject({
      type: "paragraph",
      paragraph: {
        rich_text: [{ type: "text", text: { content: "a b" } }],
      },
    });
  });

  it("uses page id when there is no visible text", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "   \n\t  ", "99");
    expect(result.blocks[0]).toMatchObject({
      type: "paragraph",
      paragraph: {
        rich_text: [{ type: "text", text: { content: "page 99" } }],
      },
    });
  });

  it("returns empty usedRules and unresolved", () => {
    const result = convertXhtmlToConversionResult(emptyRuleset, "<p>x</p>", "1");
    expect(result.unresolved).toEqual([]);
    expect(result.usedRules).toEqual({});
  });
});
