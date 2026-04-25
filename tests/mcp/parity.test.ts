import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";
import { createServer } from "../../src/mcp/server.js";
import resourcesListFixture from "../fixtures/mcp/resources-list.json" with { type: "json" };
import toolsListFixture from "../fixtures/mcp/tools-list.json" with { type: "json" };

async function connectClient() {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "parity-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

describe("MCP server parity", () => {
  it("tools/list matches the frozen contract", async () => {
    const { client, server } = await connectClient();
    try {
      const response = await client.listTools();
      expect({ tools: response.tools }).toEqual(toolsListFixture);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("resources/list matches the frozen contract", async () => {
    const { client, server } = await connectClient();
    try {
      const response = await client.listResources();
      expect({ resources: response.resources }).toEqual(resourcesListFixture);
    } finally {
      await client.close();
      await server.close();
    }
  });
});
