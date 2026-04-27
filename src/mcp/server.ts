// MCP server contract for c2n.
//
// Registers the tools/list and resources/templates/list handlers that
// constitute the "parity gate" for issue #133: the listings must match
// tests/fixtures/mcp/{tools-list,resource-templates-list}.json byte-for-byte.
// Read-only tool handlers (c2n_fetch_page, c2n_convert_page, c2n_list_runs,
// c2n_get_run_report) plus the c2n_record_migration ingest handler and the
// ReadResourceRequestSchema handler for the four c2n://runs/{slug}/...
// templates are implemented in this file. Per ADR-007, the MCP surface is
// read-mostly: page creation runs through the host's Notion MCP, and hosts
// post the resulting Notion page ID back via c2n_record_migration.

import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  CallToolRequestSchema,
  ErrorCode,
  ListResourceTemplatesRequestSchema,
  ListToolsRequestSchema,
  McpError,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import type { FinalRuleset } from "../agentOutput/finalRuleset.js";
import type { ConfluenceAdapter } from "../confluence/client.js";
import { convertXhtmlToConversionResult } from "../converter/convertPage.js";
import { MappingSchema } from "../runs/index.js";
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
    name: "c2n_record_migration",
    description:
      "Record a Notion page ID created by the host runtime against a Confluence page in this c2n run; persists to output/runs/<slug>/mapping.json. Write.",
    inputSchema: {
      type: "object",
      properties: {
        confluencePageId: {
          type: "string",
          description: "Source Confluence page ID being recorded.",
        },
        notionPageId: {
          type: "string",
          description: "Notion page ID created by the host runtime.",
        },
        slug: {
          type: "string",
          description: "Run slug (directory name under output/runs/) the mapping belongs to.",
        },
        notionUrl: {
          type: "string",
          description: "Optional Notion page URL for downstream reporting.",
        },
        rootDir: {
          type: "string",
          description: "Optional alternate runs root; defaults to ./output/runs.",
        },
      },
      required: ["confluencePageId", "notionPageId", "slug"],
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
   * Ruleset threaded into convertXhtmlToConversionResult. Defaults to an
   * empty ruleset so unresolved items surface with placeholder URLs — the
   * same fallback the CLI uses when no finalized ruleset is available.
   */
  ruleset?: FinalRuleset;
  /**
   * Builds a Confluence adapter for read-only tool handlers (c2n_fetch_page).
   * Tests inject a fake adapter; the production stdio entry wires this through
   * getConfluenceCreds() (a `c2n init` profile or the matching env vars).
   * When undefined, c2n_fetch_page throws InvalidRequest naming the missing
   * env vars and pointing at `c2n init`.
   */
  confluenceFactory?: (overrides?: { baseUrl?: string }) => ConfluenceAdapter;
  /**
   * Root directory under which run artifacts (source.json, report.md,
   * resolution.json, converted/<pageId>.json, mapping.json) live. Defaults
   * to `<cwd>/output/runs`. Used by the c2n_list_runs, c2n_get_run_report,
   * c2n_record_migration handlers and the ReadResourceRequestSchema handler.
   */
  runsRoot?: string;
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

const RecordMigrationInputSchema = z.object({
  confluencePageId: z.string().min(1),
  notionPageId: z.string().min(1),
  slug: z.string().min(1),
  notionUrl: z.string().optional(),
  rootDir: z.string().optional(),
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

function resolveRunsRoot(rootDir: string | undefined, fallback: string | undefined): string {
  return rootDir ?? fallback ?? join(process.cwd(), "output", "runs");
}

const URL_PAGE_ID_SANITIZE_RE = /[^\w.-]+/g;
const C2N_URI_PREFIX = "c2n://runs/";

function sanitizePageId(pageId: string): string {
  return pageId.replace(URL_PAGE_ID_SANITIZE_RE, "_");
}

interface ParsedResourceUri {
  template: "source" | "report" | "resolution" | "converted";
  slug: string;
  pageId?: string;
}

function parseResourceUri(uri: string): ParsedResourceUri | null {
  if (!uri.startsWith(C2N_URI_PREFIX)) {
    return null;
  }
  const tail = uri.slice(C2N_URI_PREFIX.length);
  const segments = tail.split("/").filter((s) => s.length > 0);
  if (segments.length < 2) {
    return null;
  }
  const slug = segments[0];
  if (!slug) {
    return null;
  }
  const second = segments[1];
  if (segments.length === 2) {
    if (second === "source" || second === "report" || second === "resolution") {
      return { template: second, slug };
    }
    return null;
  }
  if (second === "converted" && segments.length >= 3) {
    const pageId = segments.slice(2).join("/");
    return { template: "converted", slug, pageId };
  }
  return null;
}

function templateMimeType(template: ParsedResourceUri["template"]): string {
  for (const entry of RESOURCE_TEMPLATES) {
    const placeholder =
      template === "source"
        ? "/source"
        : template === "report"
          ? "/report"
          : template === "resolution"
            ? "/resolution"
            : "/converted/{pageId}";
    if (entry.uriTemplate.endsWith(placeholder)) {
      return entry.mimeType;
    }
  }
  // Fallback — should be unreachable while RESOURCE_TEMPLATES stays in sync
  // with the parser.
  return "application/octet-stream";
}

function resolvePageId(toolName: string, pageIdOrUrl: string): string {
  if (/^\d+$/.test(pageIdOrUrl)) {
    return pageIdOrUrl;
  }
  const parsed = parseConfluenceUrl(pageIdOrUrl);
  if (parsed.kind === "page" || parsed.kind === "pageId") {
    return parsed.pageId;
  }
  throw new McpError(
    ErrorCode.InvalidParams,
    `${toolName} requires a page ID or a /spaces/<KEY>/pages/<ID>/... URL; got a ${parsed.kind} link.`,
  );
}

const EMPTY_RULESET: FinalRuleset = { source: "mcp", rules: [] };

export function createServer(options: CreateServerOptions = {}): Server {
  const ruleset = options.ruleset ?? EMPTY_RULESET;
  const confluenceFactory = options.confluenceFactory;
  const runsRootOption = options.runsRoot;
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

  server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
    const { uri } = request.params;
    const parsed = parseResourceUri(uri);
    if (parsed === null) {
      throw new McpError(
        ErrorCode.InvalidParams,
        `Unsupported resource URI: ${uri}. Supported templates: ${RESOURCE_TEMPLATES.map((t) => t.uriTemplate).join(", ")}.`,
      );
    }
    const root = resolveRunsRoot(undefined, runsRootOption);
    const runDir = join(root, parsed.slug);
    let filePath: string;
    let artifactLabel: string;
    switch (parsed.template) {
      case "source":
        filePath = join(runDir, "source.json");
        artifactLabel = "source.json";
        break;
      case "report":
        filePath = join(runDir, "report.md");
        artifactLabel = "report.md";
        break;
      case "resolution":
        filePath = join(runDir, "resolution.json");
        artifactLabel = "resolution.json";
        break;
      case "converted": {
        const pageId = parsed.pageId ?? "";
        const safe = sanitizePageId(pageId);
        filePath = join(runDir, "converted", `${safe}.json`);
        artifactLabel = `converted/${safe}.json`;
        break;
      }
    }
    let text: string;
    try {
      text = await readFile(filePath, "utf8");
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        throw new McpError(
          ErrorCode.InvalidParams,
          `No ${artifactLabel} found for run slug "${parsed.slug}" under ${root}.`,
        );
      }
      throw err;
    }
    return {
      contents: [
        {
          uri,
          mimeType: templateMimeType(parsed.template),
          text,
        },
      ],
    };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
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
      const root = resolveRunsRoot(parsed.rootDir, runsRootOption);
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
      const root = resolveRunsRoot(parsed.rootDir, runsRootOption);
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
          "c2n_fetch_page requires Confluence credentials. Run `c2n init` to store a profile, or set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN in the server environment.",
        );
      }
      const parsed = FetchPageInputSchema.parse(args ?? {});
      const pageId = resolvePageId("c2n_fetch_page", parsed.pageIdOrUrl);
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
    if (name === "c2n_record_migration") {
      const parsed = RecordMigrationInputSchema.parse(args ?? {});
      const root = resolveRunsRoot(parsed.rootDir, runsRootOption);
      const runDir = join(root, parsed.slug);
      try {
        const info = await stat(runDir);
        if (!info.isDirectory()) {
          throw new McpError(
            ErrorCode.InvalidParams,
            `Run slug "${parsed.slug}" is not a directory under ${root}.`,
          );
        }
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "ENOENT") {
          throw new McpError(
            ErrorCode.InvalidParams,
            `No run directory found for slug "${parsed.slug}" under ${root}.`,
          );
        }
        throw err;
      }
      const mapping = MappingSchema.parse({
        confluencePageId: parsed.confluencePageId,
        notionPageId: parsed.notionPageId,
        ...(parsed.notionUrl !== undefined ? { notionUrl: parsed.notionUrl } : {}),
      });
      await mkdir(runDir, { recursive: true });
      const payload = {
        confluencePageId: mapping.confluencePageId,
        notionPageId: mapping.notionPageId,
        ...(mapping.notionUrl !== undefined ? { notionUrl: mapping.notionUrl } : {}),
        recordedAt: mapping.recordedAt.toISOString(),
      };
      await writeFile(
        join(runDir, "mapping.json"),
        `${JSON.stringify(payload, null, 2)}\n`,
        "utf8",
      );
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
