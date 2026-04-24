// Thin adapter over the Confluence Cloud REST v1 API. All JSON responses are
// validated through the zod schemas in ./schemas.ts at the adapter boundary so
// the rest of the codebase can consume typed, shape-checked data. undici's
// Agent (keepalive pool) is wired into the default fetch implementation to keep
// `migrate-tree-pages` runs efficient across hundreds of sequential requests;
// tests inject a plain `fetch` so no real socket is ever opened.

import { Agent, setGlobalDispatcher, fetch as undiciFetch } from "undici";
import { type ConfluencePage, ConfluencePageSchema, type PageTreeNode } from "./schemas.js";

export type FetchLike = (
  input: string | URL,
  init?: { method?: string; headers?: Record<string, string> },
) => Promise<{
  ok: boolean;
  status: number;
  statusText: string;
  url: string;
  json: () => Promise<unknown>;
  arrayBuffer: () => Promise<ArrayBuffer>;
}>;

export interface CreateConfluenceClientOptions {
  email: string;
  token: string;
  baseUrl: string;
  fetchImpl?: FetchLike;
}

export interface ListSpacePagesOptions {
  limit: number;
  cursor?: number;
}

export interface ListSpacePagesResult {
  results: ConfluencePage[];
  start: number;
  limit: number;
  size: number;
}

export interface GetPageTreeOptions {
  maxDepth: number;
}

export interface ConfluenceAdapter {
  getPage: (pageId: string) => Promise<ConfluencePage>;
  getPageTree: (rootPageId: string, options: GetPageTreeOptions) => Promise<PageTreeNode>;
  listSpacePages: (
    spaceKey: string,
    options: ListSpacePagesOptions,
  ) => Promise<ListSpacePagesResult>;
  getAttachment: (pageId: string, filename: string) => Promise<Uint8Array>;
}

let keepaliveDispatcherInstalled = false;

// Assumes the CLI process owns undici's global dispatcher. If a second consumer
// (e.g. the MCP server) lands in the same process, switch to a per-client Agent
// via `undici.request` rather than `setGlobalDispatcher` to avoid shadowing it.
function ensureKeepaliveDispatcher(): void {
  if (keepaliveDispatcherInstalled) return;
  setGlobalDispatcher(new Agent({ keepAliveTimeout: 30_000, keepAliveMaxTimeout: 60_000 }));
  keepaliveDispatcherInstalled = true;
}

function basicAuthHeader(email: string, token: string): string {
  return `Basic ${Buffer.from(`${email}:${token}`).toString("base64")}`;
}

function trimTrailingSlash(url: string): string {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

const PAGE_EXPAND = "body.storage,version,space";

export function createConfluenceClient(options: CreateConfluenceClientOptions): ConfluenceAdapter {
  const { email, token, fetchImpl } = options;
  const baseUrl = trimTrailingSlash(options.baseUrl);
  const authHeader = basicAuthHeader(email, token);

  let resolvedFetch: FetchLike;
  if (fetchImpl) {
    resolvedFetch = fetchImpl;
  } else {
    ensureKeepaliveDispatcher();
    resolvedFetch = undiciFetch as unknown as FetchLike;
  }

  async function request(path: string, query?: Record<string, string>): Promise<unknown> {
    const url = new URL(`${baseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        url.searchParams.set(k, v);
      }
    }
    const response = await resolvedFetch(url, {
      method: "GET",
      headers: {
        authorization: authHeader,
        accept: "application/json",
      },
    });
    if (!response.ok) {
      throw new Error(
        `Confluence request failed: ${response.status} ${response.statusText} (${url.toString()})`,
      );
    }
    return response.json();
  }

  async function getPage(pageId: string): Promise<ConfluencePage> {
    const data = await request(`/rest/api/content/${encodeURIComponent(pageId)}`, {
      expand: PAGE_EXPAND,
    });
    return ConfluencePageSchema.parse(data);
  }

  async function listChildPageIds(pageId: string): Promise<Array<{ id: string; title: string }>> {
    const data = (await request(`/rest/api/content/${encodeURIComponent(pageId)}/child/page`)) as {
      results?: Array<{ id: unknown; title: unknown }>;
    };
    const results = data.results ?? [];
    return results.map((r) => ({
      id: String(r.id),
      title: typeof r.title === "string" ? r.title : "",
    }));
  }

  async function walkTree(
    id: string,
    title: string,
    depthRemaining: number,
  ): Promise<PageTreeNode> {
    if (depthRemaining <= 0) {
      return { id, title, children: [] };
    }
    const children = await listChildPageIds(id);
    const nested = await Promise.all(
      children.map((child) => walkTree(child.id, child.title, depthRemaining - 1)),
    );
    return { id, title, children: nested };
  }

  async function getPageTree(rootPageId: string, tree: GetPageTreeOptions): Promise<PageTreeNode> {
    const root = await getPage(rootPageId);
    return walkTree(root.id, root.title, tree.maxDepth);
  }

  async function listSpacePages(
    spaceKey: string,
    { limit, cursor = 0 }: ListSpacePagesOptions,
  ): Promise<ListSpacePagesResult> {
    const data = (await request("/rest/api/content", {
      spaceKey,
      start: String(cursor),
      limit: String(limit),
      expand: PAGE_EXPAND,
    })) as {
      results?: unknown[];
      start?: number;
      limit?: number;
      size?: number;
    };
    const results = (data.results ?? []).map((r) => ConfluencePageSchema.parse(r));
    return {
      results,
      start: typeof data.start === "number" ? data.start : cursor,
      limit: typeof data.limit === "number" ? data.limit : limit,
      size: typeof data.size === "number" ? data.size : results.length,
    };
  }

  async function getAttachment(pageId: string, filename: string): Promise<Uint8Array> {
    const url = new URL(
      `${baseUrl}/download/attachments/${encodeURIComponent(pageId)}/${encodeURIComponent(filename)}`,
    );
    const response = await resolvedFetch(url, {
      method: "GET",
      headers: { authorization: authHeader },
    });
    if (!response.ok) {
      throw new Error(
        `Confluence attachment request failed: ${response.status} ${response.statusText} (${url.toString()})`,
      );
    }
    const buffer = await response.arrayBuffer();
    return new Uint8Array(buffer);
  }

  return { getPage, getPageTree, listSpacePages, getAttachment };
}
