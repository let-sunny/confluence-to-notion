import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { type Config, ConfigError, loadConfig } from "../src/config.js";

const ALL_VARS = {
  CONFLUENCE_EMAIL: "user@example.com",
  CONFLUENCE_TOKEN: "confluence-token",
  NOTION_TOKEN: "notion-token",
  ANTHROPIC_API_KEY: "anthropic-key",
};

function stubAll(values: Record<string, string | undefined>): void {
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined) {
      vi.stubEnv(key, "");
    } else {
      vi.stubEnv(key, value);
    }
  }
}

function clearAll(): void {
  for (const key of Object.keys(ALL_VARS)) {
    vi.stubEnv(key, "");
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("loadConfig", () => {
  it("returns a typed readonly object when every required env var is set", () => {
    stubAll(ALL_VARS);

    const config = loadConfig();

    expect(config).toEqual(ALL_VARS);
    expectTypeOf(config).toEqualTypeOf<Config>();
  });

  it("throws ConfigError naming the missing var in a single readable line", () => {
    stubAll({ ...ALL_VARS, CONFLUENCE_TOKEN: undefined });

    let caught: unknown;
    try {
      loadConfig();
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ConfigError);
    const message = (caught as ConfigError).toString();
    expect(message).toContain("CONFLUENCE_TOKEN");
    expect(message).toMatch(/Missing required env var/i);
  });

  it("does not leak a stack trace via toString()", () => {
    stubAll({ ...ALL_VARS, NOTION_TOKEN: undefined });

    try {
      loadConfig();
      throw new Error("expected loadConfig to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ConfigError);
      const rendered = (err as ConfigError).toString();
      expect(rendered).not.toMatch(/\s at /);
      expect(rendered).not.toMatch(/loadConfig/);
    }
  });

  it("reports multiple missing vars in ConfigSchema declaration order", () => {
    clearAll();

    let caught: ConfigError | undefined;
    try {
      loadConfig();
    } catch (err) {
      caught = err as ConfigError;
    }

    expect(caught).toBeInstanceOf(ConfigError);
    const rendered = (caught as ConfigError).toString();

    const confluenceEmailIndex = rendered.indexOf("CONFLUENCE_EMAIL");
    const confluenceTokenIndex = rendered.indexOf("CONFLUENCE_TOKEN");
    const notionTokenIndex = rendered.indexOf("NOTION_TOKEN");
    const anthropicKeyIndex = rendered.indexOf("ANTHROPIC_API_KEY");

    expect(confluenceEmailIndex).toBeGreaterThanOrEqual(0);
    expect(confluenceTokenIndex).toBeGreaterThan(confluenceEmailIndex);
    expect(notionTokenIndex).toBeGreaterThan(confluenceTokenIndex);
    expect(anthropicKeyIndex).toBeGreaterThan(notionTokenIndex);
  });

  it("returns a frozen object (mutation throws in strict mode)", () => {
    stubAll(ALL_VARS);

    const config = loadConfig();

    expect(Object.isFrozen(config)).toBe(true);
    expect(() => {
      (config as { CONFLUENCE_EMAIL: string }).CONFLUENCE_EMAIL = "mutated";
    }).toThrow(TypeError);
  });

  it("types the returned object as readonly at the type level", () => {
    stubAll(ALL_VARS);

    const config = loadConfig();

    expectTypeOf(config).toEqualTypeOf<Config>();
    expectTypeOf<Config>().toMatchTypeOf<
      Readonly<{
        CONFLUENCE_EMAIL: string;
        CONFLUENCE_TOKEN: string;
        NOTION_TOKEN: string;
        ANTHROPIC_API_KEY: string;
      }>
    >();
  });

  it("layers dotenvLoader output on top of process.env", () => {
    stubAll({
      ...ALL_VARS,
      NOTION_TOKEN: "process-env-notion-token",
    });
    const loader = vi.fn(() => ({
      NOTION_TOKEN: "dotenv-notion-token",
    }));

    const config = loadConfig({ dotenvLoader: loader });

    expect(loader).toHaveBeenCalledTimes(1);
    expect(config.NOTION_TOKEN).toBe("dotenv-notion-token");
    expect(config.CONFLUENCE_EMAIL).toBe(ALL_VARS.CONFLUENCE_EMAIL);
  });

  it("uses dotenvLoader values to fill otherwise-missing required vars", () => {
    stubAll({ ...ALL_VARS, ANTHROPIC_API_KEY: undefined });
    const loader = vi.fn(() => ({
      ANTHROPIC_API_KEY: "dotenv-anthropic-key",
    }));

    const config = loadConfig({ dotenvLoader: loader });

    expect(config.ANTHROPIC_API_KEY).toBe("dotenv-anthropic-key");
  });
});
