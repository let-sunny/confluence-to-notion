import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createNotionClient } from "../../src/notion/client.js";

// Stand-in for @notionhq/client's APIResponseError. The retry wrapper only
// needs to branch on the HTTP status, so duck-typing with a `status` field is
// enough — we inject this into the fake client below.
class FakeAPIResponseError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(status: number, code = "rate_limited") {
    super(`API error ${status}`);
    this.code = code;
    this.status = status;
  }
}

function makeFakeClient() {
  return {
    pages: {
      create: vi.fn(),
      update: vi.fn(),
    },
    blocks: {
      children: {
        append: vi.fn(),
      },
    },
  };
}

const sampleBlock = {
  type: "paragraph" as const,
  paragraph: { rich_text: [{ type: "text" as const, text: { content: "hi" } }] },
};

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("createNotionClient — createPage", () => {
  it("calls client.pages.create with the expected body and returns a NotionPage", async () => {
    const fake = makeFakeClient();
    fake.pages.create.mockResolvedValue({
      id: "new-page-id",
      url: "https://www.notion.so/new-page-id",
    });

    const notion = createNotionClient({
      token: "fake-token",
      client: fake as never,
    });

    const page = await notion.createPage({
      parent: { id: "parent-id" },
      title: "Ported page",
      blocks: [sampleBlock],
    });

    expect(fake.pages.create).toHaveBeenCalledTimes(1);
    expect(fake.pages.create).toHaveBeenCalledWith({
      parent: { type: "page_id", page_id: "parent-id" },
      properties: {
        title: { title: [{ type: "text", text: { content: "Ported page" } }] },
      },
      children: [sampleBlock],
    });
    expect(page).toEqual({
      id: "new-page-id",
      url: "https://www.notion.so/new-page-id",
    });
  });
});

describe("createNotionClient — appendBlocks", () => {
  it("calls client.blocks.children.append with the correct block_id + children and resolves void", async () => {
    const fake = makeFakeClient();
    fake.blocks.children.append.mockResolvedValue({ results: [] });

    const notion = createNotionClient({ token: "fake", client: fake as never });
    const result = await notion.appendBlocks("page-id", [sampleBlock]);

    expect(fake.blocks.children.append).toHaveBeenCalledTimes(1);
    expect(fake.blocks.children.append).toHaveBeenCalledWith({
      block_id: "page-id",
      children: [sampleBlock],
    });
    expect(result).toBeUndefined();
  });
});

describe("createNotionClient — updatePageTitle", () => {
  it("calls client.pages.update with the title property", async () => {
    const fake = makeFakeClient();
    fake.pages.update.mockResolvedValue({});

    const notion = createNotionClient({ token: "fake", client: fake as never });
    await notion.updatePageTitle("page-id", "Renamed");

    expect(fake.pages.update).toHaveBeenCalledTimes(1);
    expect(fake.pages.update).toHaveBeenCalledWith({
      page_id: "page-id",
      properties: {
        title: { title: [{ type: "text", text: { content: "Renamed" } }] },
      },
    });
  });
});

describe("createNotionClient — retry on 429", () => {
  it("retries up to maxRetries times and succeeds when the underlying call finally returns", async () => {
    const fake = makeFakeClient();
    fake.pages.create
      .mockRejectedValueOnce(new FakeAPIResponseError(429))
      .mockRejectedValueOnce(new FakeAPIResponseError(429))
      .mockResolvedValueOnce({ id: "ok", url: "https://www.notion.so/ok" });

    const notion = createNotionClient({
      token: "fake",
      client: fake as never,
      maxRetries: 5,
    });

    const pending = notion.createPage({
      parent: { id: "parent-id" },
      title: "Retried",
      blocks: [],
    });
    // Advance past all backoff windows; base 500ms * 2**attempt with 250ms
    // jitter means 2 retries sleep well under a few seconds in total.
    await vi.advanceTimersByTimeAsync(30_000);

    const page = await pending;
    expect(fake.pages.create).toHaveBeenCalledTimes(3);
    expect(page.id).toBe("ok");
  });

  it("rethrows the original 429 error after 6 total attempts (1 initial + 5 retries)", async () => {
    const fake = makeFakeClient();
    const final = new FakeAPIResponseError(429);
    fake.pages.create.mockRejectedValue(final);

    const notion = createNotionClient({
      token: "fake",
      client: fake as never,
      maxRetries: 5,
    });

    const captured = notion
      .createPage({ parent: { id: "parent-id" }, title: "Exhausted", blocks: [] })
      .catch((err: unknown) => err);
    // Five exponential sleeps (500, 1000, 2000, 4000, 8000 ms) plus jitter.
    await vi.advanceTimersByTimeAsync(600_000);

    await expect(captured).resolves.toBe(final);
    expect(fake.pages.create).toHaveBeenCalledTimes(6);
  });

  it("rethrows non-429 errors immediately without retrying", async () => {
    const fake = makeFakeClient();
    const err = new FakeAPIResponseError(400, "validation_error");
    fake.pages.create.mockRejectedValue(err);

    const notion = createNotionClient({
      token: "fake",
      client: fake as never,
      maxRetries: 5,
    });

    await expect(
      notion.createPage({ parent: { id: "parent-id" }, title: "Invalid", blocks: [] }),
    ).rejects.toBe(err);
    expect(fake.pages.create).toHaveBeenCalledTimes(1);
  });
});
