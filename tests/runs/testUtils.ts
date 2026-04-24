import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

let lastRoot: string | null = null;

export async function tempOutputRoot(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "c2n-runs-test-"));
  lastRoot = dir;
  return dir;
}

export async function rmTempOutputRoot(): Promise<void> {
  if (lastRoot) {
    await rm(lastRoot, { recursive: true, force: true });
    lastRoot = null;
  }
}
