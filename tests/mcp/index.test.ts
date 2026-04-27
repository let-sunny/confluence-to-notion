import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { upsertProfile } from "../../src/configStore.js";

const ENV_KEYS = [
  "CONFLUENCE_BASE_URL",
  "CONFLUENCE_EMAIL",
  "CONFLUENCE_API_TOKEN",
  "CONFLUENCE_TOKEN",
  "C2N_PROFILE",
  "C2N_CONFIG_DIR",
  "XDG_CONFIG_HOME",
] as const;

let tmp: string;
let savedEnv: Record<string, string | undefined>;

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), "c2n-mcp-idx-"));
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
});

const SAMPLE_PROFILE = {
  confluence: {
    baseUrl: "https://example.atlassian.net/wiki",
    email: "user@example.com",
    apiToken: "atl-token-1",
  },
  notion: {
    token: "secret_abc",
    rootPageId: "00000000000000000000000000000000",
  },
};

describe("c2n-mcp entry", () => {
  it("imports without side effects and exposes main()", async () => {
    const mod = await import("../../src/mcp/index.js");
    expect(typeof mod.main).toBe("function");
  });

  it("exposes buildServerOptions() that wires cred-store factories", async () => {
    const mod = await import("../../src/mcp/index.js");
    expect(typeof mod.buildServerOptions).toBe("function");
  });
});

describe("buildServerOptions credential wiring", () => {
  it("uses C2N_PROFILE when set, then config currentProfile, then 'default'", async () => {
    upsertProfile("work", SAMPLE_PROFILE, { configDir: tmp });
    process.env.C2N_PROFILE = "work";

    const { buildServerOptions } = await import("../../src/mcp/index.js");
    const options = buildServerOptions();

    expect(typeof options.confluenceFactory).toBe("function");
    // Should not throw: profile 'work' resolves and has full creds.
    expect(() => options.confluenceFactory?.()).not.toThrow();
  });

  it("constructs a Confluence adapter from stored profile creds when env vars are unset", async () => {
    upsertProfile("default", SAMPLE_PROFILE, { configDir: tmp });

    const { buildServerOptions } = await import("../../src/mcp/index.js");
    const options = buildServerOptions();
    const adapter = options.confluenceFactory?.();

    expect(adapter).toBeDefined();
    expect(typeof adapter?.getPage).toBe("function");
    expect(typeof adapter?.listSpacePages).toBe("function");
  });

  it("Confluence factory throws InvalidRequest naming env vars and 'c2n init' when creds missing", async () => {
    const { buildServerOptions } = await import("../../src/mcp/index.js");
    const options = buildServerOptions();

    let captured: unknown;
    try {
      options.confluenceFactory?.();
    } catch (e) {
      captured = e;
    }
    expect(captured).toBeInstanceOf(McpError);
    const err = captured as McpError;
    expect(err.code).toBe(ErrorCode.InvalidRequest);
    expect(err.message).toMatch(/CONFLUENCE_BASE_URL/);
    expect(err.message).toMatch(/CONFLUENCE_EMAIL/);
    expect(err.message).toMatch(/CONFLUENCE_API_TOKEN/);
    expect(err.message).toMatch(/c2n init/);
  });
});
