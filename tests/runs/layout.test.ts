import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { finalizeRun, listRunLayoutTopLevel, startRun } from "../../src/runs/index.js";
import { rmTempOutputRoot, tempOutputRoot } from "./testUtils.js";

const fixtureDir = fileURLToPath(new URL("../fixtures/runs", import.meta.url));

afterEach(async () => {
  await rmTempOutputRoot();
});

describe("run directory layout", () => {
  it("matches reference-tree.json after startRun + finalizeRun", async () => {
    const refRaw = await readFile(join(fixtureDir, "reference-tree.json"), "utf8");
    const ref = JSON.parse(refRaw) as { topLevel: string[] };
    const expected = [...ref.topLevel].sort();

    const outputRoot = await tempOutputRoot();
    const url = "https://cwiki.apache.org/confluence/display/TEST/Integration+Page";
    const { context } = await startRun({
      outputRoot,
      url,
      sourceType: "page",
      rootId: null,
      notionTarget: { page_id: "test-parent-page-id" },
    });

    await finalizeRun(context);

    const actual = (await listRunLayoutTopLevel(context.runDir)).sort();
    expect(actual).toEqual(expected);
  });
});
