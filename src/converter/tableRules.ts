// Port of `src/confluence_to_notion/converter/table_rules.py` (see
// `git show 112afeb^:src/confluence_to_notion/converter/table_rules.py`).
// The Python store's TableRuleStore class is flattened into load/save
// functions here — callers manipulate `TableRuleSet.rules` directly. The
// header heuristics (date regex, select thresholds) are copied verbatim
// because they were tuned against the historical Python corpus.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { DOMParser } from "@xmldom/xmldom";
import { type NotionPropertyType, type TableRuleSet, TableRuleSetSchema } from "./schemas.js";

interface DomNode {
  readonly nodeType: number;
  readonly nodeName: string;
  readonly nodeValue: string | null;
  readonly childNodes: { length: number; item(i: number): DomNode | null };
}
interface Element extends DomNode {
  readonly tagName: string;
  readonly localName: string;
}
type ParentNode = DomNode;
type ChildNode = DomNode;

const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const CDATA_SECTION_NODE = 4;

const NAMESPACE_WRAPPER_OPEN =
  '<root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier">';
const NAMESPACE_WRAPPER_CLOSE = "</root>";

// Mirror of converter.ts's HTML_NAMED_ENTITIES — kept in sync deliberately
// (per ADR allowance to duplicate small helpers across these two files).
// A divergent map would cause rule inference to see literal `&deg;` while
// converter rendering decodes it to `°`, producing different column-type
// guesses than the rendered output.
const HTML_NAMED_ENTITIES: Record<string, string> = {
  nbsp: " ",
  ensp: " ",
  emsp: " ",
  thinsp: " ",
  ndash: "–",
  mdash: "—",
  hellip: "…",
  copy: "©",
  reg: "®",
  trade: "™",
  laquo: "«",
  raquo: "»",
  lsquo: "‘",
  rsquo: "’",
  ldquo: "“",
  rdquo: "”",
  sbquo: "‚",
  bdquo: "„",
  middot: "·",
  bull: "•",
  deg: "°",
  plusmn: "±",
  times: "×",
  divide: "÷",
  cent: "¢",
  pound: "£",
  euro: "€",
  yen: "¥",
  sect: "§",
  para: "¶",
  larr: "←",
  uarr: "↑",
  rarr: "→",
  darr: "↓",
  harr: "↔",
  hArr: "⇔",
  rArr: "⇒",
  lArr: "⇐",
  iexcl: "¡",
  iquest: "¿",
  shy: "­",
};

function decodeNamedHtmlEntities(input: string): string {
  const parts = input.split(/(<!\[CDATA\[[\s\S]*?\]\]>)/);
  for (let i = 0; i < parts.length; i += 1) {
    const part = parts[i];
    if (part === undefined || part.startsWith("<![CDATA[")) continue;
    parts[i] = part.replace(/&([a-zA-Z][a-zA-Z0-9]*);/g, (match, name: string) => {
      const ch = HTML_NAMED_ENTITIES[name];
      return ch !== undefined ? ch : match;
    });
  }
  return parts.join("");
}

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
  return node.nodeType === ELEMENT_NODE;
}

function* childNodesOf(node: ParentNode): Generator<ChildNode> {
  const list = node.childNodes;
  for (let i = 0; i < list.length; i += 1) {
    const child = list.item(i);
    if (child !== null) yield child;
  }
}

function elementChildren(node: ParentNode): Element[] {
  const out: Element[] = [];
  for (const child of childNodesOf(node)) {
    if (isElement(child)) out.push(child);
  }
  return out;
}

function* walkElements(node: ParentNode): Generator<Element> {
  for (const child of childNodesOf(node)) {
    if (isElement(child)) {
      yield child;
      yield* walkElements(child);
    }
  }
}

function textOf(node: ParentNode): string {
  let acc = "";
  for (const child of childNodesOf(node)) {
    if (isElement(child)) {
      acc += textOf(child);
    } else if (child.nodeType === TEXT_NODE || child.nodeType === CDATA_SECTION_NODE) {
      acc += child.nodeValue ?? "";
    }
  }
  return acc;
}

function collapseWhitespace(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").trim();
}

function parseFragmentSafe(xhtml: string): ParentNode | null {
  try {
    const wrapped =
      NAMESPACE_WRAPPER_OPEN + decodeNamedHtmlEntities(xhtml) + NAMESPACE_WRAPPER_CLOSE;
    const parser = new DOMParser({
      onError: (level: string, message: string) => {
        if (level === "error" || level === "fatalError") {
          console.warn(`tableRules: xhtml parse ${level}: ${message}`);
        }
      },
    });
    const doc = parser.parseFromString(wrapped, "text/xml");
    const root = doc.documentElement as unknown as ParentNode | null;
    if (root === null) {
      console.warn("tableRules: parser returned no documentElement; skipping table");
    }
    return root;
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
