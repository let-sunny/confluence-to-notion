// Port of `src/confluence_to_notion/converter/table_rules.py` (see
// `git show 112afeb^:src/confluence_to_notion/converter/table_rules.py`).
// The Python store's TableRuleStore class is flattened into load/save
// functions here — callers manipulate `TableRuleSet.rules` directly. The
// header heuristics (date regex, select thresholds) are copied verbatim
// because they were tuned against the historical Python corpus.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import * as parse5 from "parse5";
import type { DefaultTreeAdapterTypes } from "parse5";
import { type NotionPropertyType, type TableRuleSet, TableRuleSetSchema } from "./schemas.js";

type Element = DefaultTreeAdapterTypes.Element;
type ChildNode = DefaultTreeAdapterTypes.ChildNode;
type ParentNode = DefaultTreeAdapterTypes.ParentNode;

const DATE_RE = /^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})$/;
const SELECT_MAX_DISTINCT = 5;
const SELECT_MIN_ROWS = 3;

export function normalizeHeaderSignature(headers: string[]): string {
  if (headers.length === 0) {
    throw new Error("normalizeHeaderSignature requires at least one header");
  }
  return headers.map((h) => h.trim().toLowerCase()).join("|");
}

function isElement(node: ChildNode | ParentNode): node is Element {
  return "tagName" in node;
}

function elementChildren(node: ParentNode): Element[] {
  return node.childNodes.filter(isElement);
}

function* walkElements(node: ParentNode): Generator<Element> {
  for (const child of node.childNodes) {
    if (isElement(child)) {
      yield child;
      yield* walkElements(child);
    }
  }
}

function textOf(node: ParentNode): string {
  let acc = "";
  for (const child of node.childNodes) {
    if (isElement(child)) {
      acc += textOf(child);
    } else if (child.nodeName === "#text") {
      acc += child.value;
    }
  }
  return acc;
}

function collapseWhitespace(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").trim();
}

function parseFragmentSafe(xhtml: string): ParentNode | null {
  try {
    return parse5.parseFragment(xhtml);
  } catch {
    return null;
  }
}

export function extractHeadersFromXhtml(xhtml: string): string[] {
  const root = parseFragmentSafe(xhtml);
  if (!root) return [];

  let headerRow: Element | undefined;
  for (const el of walkElements(root)) {
    if (el.tagName === "thead") {
      headerRow = elementChildren(el).find((c) => c.tagName === "tr");
      if (headerRow) break;
    }
  }
  if (!headerRow) {
    for (const el of walkElements(root)) {
      if (el.tagName === "tr") {
        headerRow = el;
        break;
      }
    }
  }
  if (!headerRow) return [];

  const headers: string[] = [];
  for (const cell of elementChildren(headerRow)) {
    if (cell.tagName === "th") {
      headers.push(collapseWhitespace(textOf(cell)));
    }
  }
  return headers;
}

export function extractDataRowsFromXhtml(xhtml: string, maxRows = 5): string[][] {
  const root = parseFragmentSafe(xhtml);
  if (!root) return [];

  const rows: string[][] = [];
  for (const el of walkElements(root)) {
    if (el.tagName !== "tr") continue;
    const cells = elementChildren(el).filter((c) => c.tagName === "td" || c.tagName === "th");
    if (cells.length === 0) continue;
    if (cells.every((c) => c.tagName === "th")) continue;
    rows.push(cells.map((c) => collapseWhitespace(textOf(c))));
    if (rows.length >= maxRows) break;
  }
  return rows;
}

export function extractHeaderSignature(xhtml: string): string | null {
  const headers = extractHeadersFromXhtml(xhtml);
  if (headers.length === 0) return null;
  return normalizeHeaderSignature(headers);
}

function looksLikeDate(values: string[]): boolean {
  const stripped = values.map((v) => v.trim()).filter((v) => v.length > 0);
  if (stripped.length === 0) return false;
  return stripped.every((v) => DATE_RE.test(v));
}

function looksLikeSelect(values: string[]): boolean {
  const nonEmpty = values.map((v) => v.trim()).filter((v) => v.length > 0);
  if (nonEmpty.length < SELECT_MIN_ROWS) return false;
  const distinct = new Set(nonEmpty);
  if (distinct.size > SELECT_MAX_DISTINCT) return false;
  // Require at least one repeat so free-form short strings don't look categorical.
  return distinct.size < nonEmpty.length;
}

export function inferColumnTypes(
  rows: string[][],
  headers: string[],
): Record<string, NotionPropertyType> {
  const result: Record<string, NotionPropertyType> = {};
  for (let idx = 0; idx < headers.length; idx += 1) {
    const header = headers[idx] as string;
    const column = rows.map((row) => (idx < row.length ? (row[idx] as string) : ""));
    if (looksLikeDate(column)) {
      result[header] = "date";
    } else if (looksLikeSelect(column)) {
      result[header] = "select";
    } else {
      result[header] = "rich_text";
    }
  }
  return result;
}

export async function loadTableRules(path: string): Promise<TableRuleSet> {
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return { rules: {} };
    }
    console.error(`Failed to read ${path}, starting fresh`);
    return { rules: {} };
  }
  try {
    const json = JSON.parse(raw) as unknown;
    return TableRuleSetSchema.parse(json);
  } catch {
    console.error(`Failed to load ${path}, starting fresh`);
    return { rules: {} };
  }
}

export async function saveTableRules(path: string, rules: TableRuleSet): Promise<void> {
  const validated = TableRuleSetSchema.parse(rules);
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(validated, null, 2)}\n`, "utf8");
}
