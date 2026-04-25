// Failing unit tests for src/converter/converter.ts (issue item 5). The
// tests in this file are the Red phase for the main converter port; task:4
// makes them Green. They cover parse5 XML-mode namespace handling, entity
// decoding, macro dispatch specificity, the unsupportedMacro fallback, and
// CDATA preservation (issue #165).

import { describe, expect, it } from "vitest";
import type { FinalRuleset } from "../../src/agentOutput/finalRuleset.js";
import { convertXhtmlToNotionBlocks } from "../../src/converter/converter.js";
import { createMockResolver } from "../fixtures/mockResolver.js";

function convert(xhtml: string, ruleset?: FinalRuleset) {
  const resolver = createMockResolver();
  const options = ruleset ? { resolver, pageId: "1", ruleset } : { resolver, pageId: "1" };
  return convertXhtmlToNotionBlocks(xhtml, options);
}

function rulesetWith(ids: string[]): FinalRuleset {
  return {
    source: "tests/converter/converter.test.ts",
    rules: ids.map((rule_id) => ({
      rule_id,
      source_pattern_id: rule_id.replace(/^rule:/, ""),
      source_description: "test rule",
      notion_block_type: "paragraph",
      mapping_description: "test rule",
      example_input: "<x/>",
      example_output: { type: "paragraph", paragraph: { rich_text: [] } },
      confidence: "high",
      enabled: true,
    })),
  };
}

function firstParagraphText(blocks: Array<Record<string, unknown>>): string {
  const block = blocks[0] as {
    type?: string;
    paragraph?: { rich_text?: Array<{ text?: { content?: string } }> };
  };
  expect(block?.type).toBe("paragraph");
  const richText = block.paragraph?.rich_text ?? [];
  return richText.map((segment) => segment.text?.content ?? "").join("");
}

describe("convertXhtmlToNotionBlocks — parse5 XML-mode namespace handling", () => {
  it("walks ac:structured-macro with the info handler instead of dropping it", () => {
    const result = convert(
      '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>heads up</p></ac:rich-text-body></ac:structured-macro>',
    );
    expect(result.blocks.length).toBeGreaterThan(0);
    const callout = result.blocks[0] as { type?: string };
    expect(callout.type).toBe("callout");
  });

  it("walks ri:attachment inside ac:image and emits an image block", () => {
    const result = convert('<ac:image><ri:attachment ri:filename="diagram.png" /></ac:image>');
    expect(result.blocks.length).toBeGreaterThan(0);
    const image = result.blocks[0] as { type?: string; image?: { type?: string } };
    expect(image.type).toBe("image");
    expect(image.image?.type).toBe("external");
  });

  it("walks ac:layout / ac:layout-cell descendants and preserves their inner paragraphs", () => {
    const result = convert(
      '<ac:layout><ac:layout-section ac:type="single"><ac:layout-cell><p>layout body</p></ac:layout-cell></ac:layout-section></ac:layout>',
    );
    expect(result.blocks.length).toBeGreaterThan(0);
    expect(firstParagraphText(result.blocks as Array<Record<string, unknown>>)).toBe("layout body");
  });

  it("walks ri:user inside ac:link and produces a rich_text segment", () => {
    const result = convert('<p><ac:link><ri:user ri:userkey="abc123" /></ac:link></p>');
    expect(result.blocks.length).toBeGreaterThan(0);
    const block = result.blocks[0] as { type?: string; paragraph?: { rich_text?: unknown[] } };
    expect(block.type).toBe("paragraph");
    expect((block.paragraph?.rich_text ?? []).length).toBeGreaterThan(0);
  });
});

describe("convertXhtmlToNotionBlocks — entity decoding", () => {
  it("decodes &nbsp; into a NBSP (U+00A0) character in rich_text", () => {
    const result = convert("<p>a&nbsp;b</p>");
    expect(firstParagraphText(result.blocks as Array<Record<string, unknown>>)).toContain(" ");
  });

  it("decodes &ndash; into an en dash", () => {
    const result = convert("<p>a &ndash; b</p>");
    expect(firstParagraphText(result.blocks as Array<Record<string, unknown>>)).toContain("–");
  });

  it("decodes &hellip; into an ellipsis", () => {
    const result = convert("<p>wait&hellip;</p>");
    expect(firstParagraphText(result.blocks as Array<Record<string, unknown>>)).toContain("…");
  });

  it("decodes numeric hex entity &#x2019; into a right single quote", () => {
    const result = convert("<p>it&#x2019;s fine</p>");
    expect(firstParagraphText(result.blocks as Array<Record<string, unknown>>)).toContain("’");
  });
});

describe("convertXhtmlToNotionBlocks — macro handler dispatch order", () => {
  it("uses the specific info panel handler over the generic structured-macro fallback", () => {
    const result = convert(
      '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>note</p></ac:rich-text-body></ac:structured-macro>',
    );
    expect(result.blocks.length).toBe(1);
    const block = result.blocks[0] as {
      type?: string;
      callout?: { rich_text?: Array<{ text?: { content?: string } }> };
    };
    expect(block.type).toBe("callout");
    const calloutText = (block.callout?.rich_text ?? [])
      .map((segment) => segment.text?.content ?? "")
      .join("");
    expect(calloutText).toContain("note");
    // The specific handler should NOT also emit an unresolved macro item for the info panel.
    expect(
      result.unresolved.find((item) => item.kind === "macro" && item.identifier === "info"),
    ).toBeUndefined();
  });
});

describe("convertXhtmlToNotionBlocks — CDATA preservation (issue #165)", () => {
  it("preserves CDATA-wrapped text inside ac:plain-text-link-body as the link display text", () => {
    const xhtml =
      '<p><ac:link><ri:page ri:content-title="Real Page Title" /><ac:plain-text-link-body><![CDATA[Display Override]]></ac:plain-text-link-body></ac:link></p>';
    const result = convert(xhtml);
    const block = result.blocks[0] as {
      type?: string;
      paragraph?: { rich_text?: Array<{ text?: { content?: string } }> };
    };
    expect(block.type).toBe("paragraph");
    const segments = block.paragraph?.rich_text ?? [];
    const joined = segments.map((s) => s.text?.content ?? "").join("");
    expect(joined).toBe("Display Override");
    expect(joined).not.toBe("Real Page Title");
  });

  it("preserves CDATA-wrapped source inside ac:plain-text-body of a code macro verbatim", () => {
    const xhtml =
      '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">javascript</ac:parameter><ac:plain-text-body><![CDATA[const greet = (name) => `Hello, ${name}!`;\nconsole.log(greet("world"));]]></ac:plain-text-body></ac:structured-macro>';
    const result = convert(xhtml, rulesetWith(["rule:macro:code"]));
    expect(result.blocks).toHaveLength(1);
    const block = result.blocks[0] as {
      type?: string;
      code?: {
        language?: string;
        rich_text?: Array<{ text?: { content?: string } }>;
      };
    };
    expect(block.type).toBe("code");
    expect(block.code?.language).toBe("javascript");
    const content = block.code?.rich_text?.[0]?.text?.content ?? "";
    expect(content).toBe(
      'const greet = (name) => `Hello, ${name}!`;\nconsole.log(greet("world"));',
    );
    expect(content).not.toContain("]]>");
  });
});

describe("convertXhtmlToNotionBlocks — unknown macro fallback", () => {
  it("emits a typed unsupportedMacro block for an unknown macro rather than dropping it silently", () => {
    const xhtml =
      '<ac:structured-macro ac:name="totally-made-up"><ac:parameter ac:name="x">y</ac:parameter></ac:structured-macro>';
    const result = convert(xhtml);
    expect(result.blocks).toHaveLength(1);
    const block = result.blocks[0] as {
      type?: string;
      unsupportedMacro?: { name?: string; xhtml?: string };
    };
    expect(block.type).toBe("unsupportedMacro");
    expect(block.unsupportedMacro?.name).toBe("totally-made-up");
    expect(typeof block.unsupportedMacro?.xhtml).toBe("string");
    expect(block.unsupportedMacro?.xhtml?.length ?? 0).toBeGreaterThan(0);
    // Matching unresolved entry is recorded so the resolver pass can pick it up.
    expect(
      result.unresolved.some(
        (item) => item.kind === "macro" && item.identifier === "totally-made-up",
      ),
    ).toBe(true);
  });
});
