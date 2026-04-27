import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ProposerOutputSchema } from "../../src/agentOutput/schemas.js";
import { createServer } from "../../src/mcp/server.js";

async function connect() {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "propose-resolution-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

function sampleProposal(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    rule_id: "rule:jira-link",
    source_pattern_id: "pattern:jira-macro",
    source_description: "Confluence Jira inline link macro",
    notion_block_type: "bookmark",
    mapping_description: "Map ac:link macros pointing at Jira to Notion bookmark blocks.",
    example_input:
      '<ac:link><ri:url ri:value="https://example.atlassian.net/browse/ABC-1"/></ac:link>',
    example_output: { type: "bookmark", url: "https://example.atlassian.net/browse/ABC-1" },
    confidence: "high",
    ...overrides,
  };
}

describe("c2n_propose_resolution tool handler", () => {
  let workspace: string;
  let proposalsPath: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-propose-"));
    proposalsPath = join(workspace, "proposals.json");
  });

  afterEach(async () => {
    await rm(workspace, { recursive: true, force: true });
  });

  it("appends a proposal to an existing proposals.json", async () => {
    const seed = {
      source_patterns_file: "output/patterns.json",
      rules: [sampleProposal({ rule_id: "rule:existing" })],
    };
    await writeFile(proposalsPath, `${JSON.stringify(seed, null, 2)}\n`, "utf8");
    const { client, server } = await connect();
    try {
      const proposal = sampleProposal();
      const response = await client.callTool({
        name: "c2n_propose_resolution",
        arguments: { ...proposal, proposalsPath },
      });
      expect(response.isError).toBeFalsy();
      const content = response.content as Array<{ type: string; text: string }>;
      const echoed = JSON.parse(content[0]?.text ?? "");
      expect(echoed).toEqual({ ruleCount: 2, ruleId: "rule:jira-link" });

      const onDisk = await readFile(proposalsPath, "utf8");
      expect(onDisk.endsWith("\n")).toBe(true);
      const parsed = ProposerOutputSchema.parse(JSON.parse(onDisk));
      expect(parsed.rules.map((r) => r.rule_id)).toEqual(["rule:existing", "rule:jira-link"]);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("creates proposals.json with default scaffold when file is missing", async () => {
    const { client, server } = await connect();
    try {
      const proposal = sampleProposal();
      const response = await client.callTool({
        name: "c2n_propose_resolution",
        arguments: { ...proposal, proposalsPath },
      });
      expect(response.isError).toBeFalsy();
      const echoed = JSON.parse((response.content as Array<{ text: string }>)[0]?.text ?? "");
      expect(echoed).toEqual({ ruleCount: 1, ruleId: "rule:jira-link" });

      const onDisk = await readFile(proposalsPath, "utf8");
      const parsed = ProposerOutputSchema.parse(JSON.parse(onDisk));
      expect(parsed.source_patterns_file).toBe("output/patterns.json");
      expect(parsed.rules).toHaveLength(1);
      expect(parsed.rules[0]?.rule_id).toBe("rule:jira-link");
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects an invalid proposal payload (zod error → InvalidParams)", async () => {
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_propose_resolution",
          arguments: { rule_id: "rule:bad", proposalsPath },
        }),
      ).rejects.toThrow();
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("rejects a duplicate rule_id (idempotency surface)", async () => {
    const seed = {
      source_patterns_file: "output/patterns.json",
      rules: [sampleProposal()],
    };
    await writeFile(proposalsPath, `${JSON.stringify(seed, null, 2)}\n`, "utf8");
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_propose_resolution",
          arguments: { ...sampleProposal(), proposalsPath },
        }),
      ).rejects.toThrow(/rule:jira-link/);
    } finally {
      await client.close();
      await server.close();
    }
  });
});
