import { mkdtemp, readFile, rm } from "node:fs/promises";
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

interface StdinSecretGuard {
  restore: () => void;
}

function installSecretStdin(setRawMode: (mode: boolean) => unknown): StdinSecretGuard {
  const isTty = process.stdin.isTTY;
  const stdinAny = process.stdin as unknown as {
    setRawMode: ((mode: boolean) => unknown) | undefined;
  };
  const prevSetRawMode = stdinAny.setRawMode;
  Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
  stdinAny.setRawMode = setRawMode;
  return {
    restore: () => {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
      stdinAny.setRawMode = prevSetRawMode;
    },
  };
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
  tmp = await mkdtemp(join(tmpdir(), "c2n-auth-"));
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

describe("c2n auth confluence", () => {
  it("with all three Confluence flags updates only the confluence subtree", async () => {
    await seedDefaultProfile();

    await createProgram().parseAsync([
      "node",
      "c2n",
      "auth",
      "confluence",
      "--confluence-base-url",
      "https://updated.atlassian.net/wiki",
      "--confluence-email",
      "new@example.com",
      "--confluence-api-token",
      "atl-token-new",
    ]);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.confluence).toEqual({
      baseUrl: "https://updated.atlassian.net/wiki",
      email: "new@example.com",
      apiToken: "atl-token-new",
    });
    expect(cfg.profiles.default?.notion).toEqual({
      token: "secret_abc",
      rootPageId: "00000000000000000000000000000000",
    });
  });

  it("--profile work updates only the work profile", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();

    await createProgram().parseAsync([
      "node",
      "c2n",
      "auth",
      "confluence",
      "--profile",
      "work",
      "--confluence-base-url",
      "https://work-updated.atlassian.net/wiki",
      "--confluence-email",
      "work-new@example.com",
      "--confluence-api-token",
      "atl-token-work-new",
    ]);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.confluence.email).toBe("user@example.com");
    expect(cfg.profiles.work?.confluence).toEqual({
      baseUrl: "https://work-updated.atlassian.net/wiki",
      email: "work-new@example.com",
      apiToken: "atl-token-work-new",
    });
    // Notion subtree on the work profile is untouched.
    expect(cfg.profiles.work?.notion.token).toBe("secret_work");
  });

  it("refuses when the named profile does not exist", async () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    await expect(
      createProgram().parseAsync([
        "node",
        "c2n",
        "auth",
        "confluence",
        "--profile",
        "missing",
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
    expect(errMsg).toMatch(/profile 'missing' does not exist/);
    expect(errMsg).toMatch(/c2n init/);
    expect(errMsg).not.toMatch(/auth confluence: __exit__/);

    // Config must not have been created with a half-populated profile.
    await expect(readFile(join(tmp, "config.json"), "utf8")).rejects.toThrow();
  });

  it("non-TTY without all required flags exits 1 listing the missing flags", async () => {
    await seedDefaultProfile();
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
          "auth",
          "confluence",
          // Missing --confluence-email and --confluence-api-token
          "--confluence-base-url",
          "https://example.atlassian.net/wiki",
        ]),
      ).rejects.toThrow("__exit__");

      expect(exit).toHaveBeenCalledWith(1);
      const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
      expect(errMsg).toMatch(/--confluence-email/);
      expect(errMsg).toMatch(/--confluence-api-token/);
      expect(errMsg).not.toMatch(/auth confluence: __exit__/);
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }

    // Confluence subtree on default must remain unchanged.
    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.confluence.email).toBe("user@example.com");
  });

  it("TTY mode prompts for missing fields and updates only the confluence subtree", async () => {
    await seedDefaultProfile();
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const { question, close } = scriptReadline([
      "https://prompted.atlassian.net/wiki",
      "prompted@example.com",
    ]);
    const driver = driveSecretAnswers(["atl-token-prompted"]);
    const guard = installSecretStdin(driver.setRawMode);

    try {
      await createProgram().parseAsync(["node", "c2n", "auth", "confluence"]);
    } finally {
      guard.restore();
    }

    // Only the two non-secret fields go through readline; the api token uses the secret path.
    expect(question).toHaveBeenCalledTimes(2);
    expect(question.mock.calls[0]?.[0]).toBe("Confluence base URL: ");
    expect(question.mock.calls[1]?.[0]).toBe("Confluence account email: ");
    // promptField creates one readline per non-secret prompt and closes it on exit.
    expect(close).toHaveBeenCalledTimes(2);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.confluence).toEqual({
      baseUrl: "https://prompted.atlassian.net/wiki",
      email: "prompted@example.com",
      apiToken: "atl-token-prompted",
    });
    // Notion subtree must remain unchanged.
    expect(cfg.profiles.default?.notion).toEqual({
      token: "secret_abc",
      rootPageId: "00000000000000000000000000000000",
    });
  });

  it("TTY mode does not echo the Confluence API token while non-secret fields go through readline", async () => {
    await seedDefaultProfile();
    const writes: string[] = [];
    vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
      writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk as Buffer).toString());
      return true;
    }) as typeof process.stdout.write);

    const { question } = scriptReadline([
      "https://prompted.atlassian.net/wiki",
      "prompted@example.com",
    ]);
    const driver = driveSecretAnswers(["atl-token-must-not-leak"]);
    const guard = installSecretStdin(driver.setRawMode);

    try {
      await createProgram().parseAsync(["node", "c2n", "auth", "confluence"]);
    } finally {
      guard.restore();
    }

    // Non-secret fields are driven through the readline mock.
    expect(question.mock.calls[0]?.[0]).toBe("Confluence base URL: ");
    expect(question.mock.calls[1]?.[0]).toBe("Confluence account email: ");

    const captured = writes.join("");
    // The secret prompt label is written; the typed value never reaches stdout.
    expect(captured).toContain("Confluence API token:");
    expect(captured).not.toContain("atl-token-must-not-leak");
  });

  it("TTY mode rejects when a prompted answer is empty", async () => {
    await seedDefaultProfile();
    const { close } = scriptReadline([""]);

    const isTty = process.stdin.isTTY;
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });

    try {
      await expect(
        createProgram().parseAsync([
          "node",
          "c2n",
          "auth",
          "confluence",
          // Only --confluence-base-url is missing; the prompt receives "".
          "--confluence-email",
          "user@example.com",
          "--confluence-api-token",
          "atl-token-1",
        ]),
      ).rejects.toThrow("Empty input for --confluence-base-url; aborting.");
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }

    expect(close).toHaveBeenCalledTimes(1);
    // Confluence subtree on default must remain unchanged.
    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.confluence.baseUrl).toBe("https://example.atlassian.net/wiki");
  });
});

describe("c2n auth notion", () => {
  it("with both Notion flags updates only the notion subtree", async () => {
    await seedDefaultProfile();

    await createProgram().parseAsync([
      "node",
      "c2n",
      "auth",
      "notion",
      "--notion-token",
      "secret_new",
      "--notion-root-page-id",
      "22222222222222222222222222222222",
    ]);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.notion).toEqual({
      token: "secret_new",
      rootPageId: "22222222222222222222222222222222",
    });
    expect(cfg.profiles.default?.confluence).toEqual({
      baseUrl: "https://example.atlassian.net/wiki",
      email: "user@example.com",
      apiToken: "atl-token-1",
    });
  });

  it("--profile work updates only the work profile", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();

    await createProgram().parseAsync([
      "node",
      "c2n",
      "auth",
      "notion",
      "--profile",
      "work",
      "--notion-token",
      "secret_work_new",
      "--notion-root-page-id",
      "33333333333333333333333333333333",
    ]);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.notion.token).toBe("secret_abc");
    expect(cfg.profiles.work?.notion).toEqual({
      token: "secret_work_new",
      rootPageId: "33333333333333333333333333333333",
    });
    expect(cfg.profiles.work?.confluence.email).toBe("work@example.com");
  });

  it("refuses when the named profile does not exist", async () => {
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    await expect(
      createProgram().parseAsync([
        "node",
        "c2n",
        "auth",
        "notion",
        "--profile",
        "missing",
        "--notion-token",
        "secret_x",
        "--notion-root-page-id",
        "44444444444444444444444444444444",
      ]),
    ).rejects.toThrow("__exit__");

    expect(exit).toHaveBeenCalledWith(1);
    const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
    expect(errMsg).toMatch(/profile 'missing' does not exist/);
    expect(errMsg).toMatch(/c2n init/);
    expect(errMsg).not.toMatch(/auth notion: __exit__/);
  });

  it("non-TTY without all required flags exits 1 listing the missing flags", async () => {
    await seedDefaultProfile();
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
          "auth",
          "notion",
          // Missing --notion-root-page-id
          "--notion-token",
          "secret_x",
        ]),
      ).rejects.toThrow("__exit__");

      expect(exit).toHaveBeenCalledWith(1);
      const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
      expect(errMsg).toMatch(/--notion-root-page-id/);
      expect(errMsg).not.toMatch(/auth notion: __exit__/);
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.notion.token).toBe("secret_abc");
  });

  it("TTY mode prompts for missing fields and updates only the notion subtree", async () => {
    await seedDefaultProfile();
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const { question, close } = scriptReadline(["55555555555555555555555555555555"]);
    const driver = driveSecretAnswers(["secret_prompted"]);
    const guard = installSecretStdin(driver.setRawMode);

    try {
      await createProgram().parseAsync(["node", "c2n", "auth", "notion"]);
    } finally {
      guard.restore();
    }

    // Only the non-secret root-page-id goes through readline.
    expect(question).toHaveBeenCalledTimes(1);
    expect(question.mock.calls[0]?.[0]).toBe("Notion root page ID: ");
    expect(close).toHaveBeenCalledTimes(1);

    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.notion).toEqual({
      token: "secret_prompted",
      rootPageId: "55555555555555555555555555555555",
    });
    // Confluence subtree must remain unchanged.
    expect(cfg.profiles.default?.confluence).toEqual({
      baseUrl: "https://example.atlassian.net/wiki",
      email: "user@example.com",
      apiToken: "atl-token-1",
    });
  });

  it("TTY mode does not echo the Notion integration token while the root page id goes through readline", async () => {
    await seedDefaultProfile();
    const writes: string[] = [];
    vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
      writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk as Buffer).toString());
      return true;
    }) as typeof process.stdout.write);

    const { question } = scriptReadline(["55555555555555555555555555555555"]);
    const driver = driveSecretAnswers(["secret_must_not_leak"]);
    const guard = installSecretStdin(driver.setRawMode);

    try {
      await createProgram().parseAsync(["node", "c2n", "auth", "notion"]);
    } finally {
      guard.restore();
    }

    expect(question.mock.calls[0]?.[0]).toBe("Notion root page ID: ");

    const captured = writes.join("");
    expect(captured).toContain("Notion integration token:");
    expect(captured).not.toContain("secret_must_not_leak");
  });

  it("TTY mode rejects when a prompted answer is empty", async () => {
    await seedDefaultProfile();
    const { close } = scriptReadline([""]);

    const isTty = process.stdin.isTTY;
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });

    try {
      await expect(
        createProgram().parseAsync([
          "node",
          "c2n",
          "auth",
          "notion",
          // Only --notion-root-page-id is missing; the prompt receives "".
          "--notion-token",
          "secret_x",
        ]),
      ).rejects.toThrow("Empty input for --notion-root-page-id; aborting.");
    } finally {
      Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: isTty });
    }

    expect(close).toHaveBeenCalledTimes(1);
    // Notion subtree on default must remain unchanged.
    const cfg = await readStoredConfig();
    expect(cfg.profiles.default?.notion.token).toBe("secret_abc");
  });
});
