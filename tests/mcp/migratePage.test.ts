import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";
import type {
  ConfluenceAdapter,
  GetPageTreeOptions,
  ListSpacePagesOptions,
  ListSpacePagesResult,
} from "../../src/confluence/client.js";
import type { ConfluencePage, PageTreeNode } from "../../src/confluence/schemas.js";
import { createServer } from "../../src/mcp/server.js";
import type { NotionAdapter } from "../../src/notion/client.js";
import type { CreatePageInput, NotionBlock, NotionPageRef } from "../../src/notion/schemas.js";

interface NotionState {
  createPageCalls: CreatePageInput[];
  appendBlocksCalls: Array<{ pageId: string; blocks: NotionBlock[] }>;
}

interface ConfluenceState {
  getPageCalls: string[];
}

function buildPage(overrides: Partial<ConfluencePage> = {}): ConfluencePage {
  return {
    id: "12345",
    title: "Migrate me",
    type: "page",
    space: { key: "DOCS", name: "Docs" },
    body: {
      storage: { value: "<p>hello <strong>world</strong></p>", representation: "storage" },
    },
    version: { number: 1 },
    ...overrides,
  } as ConfluencePage;
}

function fakeConfluence(state: ConfluenceState, page: ConfluencePage): ConfluenceAdapter {
  return {
    async getPage(pageId: string): Promise<ConfluencePage> {
      state.getPageCalls.push(pageId);
      return page;
    },
    async getPageTree(_rootPageId: string, _options: GetPageTreeOptions): Promise<PageTreeNode> {
      throw new Error("not used");
    },
    async listSpacePages(
      _spaceKey: string,
      _options: ListSpacePagesOptions,
    ): Promise<ListSpacePagesResult> {
      throw new Error("not used");
    },
    async getAttachment(_pageId: string, _filename: string): Promise<Uint8Array> {
      throw new Error("not used");
    },
  };
}

function fakeNotion(state: NotionState, ref: NotionPageRef): NotionAdapter {
  return {
    async createPage(input: CreatePageInput): Promise<NotionPageRef> {
      state.createPageCalls.push(input);
      return ref;
    },
    async appendBlocks(pageId: string, blocks: NotionBlock[]): Promise<void> {
      state.appendBlocksCalls.push({ pageId, blocks });
    },
    async updatePageTitle(_pageId: string, _title: string): Promise<void> {
      throw new Error("not used");
    },
  };
}

interface ConnectOptions {
  withConfluence?: boolean;
  withNotion?: boolean;
  page?: ConfluencePage;
  notionRef?: NotionPageRef;
}

async function connect(opts: ConnectOptions = {}) {
  const confluenceState: ConfluenceState = { getPageCalls: [] };
  const notionState: NotionState = { createPageCalls: [], appendBlocksCalls: [] };
  const page = opts.page ?? buildPage();
  const ref: NotionPageRef = opts.notionRef ?? {
    id: "notion-new-page",
    url: "https://www.notion.so/notion-new-page",
  };
  const serverOptions: Parameters<typeof createServer>[0] = {};
  if (opts.withConfluence !== false) {
    serverOptions.confluenceFactory = () => fakeConfluence(confluenceState, page);
  }
  if (opts.withNotion !== false) {
    serverOptions.notionFactory = () => fakeNotion(notionState, ref);
  }
  const server = createServer(serverOptions);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "migrate-page-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server, confluenceState, notionState, page, ref };
}

describe("c2n_migrate_page tool handler", () => {
  it("rejects with InvalidRequest naming NOTION_TOKEN when no notionFactory is wired", async () => {
    const { client, server } = await connect({ withNotion: false });
    try {
      await expect(
        client.callTool({
          name: "c2n_migrate_page",
          arguments: { pageIdOrUrl: "1", parentNotionPageId: "abc" },
        }),
      ).rejects.toThrow(/NOTION_TOKEN/);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("fetches the page, creates a Notion page, appends converted blocks, and returns a JSON payload", async () => {
    const page = buildPage({
      id: "9001",
      title: "Page being migrated",
      body: {
        storage: { value: "<p>hello world</p>", representation: "storage" },
      },
    });
    const ref: NotionPageRef = {
      id: "notion-9001",
      url: "https://www.notion.so/notion-9001",
    };
    const { client, server, confluenceState, notionState } = await connect({
      page,
      notionRef: ref,
    });
    try {
      const response = await client.callTool({
        name: "c2n_migrate_page",
        arguments: { pageIdOrUrl: "9001", parentNotionPageId: "parent-abc" },
      });
      expect(response.isError).toBeFalsy();
      expect(confluenceState.getPageCalls).toEqual(["9001"]);
      expect(notionState.createPageCalls).toHaveLength(1);
      const createCall = notionState.createPageCalls[0];
      expect(createCall?.parent.id).toBe("parent-abc");
      expect(createCall?.title).toBe("Page being migrated");
      expect(notionState.appendBlocksCalls).toHaveLength(1);
      const appendCall = notionState.appendBlocksCalls[0];
      expect(appendCall?.pageId).toBe("notion-9001");
      expect(Array.isArray(appendCall?.blocks)).toBe(true);
      expect((appendCall?.blocks ?? []).length).toBeGreaterThan(0);
      const content = response.content as Array<{ type: string; text: string }>;
      expect(content[0]?.type).toBe("text");
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed.notionPageId).toBe("notion-9001");
      expect(parsed.sourcePageId).toBe("9001");
      expect(typeof parsed.blockCount).toBe("number");
      expect(parsed.blockCount).toBe(appendCall?.blocks.length);
      expect(typeof parsed.unresolvedCount).toBe("number");
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("dryRun: true skips both createPage and appendBlocks but still reports conversion stats", async () => {
    const { client, server, confluenceState, notionState } = await connect();
    try {
      const response = await client.callTool({
        name: "c2n_migrate_page",
        arguments: {
          pageIdOrUrl: "12345",
          parentNotionPageId: "parent-abc",
          dryRun: true,
        },
      });
      expect(response.isError).toBeFalsy();
      expect(confluenceState.getPageCalls).toEqual(["12345"]);
      expect(notionState.createPageCalls).toEqual([]);
      expect(notionState.appendBlocksCalls).toEqual([]);
      const content = response.content as Array<{ type: string; text: string }>;
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed.dryRun).toBe(true);
      expect(parsed.sourcePageId).toBe("12345");
      expect(typeof parsed.blockCount).toBe("number");
      expect(typeof parsed.unresolvedCount).toBe("number");
    } finally {
      await client.close();
      await server.close();
    }
  });
});
