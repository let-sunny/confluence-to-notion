import { describe, expect, it } from "vitest";
import {
  ConversionResultSchema,
  NotionPropertyTypeSchema,
  ResolutionDataSchema,
  ResolutionEntrySchema,
  TableRuleSchema,
  TableRuleSetSchema,
  UnresolvedItemSchema,
} from "../../src/converter/schemas.js";

describe("NotionPropertyTypeSchema", () => {
  it("accepts every Python-compatible property type", () => {
    for (const value of ["title", "rich_text", "select", "date", "people", "url"] as const) {
      expect(NotionPropertyTypeSchema.safeParse(value).success).toBe(true);
    }
  });

  it("rejects unknown property types", () => {
    expect(NotionPropertyTypeSchema.safeParse("number").success).toBe(false);
  });
});

describe("ResolutionEntrySchema", () => {
  it("accepts every resolvedBy literal", () => {
    for (const resolvedBy of [
      "user_input",
      "ai_inference",
      "api_call",
      "auto_lookup",
      "notion_migration",
    ] as const) {
      const parsed = ResolutionEntrySchema.safeParse({ resolvedBy, value: {} });
      expect(parsed.success).toBe(true);
    }
  });

  it("rejects an unknown resolvedBy literal", () => {
    const parsed = ResolutionEntrySchema.safeParse({ resolvedBy: "guess", value: {} });
    expect(parsed.success).toBe(false);
  });

  it("accepts an arbitrary record as value", () => {
    const parsed = ResolutionEntrySchema.safeParse({
      resolvedBy: "user_input",
      value: { anything: 1, nested: { deep: true } },
    });
    expect(parsed.success).toBe(true);
  });

  it("treats confidence as optional", () => {
    const parsed = ResolutionEntrySchema.safeParse({ resolvedBy: "user_input", value: {} });
    expect(parsed.success).toBe(true);
  });

  it("accepts confidence in [0, 1]", () => {
    for (const confidence of [0, 0.5, 1]) {
      const parsed = ResolutionEntrySchema.safeParse({
        resolvedBy: "user_input",
        value: {},
        confidence,
      });
      expect(parsed.success).toBe(true);
    }
  });

  it("rejects confidence below 0 or above 1", () => {
    expect(
      ResolutionEntrySchema.safeParse({
        resolvedBy: "user_input",
        value: {},
        confidence: -0.1,
      }).success,
    ).toBe(false);
    expect(
      ResolutionEntrySchema.safeParse({
        resolvedBy: "user_input",
        value: {},
        confidence: 1.2,
      }).success,
    ).toBe(false);
  });

  it("coerces ISO-8601 resolvedAt strings to Date", () => {
    const parsed = ResolutionEntrySchema.safeParse({
      resolvedBy: "user_input",
      value: {},
      resolvedAt: "2026-04-24T10:00:00Z",
    });
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.resolvedAt).toBeInstanceOf(Date);
      expect(parsed.data.resolvedAt.toISOString()).toBe("2026-04-24T10:00:00.000Z");
    }
  });

  it("defaults resolvedAt to near-now when omitted", () => {
    const before = Date.now();
    const parsed = ResolutionEntrySchema.safeParse({ resolvedBy: "user_input", value: {} });
    const after = Date.now();
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      const ts = parsed.data.resolvedAt.getTime();
      expect(ts).toBeGreaterThanOrEqual(before);
      expect(ts).toBeLessThanOrEqual(after);
    }
  });
});

describe("UnresolvedItemSchema", () => {
  it("accepts every kind literal", () => {
    for (const kind of ["macro", "jira_server", "page_link", "synced_block", "table"] as const) {
      const parsed = UnresolvedItemSchema.safeParse({
        kind,
        identifier: "x",
        sourcePageId: "123",
      });
      expect(parsed.success).toBe(true);
    }
  });

  it("rejects unknown kinds", () => {
    const parsed = UnresolvedItemSchema.safeParse({
      kind: "other",
      identifier: "x",
      sourcePageId: "123",
    });
    expect(parsed.success).toBe(false);
  });

  it("requires identifier and sourcePageId but allows empty strings (Python parity)", () => {
    const parsed = UnresolvedItemSchema.safeParse({
      kind: "macro",
      identifier: "",
      sourcePageId: "",
    });
    expect(parsed.success).toBe(true);
  });

  it("fails when identifier is missing", () => {
    const parsed = UnresolvedItemSchema.safeParse({ kind: "macro", sourcePageId: "123" });
    expect(parsed.success).toBe(false);
  });

  it("allows contextXhtml to be null or omitted", () => {
    expect(
      UnresolvedItemSchema.safeParse({
        kind: "macro",
        identifier: "x",
        sourcePageId: "123",
        contextXhtml: null,
      }).success,
    ).toBe(true);
    expect(
      UnresolvedItemSchema.safeParse({
        kind: "macro",
        identifier: "x",
        sourcePageId: "123",
      }).success,
    ).toBe(true);
  });
});

describe("ResolutionDataSchema", () => {
  it("defaults entries to empty record", () => {
    const parsed = ResolutionDataSchema.safeParse({});
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.entries).toEqual({});
  });

  it("accepts a record of ResolutionEntry", () => {
    const parsed = ResolutionDataSchema.safeParse({
      entries: {
        "macro:jira": { resolvedBy: "user_input", value: { url: "https://example.com" } },
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an entry with an invalid resolvedBy", () => {
    const parsed = ResolutionDataSchema.safeParse({
      entries: { "macro:jira": { resolvedBy: "oops", value: {} } },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("ConversionResultSchema", () => {
  it("applies defaults for blocks, unresolved, usedRules", () => {
    const parsed = ConversionResultSchema.safeParse({});
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.blocks).toEqual([]);
      expect(parsed.data.unresolved).toEqual([]);
      expect(parsed.data.usedRules).toEqual({});
    }
  });

  it("accepts arbitrary block records", () => {
    const parsed = ConversionResultSchema.safeParse({
      blocks: [{ type: "paragraph", anything: true }, { foo: 1 }],
    });
    expect(parsed.success).toBe(true);
  });

  it("validates each unresolved entry", () => {
    const parsed = ConversionResultSchema.safeParse({
      unresolved: [{ kind: "macro", identifier: "jira", sourcePageId: "1" }],
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an invalid unresolved entry", () => {
    const parsed = ConversionResultSchema.safeParse({
      unresolved: [{ kind: "unknown", identifier: "jira", sourcePageId: "1" }],
    });
    expect(parsed.success).toBe(false);
  });

  it("accepts usedRules as string → number", () => {
    const parsed = ConversionResultSchema.safeParse({ usedRules: { "rule-a": 3 } });
    expect(parsed.success).toBe(true);
  });
});

describe("TableRuleSchema", () => {
  it("requires isDatabase", () => {
    const parsed = TableRuleSchema.safeParse({});
    expect(parsed.success).toBe(false);
  });

  it("accepts a minimal rule with only isDatabase", () => {
    const parsed = TableRuleSchema.safeParse({ isDatabase: true });
    expect(parsed.success).toBe(true);
  });

  it("accepts null titleColumn and columnTypes", () => {
    const parsed = TableRuleSchema.safeParse({
      isDatabase: true,
      titleColumn: null,
      columnTypes: null,
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts a NotionPropertyType map for columnTypes", () => {
    const parsed = TableRuleSchema.safeParse({
      isDatabase: true,
      titleColumn: "owner",
      columnTypes: { owner: "title", status: "select" },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an invalid NotionPropertyType inside columnTypes", () => {
    const parsed = TableRuleSchema.safeParse({
      isDatabase: true,
      columnTypes: { status: "number" },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("TableRuleSetSchema", () => {
  it("defaults rules to empty record", () => {
    const parsed = TableRuleSetSchema.safeParse({});
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.rules).toEqual({});
  });

  it("rejects an empty signature key", () => {
    const parsed = TableRuleSetSchema.safeParse({
      rules: { "": { isDatabase: false } },
    });
    expect(parsed.success).toBe(false);
  });

  it("accepts a rule whose titleColumn matches a signature column", () => {
    const parsed = TableRuleSetSchema.safeParse({
      rules: {
        "status|owner": { isDatabase: true, titleColumn: "owner" },
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a titleColumn that does not appear in the signature columns", () => {
    const parsed = TableRuleSetSchema.safeParse({
      rules: {
        "status|owner": { isDatabase: true, titleColumn: "missing" },
      },
    });
    expect(parsed.success).toBe(false);
    if (!parsed.success) {
      const joined = parsed.error.issues.map((i) => i.message).join(" ");
      expect(joined).toContain("missing");
      expect(joined).toContain("status");
      expect(joined).toContain("owner");
    }
  });

  it("accepts a null titleColumn without checking signature membership", () => {
    const parsed = TableRuleSetSchema.safeParse({
      rules: { "status|owner": { isDatabase: false, titleColumn: null } },
    });
    expect(parsed.success).toBe(true);
  });
});
