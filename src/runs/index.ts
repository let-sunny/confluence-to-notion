import { existsSync } from "node:fs";
import { appendFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import type { TableRuleSet } from "../converter/schemas.js";
import { TableRuleSetSchema } from "../converter/schemas.js";
import {
  type RunResolution,
  RunResolutionSchema,
  type RunStatus,
  RunStatusSchema,
  type RunStepName,
  type SourceInfo,
  SourceInfoSchema,
  type StepRecord,
  type StepStatus,
  defaultRunStatus,
} from "./schemas.js";

export {
  type Mapping,
  type RunResolution,
  type RunStatus,
  type RunStepName,
  type SourceInfo,
  type StepRecord,
  type StepStatus,
  MappingSchema,
  RunResolutionSchema,
  RunStatusSchema,
  RunStepNameSchema,
  SourceInfoSchema,
  StepRecordSchema,
  StepStatusSchema,
  defaultRunStatus,
} from "./schemas.js";

const KEBAB_RE = /[^a-z0-9]+/g;

function kebab(value: string): string {
  return value
    .toLowerCase()
    .replace(KEBAB_RE, "-")
    .replace(/^-+|-+$/g, "");
}

/** Derive `hostPrefix-key` slug from a Confluence URL (port of legacy `slug_for_url`). */
export function slugForUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new TypeError(`slugForUrl: invalid URL: ${url}`);
  }

  const hostPrefix = (parsed.hostname ?? "").split(".")[0]?.toLowerCase() ?? "run";

  const pageId = parsed.searchParams.get("pageId");
  if (pageId) {
    return `${hostPrefix}-${kebab(pageId)}`;
  }

  const segments = parsed.pathname.split("/").filter((s) => s.length > 0);
  for (let i = 0; i < segments.length; i += 1) {
    if (segments[i] === "pages" && i + 1 < segments.length) {
      const page = segments[i + 1];
      if (page !== undefined) {
        return `${hostPrefix}-${kebab(page)}`;
      }
    }
  }
  for (let i = 0; i < segments.length; i += 1) {
    if (segments[i] === "spaces" && i + 1 < segments.length) {
      const space = segments[i + 1];
      if (space !== undefined) {
        return `${hostPrefix}-${kebab(space)}`;
      }
    }
  }

  if (segments.length > 0) {
    const last = segments[segments.length - 1];
    if (last !== undefined) {
      return `${hostPrefix}-${kebab(last)}`;
    }
  }

  return hostPrefix;
}

export interface RunPaths {
  sourceJson: string;
  statusJson: string;
  reportMd: string;
  resolutionJson: string;
  convertedDir: string;
  rulesDir: string;
  tableRulesJson: string;
  logsDir: string;
}

export interface RunContext {
  readonly runDir: string;
  /** Final directory name under `runs/` (includes `-2` when allocated on collision). */
  readonly slug: string;
  readonly paths: RunPaths;
}

export interface StartRunOptions {
  outputRoot: string;
  url: string;
  sourceType: string;
  rootId?: string | null;
  notionTarget?: Record<string, unknown> | null;
  slugOverride?: string | null;
}

function buildPaths(runDir: string): RunPaths {
  return {
    sourceJson: join(runDir, "source.json"),
    statusJson: join(runDir, "status.json"),
    reportMd: join(runDir, "report.md"),
    resolutionJson: join(runDir, "resolution.json"),
    convertedDir: join(runDir, "converted"),
    rulesDir: join(runDir, "rules"),
    tableRulesJson: join(runDir, "rules", "table-rules.json"),
    logsDir: join(runDir, "logs"),
  };
}

export async function allocateRunDirectory(outputRoot: string, slug: string): Promise<string> {
  const runsRoot = join(outputRoot, "runs");
  await mkdir(runsRoot, { recursive: true });
  let candidate = join(runsRoot, slug);
  let suffix = 2;
  while (existsSync(candidate)) {
    candidate = join(runsRoot, `${slug}-${suffix}`);
    suffix += 1;
  }
  await mkdir(candidate);
  return candidate;
}

async function ensureRunSubdirectories(runDir: string, paths: RunPaths): Promise<void> {
  await mkdir(paths.convertedDir, { recursive: true });
  await mkdir(paths.rulesDir, { recursive: true });
  await mkdir(paths.logsDir, { recursive: true });
  await mkdir(join(runDir, "samples"), { recursive: true });
}

const STEP_ORDER: RunStepName[] = ["fetch", "discover", "convert", "migrate"];

function formatStepLine(name: RunStepName, record: StepRecord): string {
  const parts: string[] = [`**${name}**: ${record.status}`];
  if (record.at !== null) {
    parts.push(`at ${record.at}`);
  }
  if (record.count !== null) {
    parts.push(`count=${record.count}`);
  }
  if (record.warnings !== null) {
    parts.push(`warnings=${record.warnings}`);
  }
  return `- ${parts.join(" · ")}`;
}

export function renderReport(
  source: SourceInfo,
  status: RunStatus,
  rulesSummary?: string | null,
): string {
  const lines: string[] = [
    "# Run Report",
    "",
    "## Source",
    `- url: ${source.url}`,
    `- type: ${source.type}`,
  ];
  if (source.root_id !== undefined && source.root_id !== null) {
    lines.push(`- root_id: ${source.root_id}`);
  }
  if (source.notion_target !== undefined && source.notion_target !== null) {
    lines.push(`- notion_target: ${JSON.stringify(source.notion_target)}`);
  }
  lines.push("", "## Steps");
  for (const name of STEP_ORDER) {
    lines.push(formatStepLine(name, status[name]));
  }
  if (source.rules_source !== undefined && source.rules_source !== null) {
    lines.push("", "## Rules source", `- source: ${source.rules_source}`);
    if (source.rules_generated_at !== undefined && source.rules_generated_at !== null) {
      lines.push(`- last generated_at: ${source.rules_generated_at}`);
    }
  }
  if (rulesSummary !== undefined && rulesSummary !== null && rulesSummary.length > 0) {
    lines.push("", "## Rules usage", rulesSummary);
  }
  lines.push("");
  return lines.join("\n");
}

export function formatRulesSummary(usedRules: Record<string, number>): string | null {
  const keys = Object.keys(usedRules);
  if (keys.length === 0) {
    return null;
  }
  return keys
    .sort((a, b) => a.localeCompare(b))
    .map((ruleId) => `- ${ruleId}: ${usedRules[ruleId]}`)
    .join("\n");
}

export async function readSource(runDir: string): Promise<SourceInfo> {
  const raw = await readFile(join(runDir, "source.json"), "utf8");
  return SourceInfoSchema.parse(JSON.parse(raw));
}

export async function writeSource(runDir: string, source: SourceInfo): Promise<void> {
  const parsed = SourceInfoSchema.parse(source);
  await writeFile(join(runDir, "source.json"), `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
}

export async function readStatus(runDir: string): Promise<RunStatus> {
  const raw = await readFile(join(runDir, "status.json"), "utf8");
  return RunStatusSchema.parse(JSON.parse(raw));
}

export async function writeStatus(runDir: string, status: RunStatus): Promise<void> {
  const parsed = RunStatusSchema.parse(status);
  await writeFile(join(runDir, "status.json"), `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
}

export async function startRun(
  options: StartRunOptions,
): Promise<{ context: RunContext; source: SourceInfo }> {
  const baseSlug =
    options.slugOverride !== undefined &&
    options.slugOverride !== null &&
    options.slugOverride.trim() !== ""
      ? options.slugOverride.trim()
      : slugForUrl(options.url);
  const runDir = await allocateRunDirectory(options.outputRoot, baseSlug);
  const paths = buildPaths(runDir);
  await ensureRunSubdirectories(runDir, paths);

  const source: SourceInfo = {
    url: options.url,
    type: options.sourceType,
    root_id: options.rootId ?? null,
    notion_target: options.notionTarget === undefined ? null : options.notionTarget,
  };
  await writeSource(runDir, source);
  await writeStatus(runDir, defaultRunStatus());

  const context: RunContext = {
    runDir,
    slug: basename(runDir),
    paths,
  };
  return { context, source };
}

export async function updateStep(
  context: RunContext,
  step: RunStepName,
  status: StepStatus,
  opts?: { count?: number | null; warnings?: number | null },
): Promise<void> {
  const current = await readStatus(context.runDir);
  const at = new Date().toISOString();
  const record = {
    status,
    at,
    count: opts?.count === undefined ? null : opts.count,
    warnings: opts?.warnings === undefined ? null : opts.warnings,
  };
  const updated: RunStatus = { ...current, [step]: record };
  await writeStatus(context.runDir, updated);
}

export interface FinalizeRunOptions {
  rulesSummary?: string | null;
}

export async function finalizeRun(
  context: RunContext,
  options?: FinalizeRunOptions,
): Promise<void> {
  const source = await readSource(context.runDir);
  const status = await readStatus(context.runDir);
  const body = renderReport(source, status, options?.rulesSummary ?? null);
  await writeFile(context.paths.reportMd, body, "utf8");
}

export async function writeResolution(context: RunContext, entries: RunResolution): Promise<void> {
  const parsed = RunResolutionSchema.parse(entries);
  await writeFile(context.paths.resolutionJson, `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
}

export async function writeConvertedPage(
  context: RunContext,
  pageId: string,
  payload: unknown,
): Promise<void> {
  const safeId = pageId.replace(/[^\w.-]+/g, "_");
  const filePath = join(context.paths.convertedDir, `${safeId}.json`);
  await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

export async function writeTableRules(context: RunContext, ruleSet: TableRuleSet): Promise<void> {
  const parsed = TableRuleSetSchema.parse(ruleSet);
  await writeFile(context.paths.tableRulesJson, `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
}

export async function appendLog(context: RunContext, name: string, line: string): Promise<void> {
  const safe = name.replace(/[^\w.-]+/g, "_");
  const filePath = join(context.paths.logsDir, `${safe}.log`);
  await appendFile(filePath, `${line}\n`, "utf8");
}

/** Sorted top-level names; directories include a trailing `/` (for drift fixtures). */
export async function listRunLayoutTopLevel(runDir: string): Promise<string[]> {
  const entries = await readdir(runDir, { withFileTypes: true });
  return entries
    .map((e) => (e.isDirectory() ? `${e.name}/` : e.name))
    .sort((a, b) => a.localeCompare(b));
}
