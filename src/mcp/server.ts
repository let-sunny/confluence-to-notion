// MCP server contract for c2n.
//
// Registers the tools/list and resources/list handlers that constitute the
// "parity gate" for issue #133: the listing must match
// tests/fixtures/mcp/{tools-list,resources-list}.json byte-for-byte. The 4
// resources beyond c2n_convert_page are listed as part of the contract but
// their CallToolRequestSchema branches throw "not implemented" and are
// carved out into the follow-up issues described in plan.json.

import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
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
import type { ConfluenceAdapter } from "../confluence/client.js";
import { convertXhtmlToConversionResult } from "../converter/convertPage.js";
import { parseConfluenceUrl } from "../url.js";

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
  /**
   * Builds a Confluence adapter for read-only tool handlers (c2n_fetch_page).
   * Tests inject a fake adapter; the production stdio entry wires this from
   * src/config.ts + src/cli/confluenceEnv.ts. When undefined, c2n_fetch_page
   * throws InvalidRequest naming the missing env vars.
   */
  confluenceFactory?: (overrides?: { baseUrl?: string }) => ConfluenceAdapter;
}

const ConvertPageInputSchema = z.object({
  xhtml: z.string(),
  pageId: z.string().optional(),
  title: z.string().optional(),
});

const FetchPageInputSchema = z.object({
  pageIdOrUrl: z.string().min(1),
  baseUrl: z.string().optional(),
});

// Both run-read handlers accept an optional `rootDir` so tests can target a tmp
// directory. The public tools/list schema only documents `slug` for
// c2n_get_run_report (and `rootDir` on c2n_list_runs); the parity gate is
// unaffected because the handler tolerates the extra field rather than
// advertising it.
const ListRunsInputSchema = z.object({
  rootDir: z.string().optional(),
});

const GetRunReportInputSchema = z.object({
  slug: z.string().min(1),
  rootDir: z.string().optional(),
});

function resolveRunsRoot(rootDir: string | undefined): string {
  return rootDir ?? join(process.cwd(), "output", "runs");
}

function resolvePageId(pageIdOrUrl: string): string {
  if (/^\d+$/.test(pageIdOrUrl)) {
    return pageIdOrUrl;
  }
  const parsed = parseConfluenceUrl(pageIdOrUrl);
  if (parsed.kind === "page" || parsed.kind === "pageId") {
    return parsed.pageId;
  }
  throw new McpError(
    ErrorCode.InvalidParams,
    `c2n_fetch_page requires a page ID or a /spaces/<KEY>/pages/<ID>/... URL; got a ${parsed.kind} link.`,
  );
}

const EMPTY_RULESET: FinalRuleset = { source: "mcp", rules: [] };

const WRITE_TOOLS = new Set(["c2n_migrate_page"]);

export function createServer(options: CreateServerOptions = {}): Server {
  const ruleset = options.ruleset ?? EMPTY_RULESET;
  const allowWrite = options.allowWrite === true;
  const confluenceFactory = options.confluenceFactory;
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
    if (name === "c2n_list_runs") {
      const parsed = ListRunsInputSchema.parse(args ?? {});
      const root = resolveRunsRoot(parsed.rootDir);
      let entries: Array<{ name: string; isDirectory: () => boolean }>;
      try {
        entries = await readdir(root, { withFileTypes: true });
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "ENOENT") {
          return { content: [{ type: "text", text: JSON.stringify([]) }] };
        }
        throw err;
      }
      const slugs = entries
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort();
      return { content: [{ type: "text", text: JSON.stringify(slugs) }] };
    }
    if (name === "c2n_get_run_report") {
      const parsed = GetRunReportInputSchema.parse(args ?? {});
      const root = resolveRunsRoot(parsed.rootDir);
      const reportPath = join(root, parsed.slug, "report.md");
      let body: string;
      try {
        body = await readFile(reportPath, "utf8");
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "ENOENT") {
          throw new McpError(
            ErrorCode.InvalidParams,
            `No report.md found for run slug "${parsed.slug}" under ${root}.`,
          );
        }
        throw err;
      }
      return { content: [{ type: "text", text: body }] };
    }
    if (name === "c2n_fetch_page") {
      if (!confluenceFactory) {
        throw new McpError(
          ErrorCode.InvalidRequest,
          "c2n_fetch_page requires CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN to be set in the server environment.",
        );
      }
      const parsed = FetchPageInputSchema.parse(args ?? {});
      const pageId = resolvePageId(parsed.pageIdOrUrl);
      const adapter = confluenceFactory(parsed.baseUrl ? { baseUrl: parsed.baseUrl } : undefined);
      const page = await adapter.getPage(pageId);
      const payload = {
        pageId: page.id,
        title: page.title,
        spaceKey: page.space.key,
        version: page.version.number,
        body: {
          storage: {
            value: page.body.storage.value,
            representation: page.body.storage.representation,
          },
        },
      };
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(payload),
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
