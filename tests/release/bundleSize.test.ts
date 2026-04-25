import { existsSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..", "..");
const cliPath = resolve(repoRoot, "dist", "cli.js");
const mcpPath = resolve(repoRoot, "dist", "mcp.js");

const MAX_BUNDLE_BYTES = 3 * 1024 * 1024;

describe("published bundle size guard", () => {
  it("keeps dist/cli.js + dist/mcp.js below 3 MB", () => {
    if (!existsSync(cliPath) || !existsSync(mcpPath)) {
      console.warn(
        "[bundleSize.test] dist/cli.js or dist/mcp.js missing — run `pnpm build` to enforce this guard locally. Skipping.",
      );
      return;
    }

    const total = statSync(cliPath).size + statSync(mcpPath).size;
    expect(total).toBeLessThan(MAX_BUNDLE_BYTES);
  });
});
