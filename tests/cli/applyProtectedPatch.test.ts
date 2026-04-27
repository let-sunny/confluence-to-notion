import { execSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = join(__dirname, "..", "..");
const SCRIPT_PATH = join(REPO_ROOT, "scripts", "develop.sh");

// Extract the apply_protected_patch function from scripts/develop.sh so we
// can exercise it without running the whole orchestration. Sourcing the full
// script would trigger argv parsing, branch creation, and preflight checks.
function extractApplyProtectedPatch(): string {
  const content = readFileSync(SCRIPT_PATH, "utf8");
  const match = content.match(/^apply_protected_patch\(\) \{[\s\S]*?^\}/m);
  if (!match) throw new Error("apply_protected_patch function not found in scripts/develop.sh");
  return match[0];
}

interface RunResult {
  status: number;
  stdout: string;
  stderr: string;
}

function runHarness(repoDir: string, patchBody: string | null, fnCode: string): RunResult {
  const outputDir = join(repoDir, "output", "dev");
  mkdirSync(outputDir, { recursive: true });
  const patchFile = join(outputDir, "protected-paths.patch");
  if (patchBody !== null) {
    writeFileSync(patchFile, patchBody);
  }

  const script = `
set -uo pipefail
cd "${repoDir}"
OUTPUT_DIR="output/dev"
FROM_STEP=1
${fnCode}
apply_protected_patch 2 "test"
`;

  try {
    const stdout = execSync("bash", {
      input: script,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    });
    return { status: 0, stdout, stderr: "" };
  } catch (err) {
    const e = err as { status?: number; stdout?: Buffer | string; stderr?: Buffer | string };
    return {
      status: typeof e.status === "number" ? e.status : 1,
      stdout: e.stdout ? e.stdout.toString() : "",
      stderr: e.stderr ? e.stderr.toString() : "",
    };
  }
}

function initGitRepo(dir: string): void {
  execSync("git init -q", { cwd: dir });
  execSync("git config user.email test@example.com", { cwd: dir });
  execSync("git config user.name test", { cwd: dir });
  execSync("git config commit.gpgsign false", { cwd: dir });
}

function commitFile(dir: string, relPath: string, content: string, message: string): void {
  const abs = join(dir, relPath);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content);
  execSync(`git add -- "${relPath}"`, { cwd: dir });
  execSync(`git commit -q -m "${message}"`, { cwd: dir });
}

describe("apply_protected_patch (scripts/develop.sh)", () => {
  let repoDir: string;
  const fnCode = extractApplyProtectedPatch();

  beforeEach(() => {
    repoDir = mkdtempSync(join(tmpdir(), "c2n-apply-protected-patch-"));
    initGitRepo(repoDir);
  });

  afterEach(() => {
    rmSync(repoDir, { recursive: true, force: true });
  });

  it("(a) clean apply: applies the patch and removes the patch file", () => {
    commitFile(repoDir, "target.md", "old line\n", "init");

    const patch = `--- a/target.md
+++ b/target.md
@@ -1 +1 @@
-old line
+new line
`;

    const result = runHarness(repoDir, patch, fnCode);

    expect(result.status).toBe(0);
    expect(readFileSync(join(repoDir, "target.md"), "utf8")).toBe("new line\n");
    expect(existsSync(join(repoDir, "output", "dev", "protected-paths.patch"))).toBe(false);
    expect(result.stdout).toContain("applied successfully");
  });

  it("(b) already applied: reverse-check passes, logs 'already applied', removes the patch file, returns 0", () => {
    // Commit the file already containing the post-patch content. The patch
    // forward-applies cleanly to "old line" but the working tree already has
    // "new line", so forward apply fails and reverse apply succeeds — meaning
    // the patch is already in the tree (likely self-applied by an agent).
    commitFile(repoDir, "target.md", "new line\n", "already-applied");

    const patch = `--- a/target.md
+++ b/target.md
@@ -1 +1 @@
-old line
+new line
`;

    const result = runHarness(repoDir, patch, fnCode);

    expect(result.status).toBe(0);
    expect(readFileSync(join(repoDir, "target.md"), "utf8")).toBe("new line\n");
    expect(existsSync(join(repoDir, "output", "dev", "protected-paths.patch"))).toBe(false);
    expect(result.stdout).toMatch(/already applied/i);
  });

  it("(c) genuinely broken patch: fails loud and preserves the patch file", () => {
    commitFile(repoDir, "target.md", "completely unrelated content\n", "init");

    const patch = `--- a/target.md
+++ b/target.md
@@ -1 +1 @@
-old line
+new line
`;

    const result = runHarness(repoDir, patch, fnCode);

    expect(result.status).not.toBe(0);
    expect(existsSync(join(repoDir, "output", "dev", "protected-paths.patch"))).toBe(true);
    const combined = result.stdout + result.stderr;
    expect(combined).toMatch(/git apply failed|does not apply|patch failed/i);
  });
});
