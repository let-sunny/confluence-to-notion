import type { Command } from "commander";
import {
  type ConfigStoreOptions,
  getConfigPath,
  readConfig,
  setCurrentProfile,
} from "../configStore.js";

function resolveConfigDirOpts(): ConfigStoreOptions {
  const dir = process.env.C2N_CONFIG_DIR?.trim();
  return dir !== undefined && dir.length > 0 ? { configDir: dir } : {};
}

export async function runUseCommand(name: string): Promise<void> {
  const storeOpts = resolveConfigDirOpts();
  const cfg = readConfig(storeOpts);
  if (!cfg.profiles[name]) {
    process.stderr.write(
      `use: profile '${name}' does not exist; run \`c2n init --profile ${name}\` first.\n`,
    );
    process.exit(1);
    throw new Error("process.exit did not terminate");
  }
  setCurrentProfile(name, storeOpts);
  const { file } = getConfigPath(storeOpts);
  process.stdout.write(`use: switched current profile to '${name}' in ${file}\n`);
}

export function registerUseCommand(program: Command): void {
  program
    .command("use <name>")
    .description("Switch the current profile to <name> (must already exist).")
    .action(async (name: string) => {
      await runUseCommand(name);
    });
}
