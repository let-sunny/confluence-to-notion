import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, statSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const maxBytes = 2 * 1024 * 1024;
const cliJs = join(repoRoot, "dist/cli.js");

function runBuiltCli(args: string[]): string {
  return execFileSync(process.execPath, [cliJs, ...args], {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, NO_COLOR: "1" },
  });
}

describe("CLI distribution (built dist/cli.js)", () => {
  it("prints a semver version", () => {
    const out = runBuiltCli(["--version"]).trim();
    expect(out).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("help output mentions primary workflow commands", () => {
    const out = runBuiltCli(["--help"]);
    expect(out).toContain("fetch");
    expect(out).toContain("convert");
    expect(out).toContain("validate-output");
  });

  it("runs through a bin-style symlink (npm installs the bin as a symlink to dist/cli.js)", () => {
    const dir = mkdtempSync(join(tmpdir(), "c2n-symlink-"));
    const shim = join(dir, "c2n");
    try {
      symlinkSync(cliJs, shim);
      const out = execFileSync(process.execPath, [shim, "--version"], {
        cwd: dir,
        encoding: "utf8",
        env: { ...process.env, NO_COLOR: "1" },
      }).trim();
      expect(out).toMatch(/^\d+\.\d+\.\d+/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("keeps published CLI bundles under 2MB each", () => {
    for (const rel of ["dist/cli.js", "dist/mcp.js"] as const) {
      const bytes = statSync(join(repoRoot, rel)).size;
      expect(bytes, rel).toBeLessThan(maxBytes);
    }
  });
});
