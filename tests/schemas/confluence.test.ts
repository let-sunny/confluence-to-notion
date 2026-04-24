import { describe, expect, it } from "vitest";
import {
  ConfluenceAttachmentSchema,
  ConfluencePageSchema,
  ConfluenceUserSchema,
  PageTreeNodeSchema,
} from "../../src/schemas/confluence.js";

describe("ConfluencePageSchema", () => {
  const validPage = {
    id: "12345",
    title: "Home",
    type: "page",
    space: { key: "DEV", name: "Development" },
    body: { storage: { value: "<p>hi</p>", representation: "storage" } },
    version: { number: 3 },
  };

  it("parses a minimal valid page payload", () => {
    const parsed = ConfluencePageSchema.safeParse(validPage);
    expect(parsed.success).toBe(true);
  });

  it("passes through unknown fields from the Confluence REST API", () => {
    const parsed = ConfluencePageSchema.safeParse({
      ...validPage,
      _expandable: { ancestors: "/rest/api/content/12345/ancestor" },
      extensions: { position: 1 },
      _links: { self: "/rest/api/content/12345" },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects when id is missing", () => {
    const { id: _id, ...rest } = validPage;
    const parsed = ConfluencePageSchema.safeParse(rest);
    expect(parsed.success).toBe(false);
  });

  it("rejects when body.storage.value is missing", () => {
    const parsed = ConfluencePageSchema.safeParse({
      ...validPage,
      body: { storage: { representation: "storage" } },
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects when version.number is the wrong type", () => {
    const parsed = ConfluencePageSchema.safeParse({
      ...validPage,
      version: { number: "3" },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("PageTreeNodeSchema", () => {
  it("parses a flat leaf node", () => {
    const parsed = PageTreeNodeSchema.safeParse({
      id: "1",
      title: "Leaf",
      children: [],
    });
    expect(parsed.success).toBe(true);
  });

  it("parses a recursively-nested tree", () => {
    const tree = {
      id: "root",
      title: "Root",
      children: [
        {
          id: "a",
          title: "A",
          children: [{ id: "a1", title: "A1", children: [] }],
        },
        { id: "b", title: "B", children: [] },
      ],
    };
    const parsed = PageTreeNodeSchema.safeParse(tree);
    expect(parsed.success).toBe(true);
  });

  it("rejects when a nested child is missing its id", () => {
    const bad = {
      id: "root",
      title: "Root",
      children: [{ title: "missing-id", children: [] }],
    };
    const parsed = PageTreeNodeSchema.safeParse(bad);
    expect(parsed.success).toBe(false);
  });

  it("rejects when children is not an array", () => {
    const parsed = PageTreeNodeSchema.safeParse({
      id: "root",
      title: "Root",
      children: "none",
    });
    expect(parsed.success).toBe(false);
  });
});

describe("ConfluenceUserSchema", () => {
  const validUser = {
    accountId: "u-123",
    displayName: "Jane Doe",
    email: "jane@example.com",
  };

  it("parses a valid user payload", () => {
    const parsed = ConfluenceUserSchema.safeParse(validUser);
    expect(parsed.success).toBe(true);
  });

  it("passes through unknown extra fields", () => {
    const parsed = ConfluenceUserSchema.safeParse({
      ...validUser,
      profilePicture: { path: "/x.png" },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects when accountId is missing", () => {
    const { accountId: _accountId, ...rest } = validUser;
    const parsed = ConfluenceUserSchema.safeParse(rest);
    expect(parsed.success).toBe(false);
  });
});

describe("ConfluenceAttachmentSchema", () => {
  const validAttachment = {
    id: "att-1",
    title: "diagram.png",
    mediaType: "image/png",
    _links: { download: "/download/attachments/1/diagram.png" },
  };

  it("parses a valid attachment payload", () => {
    const parsed = ConfluenceAttachmentSchema.safeParse(validAttachment);
    expect(parsed.success).toBe(true);
  });

  it("passes through unknown extra fields on the attachment", () => {
    const parsed = ConfluenceAttachmentSchema.safeParse({
      ...validAttachment,
      fileSize: 2048,
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects when _links.download is missing", () => {
    const parsed = ConfluenceAttachmentSchema.safeParse({
      ...validAttachment,
      _links: {},
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects when mediaType is the wrong type", () => {
    const parsed = ConfluenceAttachmentSchema.safeParse({
      ...validAttachment,
      mediaType: 123,
    });
    expect(parsed.success).toBe(false);
  });
});
