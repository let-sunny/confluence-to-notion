import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const usersMeMock = vi.fn();

vi.mock("@notionhq/client", () => ({
  Client: vi.fn(),
}));

import { Client } from "@notionhq/client";
import { createProgram } from "../../src/cli/index.js";

const ClientMock = vi.mocked(Client);

const ENV_KEYS = [
  "C2N_CONFIG_DIR",
  "C2N_PROFILE",
  "NOTION_TOKEN",
  "NOTION_API_TOKEN",
  "NOTION_ROOT_PAGE_ID",
] as const;

interface StoredProfile {
  confluence: { baseUrl: string; email: string; apiToken: string };
  notion: { token: string; rootPageId: string };
}

let tmp: string;
let cwdSaved: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-notion-"));
  await mkdir(tmp, { recursive: true });
  savedEnv = {};
  for (const k of ENV_KEYS) {
    savedEnv[k] = process.env[k];
    delete process.env[k];
  }
  process.env.C2N_CONFIG_DIR = tmp;
  cwdSaved = process.cwd();
  process.chdir(tmp);
  ClientMock.mockReset();
  ClientMock.mockImplementation(() => ({ users: { me: usersMeMock } }) as unknown as Client);
  usersMeMock.mockReset();
  usersMeMock.mockResolvedValue({ id: "bot" } as never);
});

afterEach(async () => {
  process.chdir(cwdSaved);
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

async function seedConfig(
  profiles: Record<string, StoredProfile>,
  currentProfile = "default",
): Promise<void> {
  const cfg = { currentProfile, profiles };
  await writeFile(join(tmp, "config.json"), JSON.stringify(cfg), "utf8");
}

const DEFAULT_PROFILE: StoredProfile = {
  confluence: {
    baseUrl: "https://default.example/wiki",
    email: "default@example.com",
    apiToken: "tok-default",
  },
  notion: { token: "secret_default", rootPageId: "0".repeat(32) },
};

const FOO_PROFILE: StoredProfile = {
  confluence: {
    baseUrl: "https://foo.example/wiki",
    email: "foo@example.com",
    apiToken: "tok-foo",
  },
  notion: { token: "secret_foo", rootPageId: "1".repeat(32) },
};

describe("c2n notion-ping --profile", () => {
  it("--profile foo reads creds from the foo profile entry", async () => {
    await seedConfig({ default: DEFAULT_PROFILE, foo: FOO_PROFILE });

    await createProgram().parseAsync(["node", "c2n", "notion-ping", "--profile", "foo"]);

    expect(ClientMock).toHaveBeenCalledTimes(1);
    expect(ClientMock.mock.calls[0]?.[0]).toMatchObject({ auth: "secret_foo" });
    expect(usersMeMock).toHaveBeenCalledTimes(1);
  });

  it("env vars override stored profile values", async () => {
    await seedConfig({ default: DEFAULT_PROFILE });
    process.env.NOTION_TOKEN = "secret_env";
    process.env.NOTION_ROOT_PAGE_ID = "9".repeat(32);

    await createProgram().parseAsync(["node", "c2n", "notion-ping"]);

    expect(ClientMock.mock.calls[0]?.[0]).toMatchObject({ auth: "secret_env" });
  });

  it("legacy NOTION_API_TOKEN is also accepted", async () => {
    await seedConfig({ default: DEFAULT_PROFILE });
    process.env.NOTION_API_TOKEN = "secret_legacy";

    await createProgram().parseAsync(["node", "c2n", "notion-ping"]);

    expect(ClientMock.mock.calls[0]?.[0]).toMatchObject({ auth: "secret_legacy" });
  });

  it("missing creds exits non-zero with a stderr message", async () => {
    // No config seeded, no env vars set.
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = vi.spyOn(process, "exit").mockImplementation(((_code?: number) => {
      throw new Error("__exit__");
    }) as never);

    await expect(createProgram().parseAsync(["node", "c2n", "notion-ping"])).rejects.toThrow(
      "__exit__",
    );

    expect(exit).toHaveBeenCalledWith(1);
    const errMsg = stderr.mock.calls.map((c) => String(c[0])).join("");
    expect(errMsg).toMatch(/NOTION_TOKEN/);
    expect(errMsg).toMatch(/NOTION_ROOT_PAGE_ID/);
  });
});
