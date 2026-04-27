import { describe, expect, it } from "vitest";
import { MappingSchema } from "../../src/runs/index.js";

describe("MappingSchema", () => {
  it("parses a minimal valid mapping", () => {
    const parsed = MappingSchema.parse({
      confluencePageId: "12345",
      notionPageId: "notion-abc",
      recordedAt: "2026-04-27T10:00:00.000Z",
    });
    expect(parsed.confluencePageId).toBe("12345");
    expect(parsed.notionPageId).toBe("notion-abc");
    expect(parsed.recordedAt).toBeInstanceOf(Date);
    expect(parsed.recordedAt.toISOString()).toBe("2026-04-27T10:00:00.000Z");
    expect(parsed.notionUrl).toBeUndefined();
  });

  it("accepts an optional notionUrl", () => {
    const parsed = MappingSchema.parse({
      confluencePageId: "12345",
      notionPageId: "notion-abc",
      notionUrl: "https://www.notion.so/notion-abc",
      recordedAt: "2026-04-27T10:00:00.000Z",
    });
    expect(parsed.notionUrl).toBe("https://www.notion.so/notion-abc");
  });

  it("rejects an empty confluencePageId", () => {
    expect(() =>
      MappingSchema.parse({
        confluencePageId: "",
        notionPageId: "notion-abc",
        recordedAt: "2026-04-27T10:00:00.000Z",
      }),
    ).toThrow();
  });

  it("rejects an empty notionPageId", () => {
    expect(() =>
      MappingSchema.parse({
        confluencePageId: "12345",
        notionPageId: "",
        recordedAt: "2026-04-27T10:00:00.000Z",
      }),
    ).toThrow();
  });

  it("defaults recordedAt to a current Date when omitted", () => {
    const before = Date.now();
    const parsed = MappingSchema.parse({
      confluencePageId: "12345",
      notionPageId: "notion-abc",
    });
    const after = Date.now();
    expect(parsed.recordedAt).toBeInstanceOf(Date);
    const ts = parsed.recordedAt.getTime();
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(after);
  });
});
