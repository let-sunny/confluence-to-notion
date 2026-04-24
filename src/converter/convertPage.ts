import type { FinalRuleset } from "../agentOutput/finalRuleset.js";
import { type ConversionResult, ConversionResultSchema } from "./schemas.js";

/**
 * Minimal XHTML → Notion conversion for the CLI until the full deterministic
 * converter from PR 2/5 lands. Produces a single paragraph block from visible text.
 */
export function convertXhtmlToConversionResult(
  _rules: FinalRuleset,
  xhtml: string,
  pageId: string,
): ConversionResult {
  const plain = xhtml
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const content = (plain.length > 0 ? plain : `page ${pageId}`).slice(0, 1990);
  const block = {
    type: "paragraph",
    paragraph: {
      rich_text: [{ type: "text", text: { content: content } }],
    },
  };
  return ConversionResultSchema.parse({ blocks: [block], unresolved: [], usedRules: {} });
}
