import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ResolutionStore } from "../../src/converter/resolution.js";
import {
  type ResolveReport,
  type ResolveStrategy,
  Resolver,
} from "../../src/converter/resolver.js";
import type { ResolutionEntry, UnresolvedItem } from "../../src/converter/schemas.js";

function macro(identifier: string, page = "pg-1"): UnresolvedItem {
  return { kind: "macro", identifier, sourcePageId: page };
}

function pageLink(identifier: string, page = "pg-1"): UnresolvedItem {
  return { kind: "page_link", identifier, sourcePageId: page };
}

class FakeStrategy implements ResolveStrategy {
  callCount = 0;
  constructor(private readonly known: Record<string, Record<string, unknown>>) {}

  async tryResolve(item: UnresolvedItem): Promise<ResolutionEntry | null> {
    this.callCount += 1;
    const value = this.known[item.identifier];
    if (value === undefined) return null;
    return {
      resolvedBy: "ai_inference",
      value,
      confidence: 0.9,
      resolvedAt: new Date(),
    };
  }
}

class FailStrategy implements ResolveStrategy {
  async tryResolve(_item: UnresolvedItem): Promise<ResolutionEntry | null> {
    return null;
  }
}

describe("Resolver", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "c2n-resolution-"));
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  describe("store lookup", () => {
    it("skips strategies when the store already has the key", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      store.add("macro:known-macro", {
        resolvedBy: "user_input",
        value: { notion_block_type: "callout" },
      });
      const strategy = new FakeStrategy({});
      const resolver = new Resolver(store, [strategy]);

      const report = await resolver.resolve([macro("known-macro")]);

      expect(report.resolvedCount).toBe(1);
      expect(report.fromStore).toBe(1);
      expect(report.newlyResolved).toBe(0);
      expect(report.stillUnresolved).toEqual([]);
      expect(strategy.callCount).toBe(0);
    });

    it("invokes a strategy on a store miss and persists the result", async () => {
      const path = join(dir, "res.json");
      const store = await ResolutionStore.open(path);
      const strategy = new FakeStrategy({ "new-macro": { notion_block_type: "table" } });
      const resolver = new Resolver(store, [strategy]);

      const report = await resolver.resolve([macro("new-macro")]);

      expect(report.resolvedCount).toBe(1);
      expect(report.fromStore).toBe(0);
      expect(report.newlyResolved).toBe(1);
      expect(strategy.callCount).toBe(1);

      const reloaded = await ResolutionStore.open(path);
      expect(reloaded.lookup("macro:new-macro")).toBeDefined();
    });
  });

  describe("deduplication", () => {
    it("resolves duplicate items only once", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const strategy = new FakeStrategy({ "dup-macro": { type: "callout" } });
      const resolver = new Resolver(store, [strategy]);

      const items = [macro("dup-macro", "pg-1"), macro("dup-macro", "pg-2")];
      const report = await resolver.resolve(items);

      expect(report.resolvedCount).toBe(1);
      expect(strategy.callCount).toBe(1);
    });

    it("keeps different kinds with the same identifier distinct", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const strategy = new FakeStrategy({ foo: { value: "resolved" } });
      const resolver = new Resolver(store, [strategy]);

      const items = [macro("foo"), pageLink("foo")];
      const report = await resolver.resolve(items);

      expect(report.resolvedCount).toBe(2);
      expect(strategy.callCount).toBe(2);
    });
  });

  describe("strategy chain", () => {
    it("stops at the first strategy that returns a non-null entry", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const s1 = new FakeStrategy({ x: { from: "s1" } });
      const s2 = new FakeStrategy({ x: { from: "s2" } });
      const resolver = new Resolver(store, [s1, s2]);

      const report = await resolver.resolve([macro("x")]);

      expect(report.newlyResolved).toBe(1);
      expect(store.lookup("macro:x")?.value).toEqual({ from: "s1" });
      expect(s1.callCount).toBe(1);
      expect(s2.callCount).toBe(0);
    });

    it("falls through to the next strategy when the first returns null", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const s1 = new FailStrategy();
      const s2 = new FakeStrategy({ y: { from: "s2" } });
      const resolver = new Resolver(store, [s1, s2]);

      const report = await resolver.resolve([macro("y")]);

      expect(report.newlyResolved).toBe(1);
      expect(store.lookup("macro:y")).toBeDefined();
    });

    it("leaves items in stillUnresolved when every strategy fails", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const resolver = new Resolver(store, [new FailStrategy()]);

      const report = await resolver.resolve([macro("mystery")]);

      expect(report.resolvedCount).toBe(0);
      expect(report.stillUnresolved).toEqual([macro("mystery")]);
    });
  });

  describe("report counts", () => {
    it("reports mixed resolutions accurately", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      store.add("macro:cached", { resolvedBy: "user_input", value: { cached: true } });
      const strategy = new FakeStrategy({ resolvable: { new: true } });
      const resolver = new Resolver(store, [strategy]);

      const items = [macro("cached"), macro("resolvable"), macro("impossible")];
      const report: ResolveReport = await resolver.resolve(items);

      expect(report.resolvedCount).toBe(2);
      expect(report.fromStore).toBe(1);
      expect(report.newlyResolved).toBe(1);
      expect(report.stillUnresolved).toHaveLength(1);
      expect(report.stillUnresolved[0]?.identifier).toBe("impossible");
    });

    it("returns zero counts on an empty input list", async () => {
      const store = await ResolutionStore.open(join(dir, "res.json"));
      const resolver = new Resolver(store, []);

      const report = await resolver.resolve([]);

      expect(report.resolvedCount).toBe(0);
      expect(report.fromStore).toBe(0);
      expect(report.newlyResolved).toBe(0);
      expect(report.stillUnresolved).toEqual([]);
    });
  });
});
