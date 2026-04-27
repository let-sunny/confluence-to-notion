import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  ConfigStoreError,
  getConfigPath,
  getConfluenceCreds,
  getNotionCreds,
  readConfig,
  resolveProfileName,
  setCurrentProfile,
  upsertProfile,
  writeConfig,
} from "../../src/configStore.js";

const ENV_KEYS = [
  "CONFLUENCE_BASE_URL",
  "CONFLUENCE_EMAIL",
  "CONFLUENCE_API_TOKEN",
  "CONFLUENCE_TOKEN",
  "NOTION_TOKEN",
  "NOTION_API_TOKEN",
  "NOTION_ROOT_PAGE_ID",
  "C2N_PROFILE",
  "XDG_CONFIG_HOME",
] as const;

let tmp: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-cs-"));
  savedEnv = {};
  for (const k of ENV_KEYS) {
    savedEnv[k] = process.env[k];
    delete process.env[k];
  }
});

afterEach(async () => {
  for (const k of ENV_KEYS) {
    const v = savedEnv[k];
    if (v === undefined) {
      delete process.env[k];
    } else {
      process.env[k] = v;
    }
  }
  await rm(tmp, { recursive: true, force: true });
});

const SAMPLE_CONFLUENCE = {
  baseUrl: "https://example.atlassian.net/wiki",
  email: "user@example.com",
  apiToken: "atl-token-1",
};
const SAMPLE_NOTION = {
  token: "secret_abc",
  rootPageId: "00000000000000000000000000000000",
};
const SAMPLE_PROFILE = { confluence: SAMPLE_CONFLUENCE, notion: SAMPLE_NOTION };

describe("getConfigPath", () => {
  it("returns the env-paths config dir + 'config.json'", () => {
    const { dir, file } = getConfigPath();
    expect(dir.length).toBeGreaterThan(0);
    expect(file).toBe(join(dir, "config.json"));
  });

  it("honors an explicit configDir override", () => {
    const { dir, file } = getConfigPath({ configDir: tmp });
    expect(dir).toBe(tmp);
    expect(file).toBe(join(tmp, "config.json"));
  });
});

describe("readConfig", () => {
  it("returns an empty config shape when the file does not exist", () => {
    const cfg = readConfig({ configDir: tmp });
    expect(cfg).toEqual({ currentProfile: "default", profiles: {} });
  });
});

describe("writeConfig", () => {
  it("creates the parent directory and writes the file (POSIX modes 0700/0600)", async () => {
    const nestedDir = join(tmp, "nested", "c2n");
    writeConfig({ currentProfile: "default", profiles: {} }, { configDir: nestedDir });
    const dirStat = await stat(nestedDir);
    const fileStat = await stat(join(nestedDir, "config.json"));
    if (process.platform !== "win32") {
      // mask to permission bits
      expect(dirStat.mode & 0o777).toBe(0o700);
      expect(fileStat.mode & 0o777).toBe(0o600);
    }
  });
});

describe("upsertProfile", () => {
  it("adds a new profile without disturbing other profiles", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    upsertProfile(
      "work",
      {
        confluence: { ...SAMPLE_CONFLUENCE, email: "work@example.com" },
        notion: { ...SAMPLE_NOTION, token: "secret_work" },
      },
      { configDir: tmp },
    );
    const cfg = readConfig({ configDir: tmp });
    expect(Object.keys(cfg.profiles).sort()).toEqual(["default", "work"]);
    expect(cfg.profiles.default?.confluence.email).toBe("user@example.com");
    expect(cfg.profiles.work?.notion.token).toBe("secret_work");
  });

  it("overwrites only the targeted profile when called twice", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    upsertProfile(
      "default",
      {
        confluence: { ...SAMPLE_CONFLUENCE, apiToken: "atl-token-2" },
        notion: SAMPLE_NOTION,
      },
      { configDir: tmp },
    );
    const cfg = readConfig({ configDir: tmp });
    expect(cfg.profiles.default?.confluence.apiToken).toBe("atl-token-2");
  });
});

describe("setCurrentProfile", () => {
  it("flips currentProfile and persists", () => {
    upsertProfile("work", SAMPLE_PROFILE, { configDir: tmp });
    setCurrentProfile("work", { configDir: tmp });
    const cfg = readConfig({ configDir: tmp });
    expect(cfg.currentProfile).toBe("work");
  });
});

describe("resolveProfileName", () => {
  it("uses explicit profile arg first", () => {
    process.env.C2N_PROFILE = "envprof";
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    setCurrentProfile("default", { configDir: tmp });
    expect(resolveProfileName("explicit", { configDir: tmp })).toBe("explicit");
  });

  it("falls back to C2N_PROFILE env var when no explicit arg", () => {
    process.env.C2N_PROFILE = "envprof";
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    expect(resolveProfileName(undefined, { configDir: tmp })).toBe("envprof");
  });

  it("falls back to currentProfile from config when env not set", () => {
    upsertProfile("work", SAMPLE_PROFILE, { configDir: tmp });
    setCurrentProfile("work", { configDir: tmp });
    expect(resolveProfileName(undefined, { configDir: tmp })).toBe("work");
  });

  it("falls back to literal 'default' when nothing else is set", () => {
    expect(resolveProfileName(undefined, { configDir: tmp })).toBe("default");
  });
});

describe("getConfluenceCreds", () => {
  it("returns the profile's stored values when env not set", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    const creds = getConfluenceCreds(undefined, { configDir: tmp });
    expect(creds).toEqual(SAMPLE_CONFLUENCE);
  });

  it("env vars take precedence over file values, per field", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    process.env.CONFLUENCE_EMAIL = "env@example.com";
    const creds = getConfluenceCreds(undefined, { configDir: tmp });
    expect(creds.email).toBe("env@example.com");
    expect(creds.baseUrl).toBe(SAMPLE_CONFLUENCE.baseUrl);
    expect(creds.apiToken).toBe(SAMPLE_CONFLUENCE.apiToken);
  });

  it("throws ConfigStoreError naming missing fields", () => {
    expect(() => getConfluenceCreds(undefined, { configDir: tmp })).toThrow(ConfigStoreError);
    try {
      getConfluenceCreds(undefined, { configDir: tmp });
    } catch (e) {
      const msg = (e as Error).message;
      expect(msg).toContain("CONFLUENCE_BASE_URL");
      expect(msg).toContain("CONFLUENCE_EMAIL");
      expect(msg).toContain("CONFLUENCE_API_TOKEN");
    }
  });
});

describe("getNotionCreds", () => {
  it("returns the profile's stored values when env not set", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    const creds = getNotionCreds(undefined, { configDir: tmp });
    expect(creds).toEqual(SAMPLE_NOTION);
  });

  it("NOTION_TOKEN env var takes precedence over file token", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    process.env.NOTION_TOKEN = "secret_env";
    const creds = getNotionCreds(undefined, { configDir: tmp });
    expect(creds.token).toBe("secret_env");
  });

  it("legacy NOTION_API_TOKEN env var is also accepted", () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });
    process.env.NOTION_API_TOKEN = "secret_legacy";
    const creds = getNotionCreds(undefined, { configDir: tmp });
    expect(creds.token).toBe("secret_legacy");
  });

  it("throws ConfigStoreError naming missing fields", () => {
    expect(() => getNotionCreds(undefined, { configDir: tmp })).toThrow(ConfigStoreError);
    try {
      getNotionCreds(undefined, { configDir: tmp });
    } catch (e) {
      const msg = (e as Error).message;
      expect(msg).toContain("NOTION_TOKEN");
      expect(msg).toContain("NOTION_ROOT_PAGE_ID");
    }
  });
});
