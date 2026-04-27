import type { Command } from "commander";
import { type ConfigStoreOptions, readConfig } from "../configStore.js";

function resolveConfigDirOpts(): ConfigStoreOptions {
  const dir = process.env.C2N_CONFIG_DIR?.trim();
  return dir !== undefined && dir.length > 0 ? { configDir: dir } : {};
}

export async function runProfilesList(): Promise<void> {
  const storeOpts = resolveConfigDirOpts();
  const cfg = readConfig(storeOpts);
  const names = Object.keys(cfg.profiles).sort();

  if (names.length === 0) {
    process.stdout.write("profiles: no profiles configured. Run `c2n init` to create one.\n");
    return;
  }

  for (const name of names) {
    const marker = name === cfg.currentProfile ? "* " : "  ";
    process.stdout.write(`${marker}${name}\n`);
  }
}

export function registerProfilesCommands(program: Command): void {
  const profiles = program
    .command("profiles")
    .description("Manage credential profiles stored in the c2n config file.");

  profiles
    .command("list")
    .description("List profile names; the current profile is marked with a leading '* '.")
    .action(async () => {
      await runProfilesList();
    });
}
