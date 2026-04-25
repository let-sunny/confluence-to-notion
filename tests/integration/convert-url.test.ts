import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { RunStatusSchema, slugForUrl } from "../../src/runs/index.js";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const cliJs = join(repoRoot, "dist/cli.js");
const tsupCli = join(repoRoot, "node_modules", "tsup", "dist", "cli-default.js");

let tmpDir: string | null = null;

afterEach(async () => {
  if (tmpDir !== null) {
    await rm(tmpDir, { recursive: true, force: true });
    tmpDir = null;
  }
});

describe("c2n convert --url (built dist/cli.js)", () => {
  beforeAll(() => {
    execFileSync(process.execPath, [tsupCli], { cwd: repoRoot, stdio: "inherit" });
  }, 120_000);

  it("writes converted page + status + report under output/runs/<slug>/", async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "c2n-convert-url-"));
    const inputDir = join(tmpDir, "input");
    const rulesPath = join(tmpDir, "rules.json");
    const outputDir = join(tmpDir, "output");
    await mkdir(inputDir, { recursive: true });
    await mkdir(outputDir, { recursive: true });

    const pageId = "111";
    await writeFile(join(inputDir, `${pageId}.xhtml`), "<p>hello convert-url</p>\n", "utf8");
    // Minimal payload that satisfies FinalRulesetSchema (src/agentOutput/finalRuleset.ts):
    // `source` is a non-empty string, `rules` defaults to [].
    await writeFile(
      rulesPath,
      `${JSON.stringify({ source: "integration-test", rules: [] }, null, 2)}\n`,
      "utf8",
    );

    // src/cli/convert.ts resolves --input / --rules via path.join(process.cwd(), opt),
    // which does not anchor on absolute second args; use relative paths against cwd.
    // MSW is intentionally not wired here: convert only reads local XHTML and never
    // performs HTTP. See tests/integration/fetch-url-msw.test.ts for the HTTP path.
    const url = "https://cwiki.apache.org/confluence/display/FOO/Bar";
    execFileSync(
      process.execPath,
      [cliJs, "convert", "--input", "input", "--rules", "rules.json", "--url", url],
      {
        cwd: tmpDir,
        encoding: "utf8",
        env: { ...process.env, NO_COLOR: "1" },
      },
    );

    const slug = slugForUrl(url);
    const runDir = join(outputDir, "runs", slug);

    const convertedRaw = await readFile(join(runDir, "converted", `${pageId}.json`), "utf8");
    expect(() => JSON.parse(convertedRaw)).not.toThrow();

    const statusRaw = await readFile(join(runDir, "status.json"), "utf8");
    const status = RunStatusSchema.parse(JSON.parse(statusRaw));
    expect(status.convert.status).toBe("done");
    expect(status.convert.count ?? 0).toBeGreaterThanOrEqual(1);

    const report = await readFile(join(runDir, "report.md"), "utf8");
    expect(report).toContain("**convert**: done");
  }, 120_000);
});
