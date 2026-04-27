import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createProgram } from "../../src/cli/index.js";

const ENV_KEYS = [
  "C2N_CONFIG_DIR",
  "C2N_PROFILE",
  "CONFLUENCE_BASE_URL",
  "CONFLUENCE_EMAIL",
  "CONFLUENCE_API_TOKEN",
  "CONFLUENCE_TOKEN",
  "NOTION_TOKEN",
  "NOTION_API_TOKEN",
  "NOTION_ROOT_PAGE_ID",
] as const;

let tmp: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-use-"));
  savedEnv = {};
  for (const k of ENV_KEYS) {
    savedEnv[k] = process.env[k];
    delete process.env[k];
  }
  process.env.C2N_CONFIG_DIR = tmp;
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
  vi.restoreAllMocks();
});

const FLAGS_INIT_DEFAULT = [
  "--confluence-base-url",
  "https://example.atlassian.net/wiki",
  "--confluence-email",
  "user@example.com",
  "--confluence-api-token",
  "atl-token-1",
  "--notion-token",
  "secret_abc",
  "--notion-root-page-id",
  "00000000000000000000000000000000",
];

const FLAGS_INIT_WORK = [
  "--confluence-base-url",
  "https://work.atlassian.net/wiki",
  "--confluence-email",
  "work@example.com",
  "--confluence-api-token",
  "atl-token-2",
  "--notion-token",
  "secret_work",
  "--notion-root-page-id",
  "11111111111111111111111111111111",
];

interface StoredProfile {
  confluence: { baseUrl: string; email: string; apiToken: string };
  notion: { token: string; rootPageId: string };
}

interface StoredConfig {
  currentProfile: string;
  profiles: Record<string, StoredProfile>;
}

async function readStoredConfig(): Promise<StoredConfig> {
  const raw = await readFile(join(tmp, "config.json"), "utf8");
  return JSON.parse(raw) as StoredConfig;
}

async function seedDefaultProfile(): Promise<void> {
  await createProgram().parseAsync(["node", "c2n", "init", ...FLAGS_INIT_DEFAULT]);
}

async function seedWorkProfile(): Promise<void> {
  await createProgram().parseAsync([
    "node",
    "c2n",
    "init",
    "--profile",
    "work",
    ...FLAGS_INIT_WORK,
  ]);
}

describe("c2n use <name>", () => {
  it("sets currentProfile when the named profile exists, persisting to the config file", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();

    // `c2n init --profile work` does not flip currentProfile; it stays at default.
    const before = await readStoredConfig();
    expect(before.currentProfile).toBe("default");

    await createProgram().parseAsync(["node", "c2n", "use", "work"]);

    const after = await readStoredConfig();
    expect(after.currentProfile).toBe("work");
  });

  it("preserves the profiles map untouched (only currentProfile changes)", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();

    const before = await readStoredConfig();

    await createProgram().parseAsync(["node", "c2n", "use", "work"]);

    const after = await readStoredConfig();
    expect(after.profiles).toEqual(before.profiles);
  });

  it("errors with non-zero exit and a clear stderr message when the profile does not exist", async () => {
    await seedDefaultProfile();
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    await expect(createProgram().parseAsync(["node", "c2n", "use", "missing"])).rejects.toThrow(
      "__exit__",
    );

    expect(exit).toHaveBeenCalledWith(1);
    const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
    expect(errMsg).toMatch(/profile 'missing' does not exist/);
    expect(errMsg).toMatch(/c2n init/);

    // currentProfile must remain unchanged.
    const cfg = await readStoredConfig();
    expect(cfg.currentProfile).toBe("default");
  });

  it("errors when no <name> argument is given", async () => {
    await seedDefaultProfile();
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);
    // Commander writes its own usage error, which calls process.exit; intercept it.
    const program = createProgram();
    program.exitOverride();

    await expect(program.parseAsync(["node", "c2n", "use"])).rejects.toThrow();

    // Either commander's exit-override threw (no process.exit call needed) or we
    // recorded a non-zero exit. Both are acceptable; assert one happened.
    const wroteToStderr = stderr.mock.calls.length > 0;
    const calledExit = exit.mock.calls.length > 0;
    expect(wroteToStderr || calledExit).toBe(true);

    // currentProfile must remain unchanged.
    const cfg = await readStoredConfig();
    expect(cfg.currentProfile).toBe("default");
  });
});
