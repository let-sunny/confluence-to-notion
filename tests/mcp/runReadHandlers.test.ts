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
  const client = new Client({ name: "run-read-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

async function seedRun(rootDir: string, slug: string, reportBody?: string): Promise<void> {
  const runDir = join(rootDir, slug);
  await mkdir(runDir, { recursive: true });
  await writeFile(join(runDir, "source.json"), "{}", "utf8");
  await writeFile(join(runDir, "status.json"), "{}", "utf8");
  if (reportBody !== undefined) {
    await writeFile(join(runDir, "report.md"), reportBody, "utf8");
  }
}

describe("c2n_list_runs and c2n_get_run_report handlers", () => {
  let workspace: string;
  let runsRoot: string;
  let originalCwd: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-runs-"));
    runsRoot = join(workspace, "output", "runs");
    await mkdir(runsRoot, { recursive: true });
    originalCwd = process.cwd();
  });

  afterEach(async () => {
    process.chdir(originalCwd);
    await rm(workspace, { recursive: true, force: true });
  });

  describe("c2n_list_runs", () => {
    it("returns directory names sorted lexicographically when rootDir is provided", async () => {
      await seedRun(runsRoot, "2025-12-01-alpha", "# alpha\n");
      await seedRun(runsRoot, "2025-11-15-beta", "# beta\n");
      const { client, server } = await connect();
      try {
        const response = await client.callTool({
          name: "c2n_list_runs",
          arguments: { rootDir: runsRoot },
        });
        expect(response.isError).toBeFalsy();
        const content = response.content as Array<{ type: string; text: string }>;
        expect(content[0]?.type).toBe("text");
        const parsed = JSON.parse(content[0]?.text ?? "");
        expect(parsed).toEqual(["2025-11-15-beta", "2025-12-01-alpha"]);
      } finally {
        await client.close();
        await server.close();
      }
    });

    it("defaults to ./output/runs relative to process.cwd() when rootDir is omitted", async () => {
      await seedRun(runsRoot, "default-slug", "# default\n");
      process.chdir(workspace);
      const { client, server } = await connect();
      try {
        const response = await client.callTool({
          name: "c2n_list_runs",
          arguments: {},
        });
        const content = response.content as Array<{ type: string; text: string }>;
        const parsed = JSON.parse(content[0]?.text ?? "");
        expect(parsed).toEqual(["default-slug"]);
      } finally {
        await client.close();
        await server.close();
      }
    });

    it("returns [] when the runs directory does not exist", async () => {
      const missing = join(workspace, "does-not-exist");
      const { client, server } = await connect();
      try {
        const response = await client.callTool({
          name: "c2n_list_runs",
          arguments: { rootDir: missing },
        });
        const content = response.content as Array<{ type: string; text: string }>;
        const parsed = JSON.parse(content[0]?.text ?? "");
        expect(parsed).toEqual([]);
      } finally {
        await client.close();
        await server.close();
      }
    });
  });

  describe("c2n_get_run_report", () => {
    it("returns report.md contents for a known slug", async () => {
      const body = "# Run report\n\nAll pages migrated.\n";
      await seedRun(runsRoot, "2025-12-01-alpha", body);
      const { client, server } = await connect();
      try {
        const response = await client.callTool({
          name: "c2n_get_run_report",
          arguments: { slug: "2025-12-01-alpha", rootDir: runsRoot },
        });
        expect(response.isError).toBeFalsy();
        const content = response.content as Array<{ type: string; text: string }>;
        expect(content[0]?.type).toBe("text");
        expect(content[0]?.text).toBe(body);
      } finally {
        await client.close();
        await server.close();
      }
    });

    it("throws InvalidParams naming the slug for an unknown run", async () => {
      const { client, server } = await connect();
      try {
        await expect(
          client.callTool({
            name: "c2n_get_run_report",
            arguments: { slug: "missing-run", rootDir: runsRoot },
          }),
        ).rejects.toThrow(/missing-run/);
      } finally {
        await client.close();
        await server.close();
      }
    });
  });
});
