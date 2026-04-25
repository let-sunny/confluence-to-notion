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

interface FactoryCall {
  overrides: { baseUrl?: string } | undefined;
}

interface FakeAdapterState {
  factoryCalls: FactoryCall[];
  getPageCalls: string[];
}

function buildPage(overrides: Partial<ConfluencePage> = {}): ConfluencePage {
  return {
    id: "12345",
    title: "Sample page",
    type: "page",
    space: { key: "DOCS", name: "Docs" },
    body: { storage: { value: "<p>Hello</p>", representation: "storage" } },
    version: { number: 7 },
    ...overrides,
  } as ConfluencePage;
}

function fakeAdapter(state: FakeAdapterState, page: ConfluencePage): ConfluenceAdapter {
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

interface ConnectOptions {
  page?: ConfluencePage;
  withFactory?: boolean;
}

async function connect(opts: ConnectOptions = {}) {
  const state: FakeAdapterState = { factoryCalls: [], getPageCalls: [] };
  const page = opts.page ?? buildPage();
  const server = createServer(
    opts.withFactory === false
      ? {}
      : {
          confluenceFactory: (overrides) => {
            state.factoryCalls.push({ overrides });
            return fakeAdapter(state, page);
          },
        },
  );
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "fetch-page-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server, state };
}

describe("c2n_fetch_page tool handler", () => {
  it("calls adapter.getPage with a raw page ID and serialises the response", async () => {
    const page = buildPage({
      id: "9001",
      title: "Direct ID page",
      space: { key: "TEAM", name: "Team space" },
      version: { number: 3 },
      body: { storage: { value: "<p>direct</p>", representation: "storage" } },
    });
    const { client, server, state } = await connect({ page });
    try {
      const response = await client.callTool({
        name: "c2n_fetch_page",
        arguments: { pageIdOrUrl: "9001" },
      });
      expect(response.isError).toBeFalsy();
      expect(state.getPageCalls).toEqual(["9001"]);
      const content = response.content as Array<{ type: string; text: string }>;
      expect(content[0]?.type).toBe("text");
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed).toEqual({
        pageId: "9001",
        title: "Direct ID page",
        spaceKey: "TEAM",
        version: 3,
        body: { storage: { value: "<p>direct</p>", representation: "storage" } },
      });
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("resolves a Confluence URL through src/url.ts before calling adapter.getPage", async () => {
    const page = buildPage({ id: "555", title: "URL page" });
    const { client, server, state } = await connect({ page });
    try {
      const url = "https://example.atlassian.net/wiki/spaces/DOCS/pages/555/Some+Title";
      const response = await client.callTool({
        name: "c2n_fetch_page",
        arguments: { pageIdOrUrl: url },
      });
      expect(response.isError).toBeFalsy();
      expect(state.getPageCalls).toEqual(["555"]);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("throws InvalidRequest when no Confluence factory is wired", async () => {
    const { client, server } = await connect({ withFactory: false });
    try {
      await expect(
        client.callTool({
          name: "c2n_fetch_page",
          arguments: { pageIdOrUrl: "1" },
        }),
      ).rejects.toThrow(
        /CONFLUENCE_BASE_URL.*CONFLUENCE_EMAIL.*CONFLUENCE_API_TOKEN|CONFLUENCE_EMAIL.*CONFLUENCE_API_TOKEN/,
      );
    } finally {
      await client.close();
      await server.close();
    }
  });
});
