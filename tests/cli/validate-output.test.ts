import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { validateOutputFile } from "../../src/cli/validate.js";

let tmp: string | null = null;

afterEach(async () => {
  if (tmp) {
    await rm(tmp, { recursive: true, force: true });
    tmp = null;
  }
});

describe("validateOutputFile", () => {
  it("accepts a valid discovery document", async () => {
    tmp = await mkdtemp(join(tmpdir(), "c2n-val-"));
    const path = join(tmp, "patterns.json");
    const doc = {
      sample_dir: "samples/",
      pages_analyzed: 1,
      patterns: [
        {
          pattern_id: "macro:toc",
          pattern_type: "macro",
          description: "TOC",
          example_snippets: ['<ac:structured-macro ac:name="toc"></ac:structured-macro>'],
          source_pages: ["1"],
          frequency: 1,
        },
      ],
    };
    await writeFile(path, JSON.stringify(doc), "utf8");
    await expect(validateOutputFile(path, "discovery")).resolves.toBeUndefined();
  });

  it("rejects invalid discovery JSON shape", async () => {
    tmp = await mkdtemp(join(tmpdir(), "c2n-val-"));
    const path = join(tmp, "bad.json");
    await writeFile(
      path,
      JSON.stringify({ sample_dir: "x", pages_analyzed: 0, patterns: [] }),
      "utf8",
    );
    await expect(validateOutputFile(path, "discovery")).rejects.toThrow();
  });

  it("accepts scout sources.json", async () => {
    tmp = await mkdtemp(join(tmpdir(), "c2n-val-"));
    const path = join(tmp, "sources.json");
    const doc = {
      sources: [
        {
          wiki_url: "https://example.com/wiki",
          space_key: "S",
          macro_density: 0.5,
          sample_macros: ["toc"],
          page_count: 10,
          accessible: true,
        },
      ],
    };
    await writeFile(path, JSON.stringify(doc), "utf8");
    await expect(validateOutputFile(path, "scout")).resolves.toBeUndefined();
  });

  it("reads file from disk for integration-style check", async () => {
    tmp = await mkdtemp(join(tmpdir(), "c2n-val-"));
    const path = join(tmp, "p.json");
    await writeFile(path, "not json", "utf8");
    await expect(validateOutputFile(path, "discovery")).rejects.toThrow(/Invalid JSON/);
  });
});
