import { z } from "zod";

export const ConfigSchema = z.object({
  CONFLUENCE_EMAIL: z.string().min(1),
  CONFLUENCE_TOKEN: z.string().min(1),
  NOTION_TOKEN: z.string().min(1),
  ANTHROPIC_API_KEY: z.string().min(1),
});

export type Config = Readonly<z.infer<typeof ConfigSchema>>;

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }

  override toString(): string {
    return `${this.name}: ${this.message}`;
  }
}

export interface LoadConfigOptions {
  dotenvLoader?: (path?: string) => Record<string, string>;
}

export function loadConfig(opts: LoadConfigOptions = {}): Config {
  const fromDotenv = opts.dotenvLoader?.() ?? {};
  const merged: Record<string, string | undefined> = {
    ...process.env,
    ...fromDotenv,
  };

  const declarationOrderKeys = Object.keys(ConfigSchema.shape) as Array<
    keyof typeof ConfigSchema.shape
  >;

  const missing: string[] = [];
  const values: Record<string, string> = {};
  for (const key of declarationOrderKeys) {
    const raw = merged[key];
    if (typeof raw !== "string" || raw.length === 0) {
      missing.push(key);
    } else {
      values[key] = raw;
    }
  }

  if (missing.length > 0) {
    const message = missing.map((name) => `Missing required env var: ${name}`).join("\n");
    throw new ConfigError(message);
  }

  const parsed = ConfigSchema.safeParse(values);
  if (!parsed.success) {
    const message = parsed.error.issues
      .map((issue) => {
        const name = issue.path.join(".");
        return `Invalid env var: ${name} — ${issue.message}`;
      })
      .join("\n");
    throw new ConfigError(message);
  }

  return Object.freeze(parsed.data) as Config;
}
