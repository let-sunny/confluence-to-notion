import { mkdtemp, rm } from "node:fs/promises";
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

const SECRET_TOKEN = "atl-token-must-not-leak";
const NOTION_SECRET = "secret_must_not_leak";

let tmp: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-profiles-"));
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
  SECRET_TOKEN,
  "--notion-token",
  NOTION_SECRET,
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

function captureStdout(): { writes: string[]; restore: () => void } {
  const writes: string[] = [];
  const spy = vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
    writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk as Buffer).toString());
    return true;
  }) as typeof process.stdout.write);
  return { writes, restore: () => spy.mockRestore() };
}

describe("c2n profiles list", () => {
  it("prints each profile name, marking the currentProfile with '* '", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();
    // currentProfile is still 'default' (init does not flip it).

    const captured = captureStdout();
    try {
      await createProgram().parseAsync(["node", "c2n", "profiles", "list"]);
    } finally {
      captured.restore();
    }

    const out = captured.writes.join("");
    // Both profiles appear, default is marked with leading '* '.
    expect(out).toMatch(/^\*\s+default$/m);
    expect(out).toMatch(/^\s{2}work$|^work$/m);
    // The non-current profile should not be marked.
    expect(out).not.toMatch(/^\*\s+work$/m);
  });

  it("prints a friendly empty-state message when no profiles exist (exit 0)", async () => {
    const captured = captureStdout();
    try {
      await createProgram().parseAsync(["node", "c2n", "profiles", "list"]);
    } finally {
      captured.restore();
    }

    const out = captured.writes.join("");
    expect(out).toMatch(/no profiles configured/i);
    expect(out).toMatch(/c2n init/);
  });

  it("honours C2N_CONFIG_DIR (reads from the test-scoped directory)", async () => {
    await seedDefaultProfile();
    // Sanity-check: the seeded profile must round-trip via the listing.
    const captured = captureStdout();
    try {
      await createProgram().parseAsync(["node", "c2n", "profiles", "list"]);
    } finally {
      captured.restore();
    }

    const out = captured.writes.join("");
    expect(out).toContain("default");
  });

  it("does not print any credential values", async () => {
    await seedDefaultProfile();
    await seedWorkProfile();

    const captured = captureStdout();
    try {
      await createProgram().parseAsync(["node", "c2n", "profiles", "list"]);
    } finally {
      captured.restore();
    }

    const out = captured.writes.join("");
    expect(out).not.toContain(SECRET_TOKEN);
    expect(out).not.toContain(NOTION_SECRET);
    expect(out).not.toContain("secret_work");
    expect(out).not.toContain("atl-token-2");
    expect(out).not.toContain("00000000000000000000000000000000");
    expect(out).not.toContain("11111111111111111111111111111111");
  });
});
