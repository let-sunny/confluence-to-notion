import { mkdir, mkdtemp, readFile, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { runFetchCommand } from "../../src/cli/fetch.js";

const BASE = "https://eval-msw.example.test/wiki";
const EMAIL = "judge@example.com";
const TOKEN = "token";

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  process.env.CONFLUENCE_BASE_URL = undefined;
  process.env.CONFLUENCE_EMAIL = undefined;
  process.env.CONFLUENCE_API_TOKEN = undefined;
  process.env.C2N_USE_GLOBAL_FETCH = undefined;
});

afterAll(() => {
  server.close();
});

const validPage = (id: string) => ({
  id,
  title: "T",
  type: "page",
  space: { key: "S", name: "S" },
  body: { storage: { value: "<p>mocked</p>", representation: "storage" } },
  version: { number: 1 },
});

describe("fetch --url with MSW (global fetch)", () => {
  it("writes XHTML under output/runs/<slug>/samples/", async () => {
    const tmp = await mkdtemp(join(tmpdir(), "c2n-fetch-msw-"));
    await mkdir(join(tmp, "output"), { recursive: true });
    const cwdSpy = vi.spyOn(process, "cwd").mockReturnValue(tmp);

    process.env.CONFLUENCE_BASE_URL = BASE;
    process.env.CONFLUENCE_EMAIL = EMAIL;
    process.env.CONFLUENCE_API_TOKEN = TOKEN;
    process.env.C2N_USE_GLOBAL_FETCH = "1";

    server.use(
      http.get(`${BASE}/rest/api/content/77`, ({ request }) => {
        const u = new URL(request.url);
        expect(u.searchParams.get("expand")).toContain("body.storage");
        return HttpResponse.json(validPage("77"));
      }),
    );

    await runFetchCommand({
      pages: "77",
      limit: "25",
      outDir: "samples",
      url: "https://cwiki.apache.org/confluence/display/FOO/Bar",
    });

    const runsDir = join(tmp, "output", "runs");
    const slugs = await readdir(runsDir);
    expect(slugs.length).toBe(1);
    const slug = slugs[0];
    expect(slug).toBeDefined();
    const xhtmlPath = join(runsDir, slug ?? "", "samples", "77.xhtml");
    const body = await readFile(xhtmlPath, "utf8");
    expect(body).toContain("mocked");

    cwdSpy.mockRestore();
  });
});
