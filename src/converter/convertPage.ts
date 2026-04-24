import type { FinalRuleset } from "../agentOutput/finalRuleset.js";
import { convertXhtmlToNotionBlocks } from "./converter.js";
import type { ConversionResult } from "./schemas.js";

/**
 * CLI entry point used by `c2n convert`. Delegates to the deterministic
 * converter from {@link convertXhtmlToNotionBlocks} with the finalized
 * ruleset. The production resolver (ResolutionStore / Resolver) is threaded
 * in by the caller once the resolve pass lands in 2c; for now we hand an
 * undefined resolver so unresolved items surface with placeholder URLs.
 */
export function convertXhtmlToConversionResult(
  rules: FinalRuleset,
  xhtml: string,
  pageId: string,
): ConversionResult {
  return convertXhtmlToNotionBlocks(xhtml, { ruleset: rules, pageId });
}
