import * as readline from "node:readline/promises";
import { type Command, Option } from "commander";
import {
  type ConfigStoreOptions,
  type ConfluenceCreds,
  type NotionCreds,
  type Profile,
  getConfigPath,
  readConfig,
  resolveProfileName,
  upsertProfile,
} from "../configStore.js";

export interface ConfluenceAuthOptions {
  profile?: string;
  confluenceBaseUrl?: string;
  confluenceEmail?: string;
  confluenceApiToken?: string;
}

export interface NotionAuthOptions {
  profile?: string;
  notionToken?: string;
  notionRootPageId?: string;
}

interface FieldSpec<K extends string> {
  flag: string;
  prompt: string;
  optionKey: K;
}

const CONFLUENCE_FIELDS: FieldSpec<keyof ConfluenceAuthOptions>[] = [
  {
    flag: "--confluence-base-url",
    prompt: "Confluence base URL",
    optionKey: "confluenceBaseUrl",
  },
  {
    flag: "--confluence-email",
    prompt: "Confluence account email",
    optionKey: "confluenceEmail",
  },
  {
    flag: "--confluence-api-token",
    prompt: "Confluence API token",
    optionKey: "confluenceApiToken",
  },
];

const NOTION_FIELDS: FieldSpec<keyof NotionAuthOptions>[] = [
  {
    flag: "--notion-token",
    prompt: "Notion integration token",
    optionKey: "notionToken",
  },
  {
    flag: "--notion-root-page-id",
    prompt: "Notion root page ID",
    optionKey: "notionRootPageId",
  },
];

function resolveConfigDirOpts(): ConfigStoreOptions {
  const dir = process.env.C2N_CONFIG_DIR?.trim();
  return dir !== undefined && dir.length > 0 ? { configDir: dir } : {};
}

async function promptMissing<T extends Record<string, unknown>>(
  values: T,
  fields: FieldSpec<keyof T & string>[],
): Promise<T> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    for (const field of fields) {
      const current = values[field.optionKey];
      if (typeof current === "string" && current.length > 0) continue;
      const answer = (await rl.question(`${field.prompt}: `)).trim();
      if (answer.length === 0) {
        throw new Error(`Empty input for ${field.flag}; aborting.`);
      }
      (values as Record<string, unknown>)[field.optionKey] = answer;
    }
    return values;
  } finally {
    rl.close();
  }
}

async function resolveFields<T extends Record<string, unknown>>(
  opts: T,
  fields: FieldSpec<keyof T & string>[],
  subcommandLabel: string,
): Promise<T> {
  const missing = fields.filter((f) => {
    const v = opts[f.optionKey];
    return typeof v !== "string" || v.length === 0;
  });

  if (missing.length === 0) return opts;
  if (process.stdin.isTTY) return promptMissing({ ...opts }, fields);

  const flagList = missing.map((f) => f.flag).join(", ");
  process.stderr.write(
    `auth ${subcommandLabel}: missing required value(s): ${flagList}. Pass them as flags, set the matching env vars, or run interactively in a TTY.\n`,
  );
  process.exit(1);
  // Unreachable in production; keeps type narrowing happy when process.exit is mocked.
  throw new Error("process.exit did not terminate");
}

function requireExistingProfile(
  name: string,
  storeOpts: ConfigStoreOptions,
  subcommandLabel: string,
): Profile {
  const cfg = readConfig(storeOpts);
  const existing = cfg.profiles[name];
  if (!existing) {
    process.stderr.write(
      `auth ${subcommandLabel}: profile '${name}' does not exist; run \`c2n init --profile ${name}\` first.\n`,
    );
    process.exit(1);
    throw new Error("process.exit did not terminate");
  }
  return existing;
}

export async function runConfluenceAuth(opts: ConfluenceAuthOptions): Promise<void> {
  const storeOpts = resolveConfigDirOpts();
  const name = resolveProfileName(opts.profile, storeOpts);
  const existing = requireExistingProfile(name, storeOpts, "confluence");

  const resolved = await resolveFields({ ...opts }, CONFLUENCE_FIELDS, "confluence");

  const confluence: ConfluenceCreds = {
    baseUrl: resolved.confluenceBaseUrl ?? "",
    email: resolved.confluenceEmail ?? "",
    apiToken: resolved.confluenceApiToken ?? "",
  };

  const next: Profile = { ...existing, confluence };
  upsertProfile(name, next, storeOpts);
  const { file } = getConfigPath(storeOpts);
  process.stdout.write(`auth: updated confluence for profile '${name}' at ${file}\n`);
}

export async function runNotionAuth(opts: NotionAuthOptions): Promise<void> {
  const storeOpts = resolveConfigDirOpts();
  const name = resolveProfileName(opts.profile, storeOpts);
  const existing = requireExistingProfile(name, storeOpts, "notion");

  const resolved = await resolveFields({ ...opts }, NOTION_FIELDS, "notion");

  const notion: NotionCreds = {
    token: resolved.notionToken ?? "",
    rootPageId: resolved.notionRootPageId ?? "",
  };

  const next: Profile = { ...existing, notion };
  upsertProfile(name, next, storeOpts);
  const { file } = getConfigPath(storeOpts);
  process.stdout.write(`auth: updated notion for profile '${name}' at ${file}\n`);
}

export function registerAuthCommands(program: Command): void {
  const auth = program
    .command("auth")
    .description("Update credentials for an existing c2n profile (Confluence or Notion).");

  auth
    .command("confluence")
    .description("Update only the Confluence credentials of an existing profile.")
    .addOption(
      new Option(
        "--profile <name>",
        "profile name to update (defaults to C2N_PROFILE or currentProfile)",
      ),
    )
    .addOption(
      new Option("--confluence-base-url <url>", "Confluence base URL").env("CONFLUENCE_BASE_URL"),
    )
    .addOption(
      new Option("--confluence-email <email>", "Confluence account email").env("CONFLUENCE_EMAIL"),
    )
    .addOption(
      new Option("--confluence-api-token <token>", "Confluence API token").env(
        "CONFLUENCE_API_TOKEN",
      ),
    )
    .action(async function (this: Command) {
      await runConfluenceAuth(this.opts<ConfluenceAuthOptions>());
    });

  auth
    .command("notion")
    .description("Update only the Notion credentials of an existing profile.")
    .addOption(
      new Option(
        "--profile <name>",
        "profile name to update (defaults to C2N_PROFILE or currentProfile)",
      ),
    )
    .addOption(new Option("--notion-token <token>", "Notion integration token").env("NOTION_TOKEN"))
    .addOption(
      new Option("--notion-root-page-id <id>", "Notion root page ID").env("NOTION_ROOT_PAGE_ID"),
    )
    .action(async function (this: Command) {
      await runNotionAuth(this.opts<NotionAuthOptions>());
    });
}
