import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "../../src/mcp/server.js";

async function connect(runsRoot: string) {
  const server = createServer({ runsRoot });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "resource-read-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

interface SeedOptions {
  source?: string;
  report?: string;
  resolution?: string;
  converted?: Record<string, string>;
}

async function seedRun(rootDir: string, slug: string, opts: SeedOptions = {}): Promise<void> {
  const runDir = join(rootDir, slug);
  await mkdir(runDir, { recursive: true });
  if (opts.source !== undefined) {
    await writeFile(join(runDir, "source.json"), opts.source, "utf8");
  }
  if (opts.report !== undefined) {
    await writeFile(join(runDir, "report.md"), opts.report, "utf8");
  }
  if (opts.resolution !== undefined) {
    await writeFile(join(runDir, "resolution.json"), opts.resolution, "utf8");
  }
  if (opts.converted !== undefined) {
    const convertedDir = join(runDir, "converted");
    await mkdir(convertedDir, { recursive: true });
    for (const [pageId, body] of Object.entries(opts.converted)) {
      const safe = pageId.replace(/[^\w.-]+/g, "_");
      await writeFile(join(convertedDir, `${safe}.json`), body, "utf8");
    }
  }
}

describe("ReadResourceRequestSchema handler", () => {
  let workspace: string;
  let runsRoot: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-resources-"));
    runsRoot = join(workspace, "output", "runs");
    await mkdir(runsRoot, { recursive: true });
  });

  afterEach(async () => {
    await rm(workspace, { recursive: true, force: true });
  });

  it("returns source.json contents for c2n://runs/<slug>/source with the templated mimeType", async () => {
    const sourceBody = '{"url":"https://example.atlassian.net/wiki/spaces/DOCS/pages/1"}';
    await seedRun(runsRoot, "alpha", { source: sourceBody });
    const { client, server } = await connect(runsRoot);
    try {
      const response = await client.readResource({ uri: "c2n://runs/alpha/source" });
      expect(response.contents).toHaveLength(1);
      const entry = response.contents[0] as { uri: string; mimeType: string; text: string };
      expect(entry.uri).toBe("c2n://runs/alpha/source");
      expect(entry.mimeType).toBe("application/xhtml+xml");
      expect(entry.text).toBe(sourceBody);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("returns report.md text for c2n://runs/<slug>/report", async () => {
    const reportBody = "# Run report\n\nAll good.\n";
    await seedRun(runsRoot, "alpha", { report: reportBody });
    const { client, server } = await connect(runsRoot);
    try {
      const response = await client.readResource({ uri: "c2n://runs/alpha/report" });
      const entry = response.contents[0] as { uri: string; mimeType: string; text: string };
      expect(entry.mimeType).toBe("application/json");
      expect(entry.text).toBe(reportBody);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("returns the converted page JSON for c2n://runs/<slug>/converted/<pageId>", async () => {
    const convertedBody = '{"blocks":[],"unresolved":[],"usedRules":{}}';
    await seedRun(runsRoot, "alpha", { converted: { "page-42": convertedBody } });
    const { client, server } = await connect(runsRoot);
    try {
      const response = await client.readResource({
        uri: "c2n://runs/alpha/converted/page-42",
      });
      const entry = response.contents[0] as { uri: string; mimeType: string; text: string };
      expect(entry.mimeType).toBe("application/json");
      expect(entry.text).toBe(convertedBody);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("sanitizes pageId on read so it round-trips with writeConvertedPage", async () => {
    const convertedBody = '{"blocks":[],"unresolved":[],"usedRules":{}}';
    // writeConvertedPage stores under sanitized id; the read path must apply
    // the same sanitization to the URL pageId so round-trips work.
    await seedRun(runsRoot, "alpha", { converted: { "page/42": convertedBody } });
    const { client, server } = await connect(runsRoot);
    try {
      const response = await client.readResource({
        uri: "c2n://runs/alpha/converted/page/42",
      });
      const entry = response.contents[0] as { uri: string; mimeType: string; text: string };
      expect(entry.text).toBe(convertedBody);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("returns resolution.json for c2n://runs/<slug>/resolution", async () => {
    const resolutionBody = '{"some-key":"resolved"}';
    await seedRun(runsRoot, "alpha", { resolution: resolutionBody });
    const { client, server } = await connect(runsRoot);
    try {
      const response = await client.readResource({ uri: "c2n://runs/alpha/resolution" });
      const entry = response.contents[0] as { uri: string; mimeType: string; text: string };
      expect(entry.mimeType).toBe("application/json");
      expect(entry.text).toBe(resolutionBody);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects an unknown slug with InvalidParams naming the slug", async () => {
    const { client, server } = await connect(runsRoot);
    try {
      await expect(client.readResource({ uri: "c2n://runs/missing-slug/source" })).rejects.toThrow(
        /missing-slug/,
      );
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects an unsupported URI scheme with InvalidParams", async () => {
    const { client, server } = await connect(runsRoot);
    try {
      await expect(client.readResource({ uri: "https://example.com/foo" })).rejects.toThrow(
        /InvalidParams|unsupported|c2n:\/\//i,
      );
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects an unknown URI shape with InvalidParams", async () => {
    const { client, server } = await connect(runsRoot);
    try {
      await expect(client.readResource({ uri: "c2n://runs/alpha/bogus" })).rejects.toThrow(
        /InvalidParams|unsupported|c2n:\/\//i,
      );
    } finally {
      await client.close();
      await server.close();
    }
  });
});
