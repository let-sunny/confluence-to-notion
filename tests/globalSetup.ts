import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const tsupCli = join(repoRoot, "node_modules", "tsup", "dist", "cli-default.js");

export default async function setup(): Promise<void> {
  // Run tsup via Node so Windows CI does not require `pnpm` on PATH for spawnSync.
  // execFileSync throws on non-zero exit, which aborts vitest before any test loads.
  execFileSync(process.execPath, [tsupCli], { cwd: repoRoot, stdio: "inherit" });
}
