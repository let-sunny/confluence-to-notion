import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";
import type { FinalRuleset } from "../../src/agentOutput/finalRuleset.js";
import { convertXhtmlToConversionResult } from "../../src/converter/convertPage.js";
import { createServer } from "../../src/mcp/server.js";

const EMPTY_RULESET: FinalRuleset = { source: "mcp-test", rules: [] };

async function connectClient(options: { allowWrite?: boolean } = {}) {
  const server = createServer(options);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "convert-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

describe("c2n_convert_page tool handler", () => {
  it("returns the same conversion result as convertXhtmlToConversionResult", async () => {
    const xhtml = "<p>Hello <b>world</b></p>";
    const expected = convertXhtmlToConversionResult({ source: "test", rules: [] }, xhtml, "");

    const { client, server } = await connectClient();
    try {
      const response = await client.callTool({
        name: "c2n_convert_page",
        arguments: { xhtml },
      });
      expect(response.isError).toBeFalsy();
      const content = response.content as Array<{ type: string; text: string }>;
      expect(content).toHaveLength(1);
      expect(content[0]?.type).toBe("text");
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed).toEqual(JSON.parse(JSON.stringify(expected)));
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("threads pageId into unresolved entries", async () => {
    const xhtml = '<p><ac:link><ri:page ri:content-title="Other Page"/></ac:link></p>';
    const expected = convertXhtmlToConversionResult(EMPTY_RULESET, xhtml, "page-123");

    const { client, server } = await connectClient();
    try {
      const response = await client.callTool({
        name: "c2n_convert_page",
        arguments: { xhtml, pageId: "page-123" },
      });
      const content = response.content as Array<{ type: string; text: string }>;
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed.unresolved).toEqual(JSON.parse(JSON.stringify(expected.unresolved)));
      expect(parsed.unresolved[0]?.sourcePageId).toBe("page-123");
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects an unimplemented tool with an MCP error", async () => {
    const { client, server } = await connectClient();
    try {
      await expect(
        client.callTool({ name: "c2n_fetch_page", arguments: { pageIdOrUrl: "1" } }),
      ).rejects.toThrow(/not implemented/i);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects write tools when allowWrite is not enabled", async () => {
    const { client, server } = await connectClient();
    try {
      await expect(
        client.callTool({
          name: "c2n_migrate_page",
          arguments: { pageIdOrUrl: "1", parentNotionPageId: "abc" },
        }),
      ).rejects.toThrow(/allowWrite/);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("falls through to not-implemented for write tools when allowWrite is enabled", async () => {
    const { client, server } = await connectClient({ allowWrite: true });
    try {
      await expect(
        client.callTool({
          name: "c2n_migrate_page",
          arguments: { pageIdOrUrl: "1", parentNotionPageId: "abc" },
        }),
      ).rejects.toThrow(/not implemented/i);
    } finally {
      await client.close();
      await server.close();
    }
  });
});
