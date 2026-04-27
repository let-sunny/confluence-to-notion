import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as readline from "node:readline/promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createProgram } from "../../src/cli/index.js";

vi.mock("node:readline/promises", () => ({
  createInterface: vi.fn(),
}));

interface ScriptedReadline {
  question: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
}

function scriptReadline(answers: string[]): ScriptedReadline {
  const remaining = [...answers];
  const close = vi.fn();
  const question = vi.fn(async () => {
    const next = remaining.shift();
    if (next === undefined) {
      throw new Error("readline.question called more times than scripted");
    }
    return next;
  });
  vi.mocked(readline.createInterface).mockReturnValue({
    question,
    close,
  } as unknown as ReturnType<typeof readline.createInterface>);
  return { question, close };
}

function driveSecretAnswers(answers: string[]): { setRawMode: ReturnType<typeof vi.fn> } {
  const remaining = [...answers];
  const setRawMode = vi.fn((mode: boolean) => {
    if (mode === true) {
      const next = remaining.shift();
      if (next === undefined) return;
      setImmediate(() => {
        process.stdin.emit("data", Buffer.from(`${next}\r`));
      });
    }
  });
  return { setRawMode };
}

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

  it("TTY mode prompts secret token fields without echoing the typed value", async () => {
    const writes: string[] = [];
    vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
      writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk as Buffer).toString());
      return true;
    }) as typeof process.stdout.write);

    const { question } = scriptReadline([
      "https://prompted.atlassian.net/wiki",
      "prompted@example.com",
      "00000000000000000000000000000000",
    ]);
    const driver = driveSecretAnswers(["atl-token-secret", "secret_notion_token"]);

    const isTty = process.stdin.isTTY;
    const stdinAny = process.stdin as unknown as {
      setRawMode: ((mode: boolean) => unknown) | undefined;
    };
    const prevSetRawMode = stdinAny.setRawMode;
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    stdinAny.setRawMode = driver.setRawMode;

    try {
      await createProgram().parseAsync(["node", "c2n", "init"]);
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
      stdinAny.setRawMode = prevSetRawMode;
    }

    // Non-secret fields go through the readline mock — three of the five field prompts.
    expect(question).toHaveBeenCalledTimes(3);
    expect(question.mock.calls[0]?.[0]).toBe("Confluence base URL: ");
    expect(question.mock.calls[1]?.[0]).toBe("Confluence account email: ");
    expect(question.mock.calls[2]?.[0]).toBe("Notion root page ID: ");

    // Secret prompts wrote their labels but not their answers.
    const captured = writes.join("");
    expect(captured).toContain("Confluence API token:");
    expect(captured).toContain("Notion integration token:");
    expect(captured).not.toContain("atl-token-secret");
    expect(captured).not.toContain("secret_notion_token");

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default).toEqual({
      confluence: {
        baseUrl: "https://prompted.atlassian.net/wiki",
        email: "prompted@example.com",
        apiToken: "atl-token-secret",
      },
      notion: {
        token: "secret_notion_token",
        rootPageId: "00000000000000000000000000000000",
      },
    });
  });

  it("non-TTY missing-flags error path is unchanged when only secret fields are missing", async () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    const isTty = process.stdin.isTTY;
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    try {
      await expect(
        createProgram().parseAsync([
          "node",
          "c2n",
          "init",
          "--confluence-base-url",
          "https://example.atlassian.net/wiki",
          "--confluence-email",
          "user@example.com",
          "--notion-root-page-id",
          "00000000000000000000000000000000",
          // Missing --confluence-api-token and --notion-token (the secret ones).
        ]),
      ).rejects.toThrow("__exit__");

      expect(exit).toHaveBeenCalledWith(1);
      const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
      expect(errMsg).toMatch(/--confluence-api-token/);
      expect(errMsg).toMatch(/--notion-token/);
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }
  });
});
