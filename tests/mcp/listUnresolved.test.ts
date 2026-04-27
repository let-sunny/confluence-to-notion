import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "../../src/mcp/server.js";

async function connect() {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "list-unresolved-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

async function seedRunDir(rootDir: string, slug: string): Promise<string> {
  const runDir = join(rootDir, slug);
  await mkdir(runDir, { recursive: true });
  return runDir;
}

describe("c2n_list_unresolved tool handler", () => {
  let workspace: string;
  let runsRoot: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-list-unresolved-"));
    runsRoot = join(workspace, "output", "runs");
    await mkdir(runsRoot, { recursive: true });
  });

  afterEach(async () => {
    await rm(workspace, { recursive: true, force: true });
  });

  it("returns parsed resolution.json entries as JSON text content", async () => {
    const slug = "2026-04-27-alpha";
    const runDir = await seedRunDir(runsRoot, slug);
    const entries = {
      "macro:jira:ABC-123": "https://example.notion.so/abc",
      "macro:slack:#chan": "https://example.notion.so/chan",
    };
    await writeFile(
      join(runDir, "resolution.json"),
      `${JSON.stringify(entries, null, 2)}\n`,
      "utf8",
    );
    const { client, server } = await connect();
    try {
      const response = await client.callTool({
        name: "c2n_list_unresolved",
        arguments: { slug, rootDir: runsRoot },
      });
      expect(response.isError).toBeFalsy();
      const content = response.content as Array<{ type: string; text: string }>;
      expect(content[0]?.type).toBe("text");
      const parsed = JSON.parse(content[0]?.text ?? "");
      expect(parsed).toEqual(entries);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("throws InvalidParams naming the slug when the run directory does not exist", async () => {
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_list_unresolved",
          arguments: { slug: "missing-run", rootDir: runsRoot },
        }),
      ).rejects.toThrow(/missing-run/);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("throws InvalidParams naming the slug when resolution.json is missing", async () => {
    const slug = "2026-04-27-no-resolution";
    await seedRunDir(runsRoot, slug);
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_list_unresolved",
          arguments: { slug, rootDir: runsRoot },
        }),
      ).rejects.toThrow(new RegExp(slug));
    } finally {
      await client.close();
      await server.close();
    }
  });
});
