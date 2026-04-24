import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ResolutionStore } from "../../src/converter/resolution.js";

describe("ResolutionStore", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "c2n-resolution-"));
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("returns an empty store when the file does not exist", async () => {
    const store = await ResolutionStore.open(join(dir, "missing.json"));
    expect(store.keys()).toEqual([]);
  });

  it("loads entries from an existing JSON file", async () => {
    const path = join(dir, "resolution.json");
    await writeFile(
      path,
      JSON.stringify({
        entries: {
          "jira_server:ASF JIRA": {
            resolvedBy: "user_input",
            value: { url: "https://issues.apache.org/jira" },
            resolvedAt: "2026-04-16T00:00:00.000Z",
          },
        },
      }),
      "utf8",
    );
    const store = await ResolutionStore.open(path);
    expect(store.keys()).toContain("jira_server:ASF JIRA");
  });

  it("returns a hit on lookup for a known key", async () => {
    const store = await ResolutionStore.open(join(dir, "res.json"));
    store.add("macro:toc", {
      resolvedBy: "ai_inference",
      value: { notion_block_type: "table_of_contents" },
      confidence: 0.95,
    });
    const entry = store.lookup("macro:toc");
    expect(entry).toBeDefined();
    expect(entry?.value.notion_block_type).toBe("table_of_contents");
    expect(entry?.confidence).toBe(0.95);
    expect(entry?.resolvedBy).toBe("ai_inference");
  });

  it("returns undefined on lookup for an unknown key", async () => {
    const store = await ResolutionStore.open(join(dir, "res.json"));
    expect(store.lookup("macro:nope")).toBeUndefined();
  });

  it("persists entries across save + reload", async () => {
    const path = join(dir, "res.json");
    const store = await ResolutionStore.open(path);
    store.add("jira_server:My JIRA", {
      resolvedBy: "user_input",
      value: { url: "https://jira.mycompany.com" },
    });
    await store.save();

    const reloaded = await ResolutionStore.open(path);
    const entry = reloaded.lookup("jira_server:My JIRA");
    expect(entry).toBeDefined();
    expect(entry?.value.url).toBe("https://jira.mycompany.com");
  });

  it("overwrites an existing entry on add", async () => {
    const store = await ResolutionStore.open(join(dir, "res.json"));
    store.add("macro:x", {
      resolvedBy: "ai_inference",
      value: { a: 1 },
      confidence: 0.5,
    });
    store.add("macro:x", { resolvedBy: "user_input", value: { a: 2 } });

    const entry = store.lookup("macro:x");
    expect(entry).toBeDefined();
    expect(entry?.value).toEqual({ a: 2 });
    expect(entry?.resolvedBy).toBe("user_input");
  });

  it("returns all stored keys via keys()", async () => {
    const store = await ResolutionStore.open(join(dir, "res.json"));
    store.add("macro:a", {
      resolvedBy: "ai_inference",
      value: {},
      confidence: 0.9,
    });
    store.add("jira_server:b", { resolvedBy: "user_input", value: {} });
    expect(new Set(store.keys())).toEqual(new Set(["macro:a", "jira_server:b"]));
  });

  it("falls back to an empty store on corrupt JSON", async () => {
    const path = join(dir, "bad.json");
    await writeFile(path, "not valid json", "utf8");
    const store = await ResolutionStore.open(path);
    expect(store.keys()).toEqual([]);
  });

  it("creates parent directories on save", async () => {
    const path = join(dir, "nested", "a", "b", "res.json");
    const store = await ResolutionStore.open(path);
    store.add("macro:z", { resolvedBy: "user_input", value: {} });
    await store.save();

    const contents = await readFile(path, "utf8");
    expect(JSON.parse(contents)).toBeTruthy();
  });
});
