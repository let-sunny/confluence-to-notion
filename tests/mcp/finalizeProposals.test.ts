import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FinalRulesetSchema } from "../../src/agentOutput/finalRuleset.js";
import { createServer } from "../../src/mcp/server.js";

async function connect() {
  const server = createServer();
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "finalize-proposals-test-client", version: "0.0.0" });
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

function sampleProposalsPayload(): Record<string, unknown> {
  return {
    source_patterns_file: "output/patterns.json",
    rules: [
      {
        rule_id: "rule:jira",
        source_pattern_id: "pattern:jira",
        source_description: "Confluence Jira inline link",
        notion_block_type: "bookmark",
        mapping_description: "Map Jira links to bookmark blocks.",
        example_input: "<ac:link/>",
        example_output: { type: "bookmark" },
        confidence: "high",
      },
    ],
  };
}

describe("c2n_finalize_proposals tool handler", () => {
  let workspace: string;
  let proposalsPath: string;
  let rulesPath: string;

  beforeEach(async () => {
    workspace = await mkdtemp(join(tmpdir(), "c2n-mcp-finalize-"));
    proposalsPath = join(workspace, "proposals.json");
    rulesPath = join(workspace, "rules.json");
  });

  afterEach(async () => {
    await rm(workspace, { recursive: true, force: true });
  });

  it("writes rules.json from proposals.json and returns ruleCount + rulesPath", async () => {
    await writeFile(
      proposalsPath,
      `${JSON.stringify(sampleProposalsPayload(), null, 2)}\n`,
      "utf8",
    );
    const { client, server } = await connect();
    try {
      const response = await client.callTool({
        name: "c2n_finalize_proposals",
        arguments: { proposalsPath, rulesOutPath: rulesPath },
      });
      expect(response.isError).toBeFalsy();
      const echoed = JSON.parse((response.content as Array<{ text: string }>)[0]?.text ?? "");
      expect(echoed).toEqual({ ruleCount: 1, rulesPath });

      const onDisk = await readFile(rulesPath, "utf8");
      const parsed = FinalRulesetSchema.parse(JSON.parse(onDisk));
      expect(parsed.source).toBe("output/patterns.json");
      expect(parsed.rules).toHaveLength(1);
      expect(parsed.rules[0]?.rule_id).toBe("rule:jira");
      expect(parsed.rules[0]?.enabled).toBe(true);
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("surfaces a missing proposals file as InvalidParams", async () => {
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_finalize_proposals",
          arguments: { proposalsPath, rulesOutPath: rulesPath },
        }),
      ).rejects.toThrow();
    } finally {
      await client.close();
      await server.close();
    }
  });

  it("surfaces invalid JSON as InvalidParams", async () => {
    await writeFile(proposalsPath, "{ not json", "utf8");
    const { client, server } = await connect();
    try {
      await expect(
        client.callTool({
          name: "c2n_finalize_proposals",
          arguments: { proposalsPath, rulesOutPath: rulesPath },
        }),
      ).rejects.toThrow();
    } finally {
      await client.close();
      await server.close();
    }
  });
});
