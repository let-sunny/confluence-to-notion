import { readFile, readdir } from "node:fs/promises";
import { extname, join } from "node:path";
import type { DiscoveryOutput } from "../agentOutput/schemas.js";
import type { SemanticCoverage } from "./report.js";

function collectKeysFromXhtml(xhtml: string): Set<string> {
  const keys = new Set<string>();
  const macroRe = /<ac:structured-macro\b[^>]*\bac:name\s*=\s*"([^"]+)"/gi;
  for (const m of xhtml.matchAll(macroRe)) {
    const name = m[1];
    if (name) keys.add(`macro:${name}`);
  }
  const macroRe2 = /<ac:structured-macro\b[^>]*\bac:name\s*=\s*'([^']+)'/gi;
  for (const m of xhtml.matchAll(macroRe2)) {
    const name = m[1];
    if (name) keys.add(`macro:${name}`);
  }
  if (/<ac:link\b/i.test(xhtml)) keys.add("element:ac-link");
  if (/<ac:image\b/i.test(xhtml)) keys.add("element:ac-image");
  if (/<h[1-6]\b/i.test(xhtml)) keys.add("element:heading");
  if (/<\/?(ul|ol)\b/i.test(xhtml)) keys.add("element:list");
  if (/<(code|pre)\b/i.test(xhtml)) keys.add("element:code");
  if (/<table\b/i.test(xhtml)) keys.add("element:table");
  if (/<a\b/i.test(xhtml)) keys.add("element:link");
  return keys;
}

function patternKeys(patterns: DiscoveryOutput): Set<string> {
  const covered = new Set<string>();
  for (const pattern of patterns.patterns) {
    for (const snippet of pattern.example_snippets) {
      for (const k of collectKeysFromXhtml(snippet)) {
        covered.add(k);
      }
    }
  }
  return covered;
}

export async function analyzeCoverage(
  samplesDir: string,
  patterns: DiscoveryOutput,
): Promise<SemanticCoverage> {
  const entries = await readdir(samplesDir, { withFileTypes: true });
  const sampleFiles = entries
    .filter((e) => e.isFile() && extname(e.name).toLowerCase() === ".xhtml")
    .map((e) => e.name)
    .sort();
  if (sampleFiles.length === 0) {
    throw new Error(`no .xhtml files found in ${samplesDir}`);
  }

  const sampleKeys = new Set<string>();
  for (const name of sampleFiles) {
    const text = await readFile(join(samplesDir, name), "utf8");
    for (const k of collectKeysFromXhtml(text)) {
      sampleKeys.add(k);
    }
  }

  const pKeys = patternKeys(patterns);
  const covered = new Set<string>();
  for (const k of sampleKeys) {
    if (pKeys.has(k)) covered.add(k);
  }

  const ratio = sampleKeys.size > 0 ? covered.size / sampleKeys.size : 1.0;

  return {
    pages_analyzed: sampleFiles.length,
    sample_elements: [...sampleKeys].sort((a, b) => a.localeCompare(b)),
    covered_elements: [...covered].sort((a, b) => a.localeCompare(b)),
    coverage_ratio: ratio,
  };
}
