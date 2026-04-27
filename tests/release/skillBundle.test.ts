import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..", "..");
const bundleDir = resolve(repoRoot, "skills", "c2n-migrate");
const skillPath = resolve(bundleDir, "SKILL.md");
const readmePath = resolve(bundleDir, "README.md");

const REQUIRED_TOOL_NAMES = [
  "c2n_fetch_page",
  "c2n_convert_page",
  "c2n_list_unresolved",
  "c2n_propose_resolution",
  "c2n_finalize_proposals",
  "c2n_record_migration",
  "c2n_list_runs",
] as const;

function parseFrontmatter(source: string): Record<string, string> {
  if (!source.startsWith("---\n")) {
    throw new Error("SKILL.md must start with a YAML frontmatter block (---)");
  }
  const end = source.indexOf("\n---", 4);
  if (end === -1) {
    throw new Error("SKILL.md frontmatter is not terminated by `---`");
  }
  const block = source.slice(4, end);
  const out: Record<string, string> = {};
  for (const rawLine of block.split("\n")) {
    const line = rawLine.trimEnd();
    if (line === "" || line.startsWith("#")) continue;
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    const key = line.slice(0, colon).trim();
    const value = line.slice(colon + 1).trim();
    out[key] = value;
  }
  return out;
}

describe("skills/c2n-migrate bundle integrity", () => {
  it("ships SKILL.md with name+description frontmatter", () => {
    expect(existsSync(skillPath)).toBe(true);
    const source = readFileSync(skillPath, "utf8");
    const fm = parseFrontmatter(source);
    expect(fm.name).toBeTruthy();
    expect(fm.description).toBeTruthy();
  });

  it("references every c2n MCP tool the playbook drives", () => {
    const source = readFileSync(skillPath, "utf8");
    for (const tool of REQUIRED_TOOL_NAMES) {
      expect(source, `SKILL.md should mention ${tool}`).toContain(tool);
    }
  });

  it("ships README.md that points at the migration playbook", () => {
    expect(existsSync(readmePath)).toBe(true);
    const source = readFileSync(readmePath, "utf8");
    expect(source).toMatch(/docs\/migration-playbook\.md/);
  });
});
