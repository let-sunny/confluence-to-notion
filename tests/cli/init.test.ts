import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
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
  tmp = await mkdtemp(join(tmpdir(), "c2n-init-"));
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

const FLAGS_DEFAULT = [
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

const FLAGS_WORK = [
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

async function readStoredConfig(): Promise<{
  currentProfile: string;
  profiles: Record<
    string,
    {
      confluence: { baseUrl: string; email: string; apiToken: string };
      notion: { token: string; rootPageId: string };
    }
  >;
}> {
  const raw = await readFile(join(tmp, "config.json"), "utf8");
  return JSON.parse(raw) as {
    currentProfile: string;
    profiles: Record<
      string,
      {
        confluence: { baseUrl: string; email: string; apiToken: string };
        notion: { token: string; rootPageId: string };
      }
    >;
  };
}

describe("c2n init", () => {
  it("with all five non-interactive flags writes the default profile", async () => {
    const program = createProgram();
    await program.parseAsync(["node", "c2n", "init", ...FLAGS_DEFAULT]);
    const cfg = await readStoredConfig();
    expect(cfg.currentProfile).toBe("default");
    expect(cfg.profiles.default).toEqual({
      confluence: {
        baseUrl: "https://example.atlassian.net/wiki",
        email: "user@example.com",
        apiToken: "atl-token-1",
      },
      notion: {
        token: "secret_abc",
        rootPageId: "00000000000000000000000000000000",
      },
    });
  });

  it("--profile work writes only the work profile and leaves default intact", async () => {
    await createProgram().parseAsync(["node", "c2n", "init", ...FLAGS_DEFAULT]);
    await createProgram().parseAsync(["node", "c2n", "init", "--profile", "work", ...FLAGS_WORK]);
    const cfg = await readStoredConfig();
    expect(Object.keys(cfg.profiles).sort()).toEqual(["default", "work"]);
    expect(cfg.profiles.default?.confluence.email).toBe("user@example.com");
    expect(cfg.profiles.work?.confluence.email).toBe("work@example.com");
  });

  it("currentProfile defaults to 'default' on first init and is NOT overwritten by --profile work", async () => {
    await createProgram().parseAsync(["node", "c2n", "init", ...FLAGS_DEFAULT]);
    await createProgram().parseAsync(["node", "c2n", "init", "--profile", "work", ...FLAGS_WORK]);
    const cfg = await readStoredConfig();
    expect(cfg.currentProfile).toBe("default");
  });

  it("when stdin is not a TTY and a value is missing, exits non-zero with a useful error", async () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    // Force non-TTY
    const isTty = process.stdin.isTTY;
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    try {
      await expect(
        createProgram().parseAsync([
          "node",
          "c2n",
          "init",
          // Missing --notion-root-page-id and --notion-token
          "--confluence-base-url",
          "https://example.atlassian.net/wiki",
          "--confluence-email",
          "user@example.com",
          "--confluence-api-token",
          "atl-token-1",
        ]),
      ).rejects.toThrow("__exit__");

      expect(exit).toHaveBeenCalledWith(1);
      const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
      expect(errMsg).toMatch(/--notion-token/);
      expect(errMsg).toMatch(/--notion-root-page-id/);
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }
  });

  it("written config file has mode 0600 (POSIX only)", async () => {
    if (process.platform === "win32") return;
    await createProgram().parseAsync(["node", "c2n", "init", ...FLAGS_DEFAULT]);
    const fileStat = await stat(join(tmp, "config.json"));
    expect(fileStat.mode & 0o777).toBe(0o600);
  });
});
