// Architecture guard for the converter package. The deterministic converter
// must remain a self-contained pipeline of XHTML → Notion blocks; it must not
// reach into the Confluence client (HTTP I/O) or the Notion client (HTTP I/O)
// layers. If a future change accidentally introduces such an import we want
// CI to flag it before it lands.
//
// Strategy: walk every `.ts` file under `src/converter/` and assert no
// `from "..."` import string resolves into `src/confluence/...` or
// `src/notion/...`. We compare against the canonical absolute path to
// tolerate any depth of `../` prefixes.
//
// Resolution is purely string-based — no module loading — so the test is
// fast and won't trigger the converter's own runtime side effects.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const converterDir = path.join(repoRoot, "src", "converter");
const forbiddenDirs = [
  path.join(repoRoot, "src", "confluence"),
  path.join(repoRoot, "src", "notion"),
];

const importRegex = /from\s+["']([^"']+)["']/g;

function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      out.push(...listTsFiles(full));
    } else if (stats.isFile() && full.endsWith(".ts")) {
      out.push(full);
    }
  }
  return out;
}

function resolvesIntoForbidden(importer: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  const importerDir = path.dirname(importer);
  const resolved = path.resolve(importerDir, spec);
  for (const forbidden of forbiddenDirs) {
    const rel = path.relative(forbidden, resolved);
    if (!rel.startsWith("..") && !path.isAbsolute(rel)) {
      return forbidden;
    }
  }
  return null;
}

describe("converter architecture", () => {
  it("does not import from src/confluence or src/notion", () => {
    expect(existsSync(converterDir)).toBe(true);
    const files = listTsFiles(converterDir);
    expect(files.length).toBeGreaterThan(0);

    const violations: string[] = [];
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(importRegex)) {
        const spec = match[1];
        if (!spec) continue;
        const hit = resolvesIntoForbidden(file, spec);
        if (hit) {
          violations.push(
            `${path.relative(repoRoot, file)} imports "${spec}" which resolves into ${path.relative(repoRoot, hit)}/`,
          );
        }
      }
    }

    expect(violations).toEqual([]);
  });
});
