import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { createConfluenceClient } from "../../src/confluence/client.js";

const BASE_URL = "https://example.atlassian.net/wiki";
const EMAIL = "user@example.com";
const TOKEN = "secret-token";
const EXPECTED_AUTH_HEADER = `Basic ${Buffer.from(`${EMAIL}:${TOKEN}`).toString("base64")}`;

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

function makeClient() {
  return createConfluenceClient({
    email: EMAIL,
    token: TOKEN,
    baseUrl: BASE_URL,
    fetchImpl: fetch,
  });
}

const validPage = (id: string, title = "Home") => ({
  id,
  title,
  type: "page",
  space: { key: "DEV", name: "Development" },
  body: { storage: { value: "<p>hi</p>", representation: "storage" } },
  version: { number: 1 },
});

describe("createConfluenceClient — getPage", () => {
  it("fetches /rest/api/content/{id}, parses via ConfluencePage schema, and carries Basic auth", async () => {
    let capturedAuth: string | null = null;
    server.use(
      http.get(`${BASE_URL}/rest/api/content/12345`, ({ request }) => {
        capturedAuth = request.headers.get("authorization");
        return HttpResponse.json(validPage("12345", "Home"));
      }),
    );

    const client = makeClient();
    const page = await client.getPage("12345");

    expect(capturedAuth).toBe(EXPECTED_AUTH_HEADER);
    expect(page.id).toBe("12345");
    expect(page.title).toBe("Home");
    expect(page.body.storage.value).toBe("<p>hi</p>");
  });

  it("throws if the response fails schema validation", async () => {
    server.use(
      http.get(`${BASE_URL}/rest/api/content/bad`, () => HttpResponse.json({ id: "bad" })),
    );
    const client = makeClient();
    await expect(client.getPage("bad")).rejects.toThrow();
  });
});

describe("createConfluenceClient — getPageTree", () => {
  it("walks /child/page recursively and builds a PageTreeNode tree", async () => {
    // Shape: root -> [A -> [A1], B]
    const childMap: Record<string, Array<{ id: string; title: string }>> = {
      root: [
        { id: "a", title: "A" },
        { id: "b", title: "B" },
      ],
      a: [{ id: "a1", title: "A1" }],
      b: [],
      a1: [],
    };
    server.use(
      http.get(`${BASE_URL}/rest/api/content/:id`, ({ params }) => {
        const id = params.id as string;
        return HttpResponse.json(validPage(id, id.toUpperCase()));
      }),
      http.get(`${BASE_URL}/rest/api/content/:id/child/page`, ({ params }) => {
        const id = params.id as string;
        const children = childMap[id] ?? [];
        return HttpResponse.json({
          results: children.map((c) => validPage(c.id, c.title)),
          size: children.length,
          limit: 25,
          start: 0,
        });
      }),
    );

    const client = makeClient();
    const tree = await client.getPageTree("root", { maxDepth: 5 });

    expect(tree.id).toBe("root");
    expect(tree.children.map((c) => c.id).sort()).toEqual(["a", "b"]);
    const a = tree.children.find((c) => c.id === "a");
    expect(a?.children.map((c) => c.id)).toEqual(["a1"]);
    expect(a?.children[0]?.children).toEqual([]);
  });

  it("respects maxDepth by not recursing past the configured depth", async () => {
    const callCounts: Record<string, number> = {};
    server.use(
      http.get(`${BASE_URL}/rest/api/content/:id`, ({ params }) =>
        HttpResponse.json(validPage(params.id as string)),
      ),
      http.get(`${BASE_URL}/rest/api/content/:id/child/page`, ({ params }) => {
        const id = params.id as string;
        callCounts[id] = (callCounts[id] ?? 0) + 1;
        if (id === "root") {
          return HttpResponse.json({
            results: [validPage("child-1"), validPage("child-2")],
            size: 2,
            limit: 25,
            start: 0,
          });
        }
        return HttpResponse.json({ results: [], size: 0, limit: 25, start: 0 });
      }),
    );

    const client = makeClient();
    const tree = await client.getPageTree("root", { maxDepth: 1 });

    expect(tree.children.map((c) => c.id)).toEqual(["child-1", "child-2"]);
    // children of root are depth 1 (leaves) — the client must NOT fetch /child/page for them.
    expect(callCounts.root).toBe(1);
    expect(callCounts["child-1"]).toBeUndefined();
    expect(callCounts["child-2"]).toBeUndefined();
  });

  it("sends Basic auth on every request during tree walk", async () => {
    const authSeen = new Set<string | null>();
    server.use(
      http.get(`${BASE_URL}/rest/api/content/:id`, ({ request, params }) => {
        authSeen.add(request.headers.get("authorization"));
        return HttpResponse.json(validPage(params.id as string));
      }),
      http.get(`${BASE_URL}/rest/api/content/:id/child/page`, ({ request }) => {
        authSeen.add(request.headers.get("authorization"));
        return HttpResponse.json({ results: [], size: 0, limit: 25, start: 0 });
      }),
    );

    await makeClient().getPageTree("root", { maxDepth: 3 });
    expect(Array.from(authSeen)).toEqual([EXPECTED_AUTH_HEADER]);
  });
});

describe("createConfluenceClient — listSpacePages", () => {
  it("threads start/limit pagination through query params", async () => {
    const capturedUrls: string[] = [];
    server.use(
      http.get(`${BASE_URL}/rest/api/content`, ({ request }) => {
        capturedUrls.push(request.url);
        return HttpResponse.json({
          results: [validPage("p-1"), validPage("p-2")],
          size: 2,
          limit: 25,
          start: 50,
        });
      }),
    );

    const client = makeClient();
    const result = await client.listSpacePages("DEV", { limit: 25, cursor: 50 });

    expect(capturedUrls).toHaveLength(1);
    const parsed = new URL(capturedUrls[0] as string);
    expect(parsed.searchParams.get("spaceKey")).toBe("DEV");
    expect(parsed.searchParams.get("start")).toBe("50");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(result.results.map((p) => p.id)).toEqual(["p-1", "p-2"]);
  });

  it("defaults the cursor to 0 when only limit is provided", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE_URL}/rest/api/content`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ results: [], size: 0, limit: 10, start: 0 });
      }),
    );
    await makeClient().listSpacePages("DEV", { limit: 10 });
    const parsed = new URL(capturedUrl);
    expect(parsed.searchParams.get("start")).toBe("0");
    expect(parsed.searchParams.get("limit")).toBe("10");
  });

  it("sends Basic auth", async () => {
    let capturedAuth: string | null = null;
    server.use(
      http.get(`${BASE_URL}/rest/api/content`, ({ request }) => {
        capturedAuth = request.headers.get("authorization");
        return HttpResponse.json({ results: [], size: 0, limit: 25, start: 0 });
      }),
    );
    await makeClient().listSpacePages("DEV", { limit: 25, cursor: 0 });
    expect(capturedAuth).toBe(EXPECTED_AUTH_HEADER);
  });
});

describe("createConfluenceClient — getAttachment", () => {
  it("returns the binary body as a Uint8Array", async () => {
    const payload = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]);
    server.use(
      http.get(`${BASE_URL}/download/attachments/99/diagram.png`, () =>
        HttpResponse.arrayBuffer(payload.buffer, {
          headers: { "content-type": "image/png" },
        }),
      ),
    );

    const bytes = await makeClient().getAttachment("99", "diagram.png");
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(Array.from(bytes)).toEqual(Array.from(payload));
  });

  it("carries Basic auth on the download request", async () => {
    let capturedAuth: string | null = null;
    server.use(
      http.get(`${BASE_URL}/download/attachments/99/diagram.png`, ({ request }) => {
        capturedAuth = request.headers.get("authorization");
        return HttpResponse.arrayBuffer(new Uint8Array([1, 2, 3]).buffer);
      }),
    );
    await makeClient().getAttachment("99", "diagram.png");
    expect(capturedAuth).toBe(EXPECTED_AUTH_HEADER);
  });

  it("url-encodes filenames that contain spaces or special characters", async () => {
    let capturedPath = "";
    server.use(
      http.get(`${BASE_URL}/download/attachments/99/*`, ({ request }) => {
        capturedPath = new URL(request.url).pathname;
        return HttpResponse.arrayBuffer(new Uint8Array([0]).buffer);
      }),
    );
    await makeClient().getAttachment("99", "my file (final).png");
    expect(capturedPath).toContain("my%20file%20");
  });
});
