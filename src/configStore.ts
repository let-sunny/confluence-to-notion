import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import envPaths from "env-paths";
import { z } from "zod";

export class ConfigStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigStoreError";
  }
}

export const ConfluenceCredsSchema = z.object({
  baseUrl: z.string().min(1),
  email: z.string().min(1),
  apiToken: z.string().min(1),
});

export const NotionCredsSchema = z.object({
  token: z.string().min(1),
  rootPageId: z.string().min(1),
});

export const ProfileSchema = z.object({
  confluence: ConfluenceCredsSchema,
  notion: NotionCredsSchema,
});

export const ConfigSchema = z.object({
  currentProfile: z.string().min(1).default("default"),
  profiles: z.record(z.string(), ProfileSchema).default({}),
});

export type ConfluenceCreds = z.infer<typeof ConfluenceCredsSchema>;
export type NotionCreds = z.infer<typeof NotionCredsSchema>;
export type Profile = z.infer<typeof ProfileSchema>;
export type Config = z.infer<typeof ConfigSchema>;

export interface ConfigStoreOptions {
  configDir?: string;
}

const IS_WINDOWS = process.platform === "win32";

function resolveConfigDir(opts?: ConfigStoreOptions): string {
  if (opts?.configDir !== undefined && opts.configDir.length > 0) return opts.configDir;
  return envPaths("c2n", { suffix: "" }).config;
}

export function getConfigPath(opts?: ConfigStoreOptions): { dir: string; file: string } {
  const dir = resolveConfigDir(opts);
  return { dir, file: join(dir, "config.json") };
}

function emptyConfig(): Config {
  return { currentProfile: "default", profiles: {} };
}

export function readConfig(opts?: ConfigStoreOptions): Config {
  const { file } = getConfigPath(opts);
  if (!existsSync(file)) return emptyConfig();
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch (e) {
    throw new ConfigStoreError(`Cannot read config file at ${file}: ${String(e)}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch (e) {
    throw new ConfigStoreError(`Invalid JSON in config file ${file}: ${String(e)}`);
  }
  const result = ConfigSchema.safeParse(parsed);
  if (!result.success) {
    throw new ConfigStoreError(
      `Config file ${file} does not match schema: ${result.error.message}`,
    );
  }
  return result.data;
}

export function writeConfig(config: Config, opts?: ConfigStoreOptions): void {
  const { dir, file } = getConfigPath(opts);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  if (!IS_WINDOWS) {
    try {
      chmodSync(dir, 0o700);
    } catch {
      // best-effort: directory may have been created by something else
    }
  }
  const json = `${JSON.stringify(config, null, 2)}\n`;
  writeFileSync(file, json, { encoding: "utf8", mode: 0o600 });
  if (!IS_WINDOWS) {
    chmodSync(file, 0o600);
  }
}

export function upsertProfile(name: string, profile: Profile, opts?: ConfigStoreOptions): void {
  const validated = ProfileSchema.parse(profile);
  const cfg = readConfig(opts);
  cfg.profiles[name] = validated;
  writeConfig(cfg, opts);
}

export function setCurrentProfile(name: string, opts?: ConfigStoreOptions): void {
  if (name.length === 0) {
    throw new ConfigStoreError("Profile name must not be empty.");
  }
  const cfg = readConfig(opts);
  cfg.currentProfile = name;
  writeConfig(cfg, opts);
}

export function resolveProfileName(profile: string | undefined, opts?: ConfigStoreOptions): string {
  if (profile !== undefined && profile.length > 0) return profile;
  const fromEnv = process.env.C2N_PROFILE?.trim();
  if (fromEnv !== undefined && fromEnv.length > 0) return fromEnv;
  const { file } = getConfigPath(opts);
  if (existsSync(file)) {
    try {
      const cfg = readConfig(opts);
      if (cfg.currentProfile.length > 0) return cfg.currentProfile;
    } catch {
      // fall through to default
    }
  }
  return "default";
}

function envValue(key: string): string | undefined {
  const v = process.env[key];
  if (v === undefined) return undefined;
  const trimmed = v.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function readProfile(name: string, opts?: ConfigStoreOptions): Profile | undefined {
  const cfg = readConfig(opts);
  return cfg.profiles[name];
}

function pickField<T>(envVal: T | undefined, fileVal: T | undefined): T | undefined {
  return envVal !== undefined ? envVal : fileVal;
}

function describeMissing(missing: string[]): string {
  return missing.length === 1
    ? `Missing required credential: ${missing[0]}`
    : `Missing required credentials: ${missing.join(", ")}`;
}

export interface GetCredsOptions extends ConfigStoreOptions {}

export function getConfluenceCreds(profile?: string, opts?: GetCredsOptions): ConfluenceCreds {
  const name = resolveProfileName(profile, opts);
  const stored = readProfile(name, opts)?.confluence;

  const baseUrl = pickField(envValue("CONFLUENCE_BASE_URL"), stored?.baseUrl);
  const email = pickField(envValue("CONFLUENCE_EMAIL"), stored?.email);
  const apiToken = pickField(
    envValue("CONFLUENCE_API_TOKEN") ?? envValue("CONFLUENCE_TOKEN"),
    stored?.apiToken,
  );

  const missing: string[] = [];
  if (baseUrl === undefined) missing.push("CONFLUENCE_BASE_URL");
  if (email === undefined) missing.push("CONFLUENCE_EMAIL");
  if (apiToken === undefined) missing.push("CONFLUENCE_API_TOKEN");
  if (missing.length > 0) {
    throw new ConfigStoreError(
      `${describeMissing(missing)} (profile '${name}'). Run \`c2n init\` or set the env var(s).`,
    );
  }

  return { baseUrl, email, apiToken } as ConfluenceCreds;
}

export function getNotionCreds(profile?: string, opts?: GetCredsOptions): NotionCreds {
  const name = resolveProfileName(profile, opts);
  const stored = readProfile(name, opts)?.notion;

  const token = pickField(envValue("NOTION_TOKEN") ?? envValue("NOTION_API_TOKEN"), stored?.token);
  const rootPageId = pickField(envValue("NOTION_ROOT_PAGE_ID"), stored?.rootPageId);

  const missing: string[] = [];
  if (token === undefined) missing.push("NOTION_TOKEN");
  if (rootPageId === undefined) missing.push("NOTION_ROOT_PAGE_ID");
  if (missing.length > 0) {
    throw new ConfigStoreError(
      `${describeMissing(missing)} (profile '${name}'). Run \`c2n init\` or set the env var(s).`,
    );
  }

  return { token, rootPageId } as NotionCreds;
}

// Re-exported for tests / future consumers that want to compose paths.
export { dirname };
