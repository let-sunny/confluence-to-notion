import { describe, expect, expectTypeOf, it } from "vitest";
import {
  type CreatePageInput,
  CreatePageInputSchema,
  type NotionBlock,
  NotionBlockSchema,
  type NotionPageRef,
  NotionPageRefSchema,
} from "../../src/notion/schemas.js";

describe("NotionPageRefSchema", () => {
  it("accepts an object with just an id", () => {
    const parsed = NotionPageRefSchema.safeParse({ id: "abc123" });
    expect(parsed.success).toBe(true);
  });

  it("accepts an object with id and url", () => {
    const parsed = NotionPageRefSchema.safeParse({
      id: "abc123",
      url: "https://www.notion.so/abc123",
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an empty id", () => {
    const parsed = NotionPageRefSchema.safeParse({ id: "" });
    expect(parsed.success).toBe(false);
  });

  it("rejects a missing id", () => {
    const parsed = NotionPageRefSchema.safeParse({});
    expect(parsed.success).toBe(false);
  });

  it("infers a type with required id and optional url", () => {
    expectTypeOf<NotionPageRef>().toEqualTypeOf<{ id: string; url?: string | undefined }>();
  });
});

describe("NotionBlockSchema", () => {
  const minimalRichText = [{ type: "text", text: { content: "hello" } }];

  it("accepts a minimal paragraph block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "paragraph",
      paragraph: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts minimal heading_1, heading_2, heading_3 blocks", () => {
    for (const type of ["heading_1", "heading_2", "heading_3"] as const) {
      const parsed = NotionBlockSchema.safeParse({
        type,
        [type]: { rich_text: minimalRichText },
      });
      expect(parsed.success).toBe(true);
    }
  });

  it("accepts a minimal bulleted_list_item block", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "bulleted_list_item",
      bulleted_list_item: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an unknown block type", () => {
    const parsed = NotionBlockSchema.safeParse({
      type: "mystery_block",
      mystery_block: { rich_text: minimalRichText },
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects a paragraph block missing its payload key", () => {
    const parsed = NotionBlockSchema.safeParse({ type: "paragraph" });
    expect(parsed.success).toBe(false);
  });

  it("narrows the inferred type to a discriminated union on `type`", () => {
    type Discriminant = NotionBlock["type"];
    expectTypeOf<Discriminant>().toEqualTypeOf<
      "paragraph" | "heading_1" | "heading_2" | "heading_3" | "bulleted_list_item"
    >();
  });
});

describe("CreatePageInputSchema", () => {
  const sampleBlock = {
    type: "paragraph" as const,
    paragraph: { rich_text: [{ type: "text" as const, text: { content: "body" } }] },
  };

  it("accepts a well-formed input", () => {
    const parsed = CreatePageInputSchema.safeParse({
      parent: { id: "parent-id" },
      title: "My page",
      blocks: [sampleBlock],
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts an empty blocks array", () => {
    const parsed = CreatePageInputSchema.safeParse({
      parent: { id: "parent-id" },
      title: "Empty body",
      blocks: [],
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an empty title", () => {
    const parsed = CreatePageInputSchema.safeParse({
      parent: { id: "parent-id" },
      title: "",
      blocks: [],
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects when parent.id is empty", () => {
    const parsed = CreatePageInputSchema.safeParse({
      parent: { id: "" },
      title: "Page",
      blocks: [],
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects when blocks contains an unknown type", () => {
    const parsed = CreatePageInputSchema.safeParse({
      parent: { id: "parent-id" },
      title: "Page",
      blocks: [{ type: "mystery_block", mystery_block: {} }],
    });
    expect(parsed.success).toBe(false);
  });

  it("infers a type matching the runtime schema", () => {
    expectTypeOf<CreatePageInput>().toMatchTypeOf<{
      parent: NotionPageRef;
      title: string;
      blocks: NotionBlock[];
    }>();
  });
});
