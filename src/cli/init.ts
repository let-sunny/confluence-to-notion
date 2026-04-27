import { type Command, Option } from "commander";
import { type ConfigStoreOptions, getConfigPath, upsertProfile } from "../configStore.js";
import { promptField } from "./promptInput.js";

export interface InitCliOptions {
  profile: string;
  confluenceBaseUrl?: string;
  confluenceEmail?: string;
  confluenceApiToken?: string;
  notionToken?: string;
  notionRootPageId?: string;
}

interface FieldSpec {
  flag: string;
  prompt: string;
  optionKey: keyof InitCliOptions;
  secret?: boolean;
}

const FIELDS: FieldSpec[] = [
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
    secret: true,
  },
  {
    flag: "--notion-token",
    prompt: "Notion integration token",
    optionKey: "notionToken",
    secret: true,
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

async function promptMissing(values: InitCliOptions): Promise<InitCliOptions> {
  for (const field of FIELDS) {
    const current = values[field.optionKey];
    if (typeof current === "string" && current.length > 0) continue;
    let answer: string;
    try {
      answer = await promptField({ prompt: field.prompt, secret: field.secret === true });
    } catch (e) {
      if (e instanceof Error && e.message === "Empty input") {
        throw new Error(`Empty input for ${field.flag}; aborting.`);
      }
      throw e;
    }
    (values as unknown as Record<string, string>)[field.optionKey] = answer;
  }
  return values;
}

export async function runInitCommand(opts: InitCliOptions): Promise<void> {
  const missing = FIELDS.filter((f) => {
    const v = opts[f.optionKey];
    return typeof v !== "string" || v.length === 0;
  });

  let resolved: InitCliOptions;
  if (missing.length === 0) {
    resolved = opts;
  } else if (process.stdin.isTTY) {
    resolved = await promptMissing({ ...opts });
  } else {
    const flagList = missing.map((f) => f.flag).join(", ");
    process.stderr.write(
      `init: missing required value(s): ${flagList}. Pass them as flags, set the matching env vars, or run interactively in a TTY.\n`,
    );
    process.exit(1);
    return;
  }

  const profile = {
    confluence: {
      baseUrl: resolved.confluenceBaseUrl ?? "",
      email: resolved.confluenceEmail ?? "",
      apiToken: resolved.confluenceApiToken ?? "",
    },
    notion: {
      token: resolved.notionToken ?? "",
      rootPageId: resolved.notionRootPageId ?? "",
    },
  };

  const storeOpts = resolveConfigDirOpts();
  upsertProfile(opts.profile, profile, storeOpts);
  const { file } = getConfigPath(storeOpts);
  process.stdout.write(`init: wrote profile '${opts.profile}' to ${file}\n`);
}

export function registerInitCommand(program: Command): void {
  program
    .command("init")
    .description("Create or update a c2n credential profile (interactive or via flags).")
    .addOption(new Option("--profile <name>", "profile name to write").default("default"))
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
    .addOption(new Option("--notion-token <token>", "Notion integration token").env("NOTION_TOKEN"))
    .addOption(
      new Option("--notion-root-page-id <id>", "Notion root page ID").env("NOTION_ROOT_PAGE_ID"),
    )
    .action(async function (this: Command) {
      const o = this.opts<InitCliOptions>();
      try {
        await runInitCommand(o);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        process.stderr.write(`init: ${msg}\n`);
        process.exit(1);
      }
    });
}
