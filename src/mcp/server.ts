// MCP server contract for c2n.
//
// Registers the tools/list and resources/list handlers that constitute the
// "parity gate" for issue #133: the listing must match
// tests/fixtures/mcp/{tools-list,resources-list}.json byte-for-byte. The 4
// resources beyond c2n_convert_page are listed as part of the contract but
// their CallToolRequestSchema branches throw "not implemented" and are
// carved out into the follow-up issues described in plan.json.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListResourceTemplatesRequestSchema,
  ListToolsRequestSchema,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import type { FinalRuleset } from "../agentOutput/finalRuleset.js";
import { convertXhtmlToConversionResult } from "../converter/convertPage.js";

interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

interface ResourceTemplateDefinition {
  uriTemplate: string;
  name: string;
  description: string;
  mimeType: string;
}

const JSON_SCHEMA_DRAFT = "http://json-schema.org/draft-07/schema#";

const TOOLS: ToolDefinition[] = [
  {
    name: "c2n_fetch_page",
    description:
      "Fetch a Confluence page by ID or URL and return its raw XHTML body plus metadata. Read-only.",
    inputSchema: {
      type: "object",
      properties: {
        pageIdOrUrl: {
          type: "string",
          description: "Confluence page ID or full page URL.",
        },
        baseUrl: {
          type: "string",
          description: "Optional Confluence base URL override; falls back to CONFLUENCE_BASE_URL.",
        },
      },
      required: ["pageIdOrUrl"],
      additionalProperties: false,
      $schema: JSON_SCHEMA_DRAFT,
    },
  },
  {
    name: "c2n_convert_page",
    description:
      "Convert a Confluence XHTML body into Notion blocks using the deterministic converter and the current ruleset. Read-only.",
    inputSchema: {
      type: "object",
      properties: {
        xhtml: {
          type: "string",
          description: "Confluence storage-format XHTML for a single page.",
        },
        pageId: {
          type: "string",
          description: "Optional source page ID; threaded into unresolved entries.",
        },
        title: {
          type: "string",
          description: "Optional source page title for diagnostic logging.",
        },
      },
      required: ["xhtml"],
      additionalProperties: false,
      $schema: JSON_SCHEMA_DRAFT,
    },
  },
  {
    name: "c2n_list_runs",
    description: "List migration runs recorded under output/runs/. Read-only.",
    inputSchema: {
      type: "object",
      properties: {
        rootDir: {
          type: "string",
          description: "Optional alternate runs root; defaults to ./output/runs.",
        },
      },
      additionalProperties: false,
      $schema: JSON_SCHEMA_DRAFT,
    },
  },
  {
    name: "c2n_get_run_report",
    description: "Read the report.json for a migration run by its slug. Read-only.",
    inputSchema: {
      type: "object",
      properties: {
        slug: {
          type: "string",
          description: "Run slug (directory name under output/runs/).",
        },
      },
      required: ["slug"],
      additionalProperties: false,
      $schema: JSON_SCHEMA_DRAFT,
    },
  },
  {
    name: "c2n_migrate_page",
    description:
      "Migrate a single Confluence page to Notion (write). Disabled unless the server is started with allowWrite: true.",
    inputSchema: {
      type: "object",
      properties: {
        pageIdOrUrl: {
          type: "string",
          description: "Confluence page ID or URL to migrate.",
        },
        parentNotionPageId: {
          type: "string",
          description: "Notion parent page ID under which the new page is created.",
        },
        dryRun: {
          type: "boolean",
          description:
            "If true, perform conversion only and report intended writes without calling the Notion API.",
        },
      },
      required: ["pageIdOrUrl", "parentNotionPageId"],
      additionalProperties: false,
      $schema: JSON_SCHEMA_DRAFT,
    },
  },
];

const RESOURCE_TEMPLATES: ResourceTemplateDefinition[] = [
  {
    uriTemplate: "c2n://runs/{slug}/source",
    name: "Run source XHTML",
    description: "Raw Confluence XHTML captured for the run. {slug} is the run identifier.",
    mimeType: "application/xhtml+xml",
  },
  {
    uriTemplate: "c2n://runs/{slug}/report",
    name: "Run report",
    description: "Run report JSON summarising success/failure per page.",
    mimeType: "application/json",
  },
  {
    uriTemplate: "c2n://runs/{slug}/converted/{pageId}",
    name: "Converted Notion blocks",
    description: "Notion blocks emitted by the converter for a single page in the run.",
    mimeType: "application/json",
  },
  {
    uriTemplate: "c2n://runs/{slug}/resolution",
    name: "Resolution store",
    description: "Aggregated unresolved-item resolutions for the run.",
    mimeType: "application/json",
  },
];

export interface CreateServerOptions {
  /**
   * Allow tool handlers that perform writes (c2n_migrate_page). Defaults to
   * false; even when false the tool is still listed so clients can discover
   * the contract.
   */
  allowWrite?: boolean;
  /**
   * Ruleset threaded into convertXhtmlToConversionResult. Defaults to an
   * empty ruleset so unresolved items surface with placeholder URLs — the
   * same fallback the CLI uses when no finalized ruleset is available.
   */
  ruleset?: FinalRuleset;
}

const ConvertPageInputSchema = z.object({
  xhtml: z.string(),
  pageId: z.string().optional(),
  title: z.string().optional(),
});

const EMPTY_RULESET: FinalRuleset = { source: "mcp", rules: [] };

const WRITE_TOOLS = new Set(["c2n_migrate_page"]);

export function createServer(options: CreateServerOptions = {}): Server {
  const ruleset = options.ruleset ?? EMPTY_RULESET;
  const allowWrite = options.allowWrite === true;
  const server = new Server(
    { name: "c2n-mcp", version: "0.1.0" },
    {
      capabilities: {
        tools: {},
        resources: {},
      },
    },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));
  server.setRequestHandler(ListResourceTemplatesRequestSchema, async () => ({
    resourceTemplates: RESOURCE_TEMPLATES,
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    if (WRITE_TOOLS.has(name) && !allowWrite) {
      throw new McpError(
        ErrorCode.InvalidRequest,
        `Tool ${name} requires the server to be started with allowWrite: true.`,
      );
    }
    if (name === "c2n_convert_page") {
      const parsed = ConvertPageInputSchema.parse(args ?? {});
      const result = convertXhtmlToConversionResult(ruleset, parsed.xhtml, parsed.pageId ?? "");
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    }
    throw new McpError(ErrorCode.MethodNotFound, `Tool not implemented: ${name}`);
  });

  return server;
}

export { TOOLS as toolDefinitions, RESOURCE_TEMPLATES as resourceTemplateDefinitions };
export { McpError, ErrorCode };
