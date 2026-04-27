import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "../../src/mcp/server.js";

async function connect() {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "record-migration-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

async function seedRunDir(rootDir: string, slug: string): Promise<string> {
  const runDir = join(rootDir, slug);
  await mkdir(runDir, { recursive: true });
  await writeFile(join(runDir, "source.json"), "{}", "utf8");
  return runDir;
}

describe("c2n_record_migration tool handler", () => {
  let workspace: string;
  let runsRoot: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-record-"));
    runsRoot = join(workspace, "output", "runs");
    await mkdir(runsRoot, { recursive: true });
  });

  afterEach(async () => {
    await rm(workspace, { recursive: true, force: true });
  });

  it("writes mapping.json under output/runs/<slug>/ and echoes the mapping", async () => {
    const slug = "2026-04-27-alpha";
    await seedRunDir(runsRoot, slug);
    const { client, server } = await connect();
    try {
      const response = await client.callTool({
        name: "c2n_record_migration",
        arguments: {
          confluencePageId: "12345",
          notionPageId: "notion-abc",
          notionUrl: "https://www.notion.so/notion-abc",
          slug,
          rootDir: runsRoot,
        },
      });
      expect(response.isError).toBeFalsy();
      const content = response.content as Array<{ type: string; text: string }>;
      expect(content[0]?.type).toBe("text");
      const echoed = JSON.parse(content[0]?.text ?? "");
      expect(echoed.confluencePageId).toBe("12345");
      expect(echoed.notionPageId).toBe("notion-abc");
      expect(echoed.notionUrl).toBe("https://www.notion.so/notion-abc");
      expect(typeof echoed.recordedAt).toBe("string");
      expect(() => new Date(echoed.recordedAt).toISOString()).not.toThrow();

      const persisted = JSON.parse(await readFile(join(runsRoot, slug, "mapping.json"), "utf8"));
      expect(persisted).toEqual(echoed);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("overwrites an existing mapping.json on a second call", async () => {
    const slug = "2026-04-27-overwrite";
    await seedRunDir(runsRoot, slug);
    const { client, server } = await connect();
    try {
      await client.callTool({
        name: "c2n_record_migration",
        arguments: {
          confluencePageId: "1",
          notionPageId: "notion-1",
          slug,
          rootDir: runsRoot,
        },
      });
      const response = await client.callTool({
        name: "c2n_record_migration",
        arguments: {
          confluencePageId: "1",
          notionPageId: "notion-2",
          slug,
          rootDir: runsRoot,
        },
      });
      expect(response.isError).toBeFalsy();
      const persisted = JSON.parse(await readFile(join(runsRoot, slug, "mapping.json"), "utf8"));
      expect(persisted.notionPageId).toBe("notion-2");
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
          name: "c2n_record_migration",
          arguments: {
            confluencePageId: "1",
            notionPageId: "notion-1",
            slug: "missing-run",
            rootDir: runsRoot,
          },
        }),
      ).rejects.toThrow(/missing-run/);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects empty confluencePageId", async () => {
    const slug = "2026-04-27-empty-conf";
    await seedRunDir(runsRoot, slug);
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_record_migration",
          arguments: {
            confluencePageId: "",
            notionPageId: "notion-1",
            slug,
            rootDir: runsRoot,
          },
        }),
      ).rejects.toThrow();
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects empty notionPageId", async () => {
    const slug = "2026-04-27-empty-notion";
    await seedRunDir(runsRoot, slug);
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_record_migration",
          arguments: {
            confluencePageId: "1",
            notionPageId: "",
            slug,
            rootDir: runsRoot,
          },
        }),
      ).rejects.toThrow();
    } finally {
      await client.close();
      await server.close();
    }
  });
});
