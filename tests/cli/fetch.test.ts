import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/confluence/client.js", () => ({
  createConfluenceClient: vi.fn(),
}));

import { createProgram } from "../../src/cli/index.js";
import { createConfluenceClient } from "../../src/confluence/client.js";

const createConfluenceClientMock = vi.mocked(createConfluenceClient);

const ENV_KEYS = [
  "C2N_CONFIG_DIR",
  "C2N_PROFILE",
  "CONFLUENCE_BASE_URL",
  "CONFLUENCE_EMAIL",
  "CONFLUENCE_API_TOKEN",
  "CONFLUENCE_TOKEN",
] as const;

interface StoredProfile {
  confluence: { baseUrl: string; email: string; apiToken: string };
  notion: { token: string; rootPageId: string };
}

let tmp: string;
let cwdSaved: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-fetch-"));
  await mkdir(join(tmp, "samples"), { recursive: true });
  savedEnv = {};
  for (const k of ENV_KEYS) {
    savedEnv[k] = process.env[k];
    delete process.env[k];
  }
  process.env.C2N_CONFIG_DIR = tmp;
  cwdSaved = process.cwd();
  process.chdir(tmp);
  createConfluenceClientMock.mockReset();
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

function fakeClient(): unknown {
  return {
    getPage: async (id: string) => ({
      id,
      title: "fake",
      version: { number: 1, when: "2024-01-01T00:00:00.000Z", by: { displayName: "u" } },
      space: { key: "TEST" },
      body: { storage: { value: "<p>hi</p>", representation: "storage" } },
    }),
    listSpacePages: async () => ({ results: [], start: 0, limit: 25, size: 0 }),
    getPageTree: async (rootId: string) => ({ id: rootId, title: "root", children: [] }),
    getAttachment: async () => new Uint8Array(),
  };
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

describe("c2n fetch --profile", () => {
  it("--profile foo causes credential reads to use the foo profile entry", async () => {
    await seedConfig({ default: DEFAULT_PROFILE, foo: FOO_PROFILE });
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch",
      "--profile",
      "foo",
      "--pages",
      "p1",
      "--out-dir",
      "samples",
    ]);

    expect(createConfluenceClientMock).toHaveBeenCalledTimes(1);
    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://foo.example/wiki",
      email: "foo@example.com",
      token: "tok-foo",
    });
  });

  it("without --profile resolves through C2N_PROFILE > currentProfile > default", async () => {
    const bar: StoredProfile = {
      confluence: {
        baseUrl: "https://bar.example/wiki",
        email: "bar@example.com",
        apiToken: "tok-bar",
      },
      notion: { token: "secret_bar", rootPageId: "2".repeat(32) },
    };
    const baz: StoredProfile = {
      confluence: {
        baseUrl: "https://baz.example/wiki",
        email: "baz@example.com",
        apiToken: "tok-baz",
      },
      notion: { token: "secret_baz", rootPageId: "3".repeat(32) },
    };
    await seedConfig({ default: DEFAULT_PROFILE, bar, baz }, "bar");
    process.env.C2N_PROFILE = "baz";
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch",
      "--pages",
      "p1",
      "--out-dir",
      "samples",
    ]);

    // C2N_PROFILE wins over currentProfile.
    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://baz.example/wiki",
      email: "baz@example.com",
      token: "tok-baz",
    });
    createConfluenceClientMock.mockReset();
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    const profileKey = "C2N_PROFILE" as const;
    delete process.env[profileKey];
    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch",
      "--pages",
      "p1",
      "--out-dir",
      "samples",
    ]);

    // With C2N_PROFILE unset, currentProfile (bar) is used.
    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://bar.example/wiki",
      email: "bar@example.com",
      token: "tok-bar",
    });
  });

  it("env vars override stored profile values", async () => {
    await seedConfig({ default: DEFAULT_PROFILE });
    process.env.CONFLUENCE_BASE_URL = "https://env.example/wiki/";
    process.env.CONFLUENCE_EMAIL = "env@example.com";
    process.env.CONFLUENCE_API_TOKEN = "tok-env";
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch",
      "--pages",
      "p1",
      "--out-dir",
      "samples",
    ]);

    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://env.example/wiki",
      email: "env@example.com",
      token: "tok-env",
    });
  });
});

describe("c2n fetch-tree --profile", () => {
  it("--profile foo causes credential reads to use the foo profile entry", async () => {
    await seedConfig({ default: DEFAULT_PROFILE, foo: FOO_PROFILE });
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch-tree",
      "--root-id",
      "root1",
      "--profile",
      "foo",
      "--output",
      "tree.json",
    ]);

    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://foo.example/wiki",
      email: "foo@example.com",
      token: "tok-foo",
    });
  });

  it("env vars override stored profile values", async () => {
    await seedConfig({ default: DEFAULT_PROFILE });
    process.env.CONFLUENCE_BASE_URL = "https://env.example/wiki";
    process.env.CONFLUENCE_EMAIL = "env@example.com";
    process.env.CONFLUENCE_API_TOKEN = "tok-env";
    createConfluenceClientMock.mockReturnValue(fakeClient() as never);

    await createProgram().parseAsync([
      "node",
      "c2n",
      "fetch-tree",
      "--root-id",
      "root1",
      "--output",
      "tree.json",
    ]);

    expect(createConfluenceClientMock.mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "https://env.example/wiki",
      email: "env@example.com",
      token: "tok-env",
    });
  });
});
