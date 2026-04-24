/**
 * TypeScript eval pipeline entry (non-CLI). Prefer `pnpm exec c2n eval …` in scripts.
 */
import { parseEvalArgvTail, runEvalWithArgs } from "./run.js";

async function main(): Promise<void> {
  const code = await runEvalWithArgs(parseEvalArgvTail(process.argv));
  process.exit(code);
}

main().catch((err: unknown) => {
  process.stderr.write(`eval: ${String(err)}\n`);
  process.exit(1);
});
