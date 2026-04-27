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

const APPLY_PROTECTED_PATCH_FN = "apply_protected_patch";

/** Escape a literal for use inside a RegExp constructor. */
function escapeRegExpLiteral(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Extract a top-level `name() { ... }` function body from a bash script (first
 * match only). Used to unit-test helpers without sourcing the full orchestrator.
 */
function extractBashNamedFunction(script: string, functionName: string): string {
  const re = new RegExp(`^${escapeRegExpLiteral(functionName)}\\(\\) \\{[\\s\\S]*?^\\}`, "m");
  const match = script.match(re);
  if (!match) {
    throw new Error(`${functionName} function not found in scripts/develop.sh`);
  }
  return match[0];
}

/** Combined stdout/stderr patterns for a loud `git apply` failure from the harness. */
const GIT_APPLY_LOUD_FAILURE = /git apply failed|does not apply|patch failed/i;

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
  // On Windows, git's default core.autocrlf=true rewrites checked-out files
  // to CRLF, breaking byte-for-byte assertions on file contents after `git apply`.
  execSync("git config core.autocrlf false", { cwd: dir });
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
  const fnCode = extractBashNamedFunction(
    readFileSync(SCRIPT_PATH, "utf8"),
    APPLY_PROTECTED_PATCH_FN,
  );

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
    expect(result.stdout).toContain("handoff artifact was:");
    expect(result.stdout).toContain("protected-paths.patch");
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
    expect(combined).toMatch(GIT_APPLY_LOUD_FAILURE);
  });
});
