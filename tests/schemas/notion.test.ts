import { describe, expect, expectTypeOf, it } from "vitest";
import { type NotionBlock, NotionBlockSchema } from "../../src/schemas/notion.js";

const minimalRichText = [{ type: "text", text: { content: "hello" } }];
const richTextPayload = { rich_text: minimalRichText };

describe("NotionBlockSchema — text-shaped blocks", () => {
  const textShapedTypes = [
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "toggle",
    "quote",
  ] as const;

  for (const type of textShapedTypes) {
    it(`accepts a minimal ${type} block`, () => {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: richTextPayload,
      });
      expect(parsed.success).toBe(true);
    });

    it(`rejects ${type} when the payload key is missing`, () => {
      const parsed = NotionBlockSchema.safeParse({ type });
      expect(parsed.success).toBe(false);
    });
  }
});

describe("NotionBlockSchema — to_do block", () => {
  it("accepts a minimal to_do block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "to_do",
      to_do: { rich_text: minimalRichText, checked: false },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a to_do block missing the checked flag", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "to_do",
      to_do: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — code block", () => {
  it("accepts a minimal code block with a language", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "code",
      code: {
        rich_text: minimalRichText,
        language: "typescript",
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a code block missing the language", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "code",
      code: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — callout block", () => {
  it("accepts a minimal callout block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "callout",
      callout: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a callout when rich_text is the wrong type", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "callout",
      callout: { rich_text: "oops" },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — file-shaped blocks", () => {
  const fileShapedTypes = ["image", "video", "file"] as const;

  for (const type of fileShapedTypes) {
    it(`accepts an external ${type} block`, () => {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: {
          type: "external",
          external: { url: "https://example.com/asset" },
        },
      });
      expect(parsed.success).toBe(true);
    });

    it(`rejects an ${type} block with an unknown source kind`, () => {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: {
          type: "mystery",
          mystery: { url: "https://example.com/asset" },
        },
      });
      expect(parsed.success).toBe(false);
    });
  }
});

describe("NotionBlockSchema — divider block", () => {
  it("accepts a divider block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "divider",
      divider: {},
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a divider block missing its payload key", () => {
    const parsed = NotionBlockSchema.safeParse({ type: "divider" });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — table and table_row", () => {
  it("accepts a minimal table block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "table",
      table: {
        table_width: 2,
        has_column_header: true,
        has_row_header: false,
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a table block missing table_width", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "table",
      table: { has_column_header: false, has_row_header: false },
    });
    expect(parsed.success).toBe(false);
  });

  it("accepts a minimal table_row block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "table_row",
      table_row: { cells: [minimalRichText, minimalRichText] },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a table_row block missing cells", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "table_row",
      table_row: {},
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — column_list and column", () => {
  it("accepts a minimal column_list block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "column_list",
      column_list: {},
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts a minimal column block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "column",
      column: {},
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a column_list block missing its payload key", () => {
    const parsed = NotionBlockSchema.safeParse({ type: "column_list" });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — link-shaped blocks", () => {
  const linkShapedTypes = ["bookmark", "embed", "link_preview"] as const;

  for (const type of linkShapedTypes) {
    it(`accepts a minimal ${type} block`, () => {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: { url: "https://example.com" },
      });
      expect(parsed.success).toBe(true);
    });

    it(`rejects a ${type} block missing the url`, () => {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: {},
      });
      expect(parsed.success).toBe(false);
    });
  }
});

describe("NotionBlockSchema — child_page block", () => {
  it("accepts a minimal child_page block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "child_page",
      child_page: { title: "Subpage" },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a child_page block missing the title", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "child_page",
      child_page: {},
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — synced_block", () => {
  it("accepts an original synced_block (synced_from is null)", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "synced_block",
      synced_block: { synced_from: null },
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts a duplicate synced_block referencing an original", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "synced_block",
      synced_block: {
        synced_from: { type: "block_id", block_id: "abc-123" },
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a synced_block missing synced_from", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "synced_block",
      synced_block: {},
    });
    expect(parsed.success).toBe(false);
  });
});

describe("NotionBlockSchema — discriminated union", () => {
  it("rejects an unknown block type", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "mystery_block",
      mystery_block: {},
    });
    expect(parsed.success).toBe(false);
  });

  it("narrows the inferred type on `type`", () => {
    type Discriminant = NotionBlock["type"];
    expectTypeOf<Discriminant>().toEqualTypeOf<
      | "paragraph"
      | "heading_1"
      | "heading_2"
      | "heading_3"
      | "bulleted_list_item"
      | "numbered_list_item"
      | "to_do"
      | "toggle"
      | "code"
      | "quote"
      | "callout"
      | "image"
      | "video"
      | "file"
      | "divider"
      | "table"
      | "table_row"
      | "column_list"
      | "column"
      | "bookmark"
      | "embed"
      | "link_preview"
      | "child_page"
      | "synced_block"
    >();
  });
});
