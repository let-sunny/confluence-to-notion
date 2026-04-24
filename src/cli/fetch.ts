import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { Command } from "commander";
import { type FetchLike, createConfluenceClient } from "../confluence/client.js";
import { type RunContext, finalizeRun, startRun, updateStep } from "../runs/index.js";
import { readConfluenceAuth, readConfluenceBaseUrl } from "./confluenceEnv.js";

export interface FetchCliOptions {
  space?: string;
  pages?: string;
  limit: string;
  outDir: string;
  url?: string;
}

function outputRootDir(): string {
  return join(process.cwd(), "output");
}

/** When `C2N_USE_GLOBAL_FETCH=1`, use `globalThis.fetch` so MSW can intercept in tests. */
function createCliConfluenceClient(): ReturnType<typeof createConfluenceClient> {
  const { email, token } = readConfluenceAuth();
  const baseUrl = readConfluenceBaseUrl();
  const useGlobal = process.env.C2N_USE_GLOBAL_FETCH === "1";
  const g = globalThis as { fetch?: FetchLike };
  return createConfluenceClient({
    email,
    token,
    baseUrl,
    ...(useGlobal && typeof g.fetch === "function" ? { fetchImpl: g.fetch } : {}),
  });
}

async function writePageXhtml(targetDir: string, pageId: string, xhtml: string): Promise<void> {
  await mkdir(targetDir, { recursive: true });
  const path = join(targetDir, `${pageId}.xhtml`);
  await writeFile(path, xhtml, "utf8");
}

async function runFetchWithClient(
  client: ReturnType<typeof createConfluenceClient>,
  opts: FetchCliOptions,
  runContext: RunContext | null,
): Promise<number> {
  const limit = Number.parseInt(opts.limit, 10) || 25;
  let count = 0;
  const samplesDir = runContext
    ? join(runContext.runDir, "samples")
    : join(process.cwd(), opts.outDir);

  if (opts.pages !== undefined && opts.pages.length > 0) {
    const ids = opts.pages
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    for (const id of ids) {
      const page = await client.getPage(id);
      const body = page.body.storage.value;
      await writePageXhtml(samplesDir, page.id, body);
      count += 1;
    }
    return count;
  }

  if (opts.space !== undefined && opts.space.length > 0) {
    let cursor = 0;
    while (true) {
      const batch = await client.listSpacePages(opts.space, { limit, cursor });
      for (const page of batch.results) {
        const body = page.body.storage.value;
        await writePageXhtml(samplesDir, page.id, body);
        count += 1;
      }
      if (batch.size < limit) break;
      cursor = batch.start + batch.size;
    }
    return count;
  }

  throw new Error("internal: neither pages nor space");
}

export async function runFetchCommand(opts: FetchCliOptions): Promise<void> {
  if (
    (opts.pages === undefined || opts.pages.trim() === "") &&
    (opts.space === undefined || opts.space.trim() === "")
  ) {
    process.stderr.write("fetch: provide --space <key> or --pages <comma-separated-ids>.\n");
    process.exit(1);
  }

  const client = createCliConfluenceClient();

  let runContext: RunContext | null = null;
  if (opts.url !== undefined && opts.url.length > 0) {
    const sourceType = opts.space !== undefined && opts.space.length > 0 ? "space" : "page";
    const started = await startRun({
      outputRoot: outputRootDir(),
      url: opts.url,
      sourceType,
    });
    runContext = started.context;
    await updateStep(runContext, "fetch", "running");
    try {
      const count = await runFetchWithClient(client, opts, runContext);
      await updateStep(runContext, "fetch", "done", { count });
      await finalizeRun(runContext);
      process.stdout.write(`fetch: wrote ${String(count)} page(s) under ${runContext.runDir}\n`);
    } catch (e) {
      await updateStep(runContext, "fetch", "failed");
      await finalizeRun(runContext);
      throw e;
    }
    return;
  }

  const count = await runFetchWithClient(client, opts, null);
  process.stdout.write(
    `fetch: wrote ${String(count)} page(s) to ${join(process.cwd(), opts.outDir)}\n`,
  );
}

export interface FetchTreeCliOptions {
  rootId: string;
  output: string;
  url?: string;
}

export async function runFetchTreeCommand(opts: FetchTreeCliOptions): Promise<void> {
  const client = createCliConfluenceClient();
  const tree = await client.getPageTree(opts.rootId, { maxDepth: 25 });
  const json = `${JSON.stringify(tree, null, 2)}\n`;

  if (opts.url !== undefined && opts.url.length > 0) {
    const { context } = await startRun({
      outputRoot: outputRootDir(),
      url: opts.url,
      sourceType: "tree",
      rootId: opts.rootId,
    });
    await updateStep(context, "fetch", "running");
    try {
      const path = join(context.runDir, "page-tree.json");
      await writeFile(path, json, "utf8");
      await updateStep(context, "fetch", "done", { count: 1 });
      await finalizeRun(context);
      process.stdout.write(`fetch-tree: wrote ${path}\n`);
    } catch (e) {
      await updateStep(context, "fetch", "failed");
      await finalizeRun(context);
      throw e;
    }
    return;
  }

  const outPath = join(process.cwd(), opts.output);
  await mkdir(dirname(outPath), { recursive: true });
  await writeFile(outPath, json, "utf8");
  process.stdout.write(`fetch-tree: wrote ${outPath}\n`);
}

export function registerFetchCommands(program: Command): void {
  program
    .command("fetch")
    .description("Fetch Confluence pages and save XHTML to disk.")
    .option("--space <key>", "Confluence space key (paginates with --limit)")
    .option("--pages <ids>", "comma-separated Confluence page IDs")
    .option("--limit <n>", "max pages when using --space", "25")
    .option("--out-dir <path>", "output directory for XHTML", "samples")
    .option("--url <url>", "Confluence source URL; writes artifacts under output/runs/<slug>/")
    .action(async function (this: Command) {
      const o = this.opts<FetchCliOptions>();
      try {
        await runFetchCommand(o);
      } catch (e) {
        process.stderr.write(`fetch: ${String(e)}\n`);
        process.exit(1);
      }
    });

  program
    .command("fetch-tree")
    .description("Fetch the Confluence page tree starting from a root page.")
    .requiredOption("--root-id <id>", "Confluence root page ID")
    .option("--output <path>", "output JSON path", "output/page-tree.json")
    .option("--url <url>", "Confluence source URL (overrides --output placement)")
    .action(async function (this: Command) {
      const o = this.opts<FetchTreeCliOptions>();
      try {
        await runFetchTreeCommand(o);
      } catch (e) {
        process.stderr.write(`fetch-tree: ${String(e)}\n`);
        process.exit(1);
      }
    });
}
