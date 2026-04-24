import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  extractDataRowsFromXhtml,
  extractHeaderSignature,
  extractHeadersFromXhtml,
  inferColumnTypes,
  loadTableRules,
  normalizeHeaderSignature,
  saveTableRules,
} from "../../src/converter/tableRules.js";

describe("normalizeHeaderSignature", () => {
  it("lowercases, strips, and joins with | preserving order", () => {
    expect(normalizeHeaderSignature(["Status", " Owner ", "ETA"])).toBe("status|owner|eta");
  });

  it("throws on an empty list", () => {
    expect(() => normalizeHeaderSignature([])).toThrow();
  });

  it("preserves internal whitespace but collapses leading/trailing", () => {
    expect(normalizeHeaderSignature(["  Task Name  ", "Due Date"])).toBe("task name|due date");
  });
});

describe("extractHeadersFromXhtml", () => {
  it("prefers the first <tr> inside <thead>", () => {
    const xhtml = `
      <table>
        <thead><tr><th>Status</th><th>Owner</th></tr></thead>
        <tbody><tr><td>open</td><td>Alice</td></tr></tbody>
      </table>`;
    expect(extractHeadersFromXhtml(xhtml)).toEqual(["Status", "Owner"]);
  });

  it("falls back to the first <tr> when <thead> is absent", () => {
    const xhtml = `
      <table>
        <tr><th>A</th><th>B</th></tr>
        <tr><td>1</td><td>2</td></tr>
      </table>`;
    expect(extractHeadersFromXhtml(xhtml)).toEqual(["A", "B"]);
  });

  it("returns [] when the table has no <th> cells", () => {
    const xhtml = "<table><tr><td>1</td><td>2</td></tr></table>";
    expect(extractHeadersFromXhtml(xhtml)).toEqual([]);
  });

  it("returns [] when the snippet cannot be parsed", () => {
    expect(extractHeadersFromXhtml("<<< not xml")).toEqual([]);
  });

  it("strips inline formatting inside <th>", () => {
    const xhtml =
      "<table><thead><tr><th>  <strong>Status</strong>  </th><th><em>Owner</em></th></tr></thead></table>";
    expect(extractHeadersFromXhtml(xhtml)).toEqual(["Status", "Owner"]);
  });
});

describe("extractDataRowsFromXhtml", () => {
  it("returns data rows skipping header-only rows", () => {
    const xhtml = `
      <table>
        <tr><th>A</th><th>B</th></tr>
        <tr><td>1</td><td>2</td></tr>
        <tr><td>3</td><td>4</td></tr>
      </table>`;
    expect(extractDataRowsFromXhtml(xhtml)).toEqual([
      ["1", "2"],
      ["3", "4"],
    ]);
  });

  it("honours the maxRows limit", () => {
    const xhtml = `
      <table>
        <tr><td>a</td></tr>
        <tr><td>b</td></tr>
        <tr><td>c</td></tr>
      </table>`;
    expect(extractDataRowsFromXhtml(xhtml, 2)).toEqual([["a"], ["b"]]);
  });

  it("returns [] when the snippet cannot be parsed", () => {
    expect(extractDataRowsFromXhtml("<<< not xml")).toEqual([]);
  });
});

describe("extractHeaderSignature", () => {
  it("extracts and normalizes in one step", () => {
    const xhtml = "<table><thead><tr><th>Status</th><th>Owner</th></tr></thead></table>";
    expect(extractHeaderSignature(xhtml)).toBe("status|owner");
  });

  it("returns null when no <th> row exists", () => {
    const xhtml = "<table><tr><td>a</td></tr></table>";
    expect(extractHeaderSignature(xhtml)).toBeNull();
  });

  it("returns null on unparseable input", () => {
    expect(extractHeaderSignature("<<< nope")).toBeNull();
  });
});

describe("inferColumnTypes", () => {
  it("detects ISO-style date columns", () => {
    const headers = ["Due"];
    const rows = [["2026-01-01"], ["2026/02/15"], ["2026.03.31"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Due: "date" });
  });

  it("detects dmy-style date columns with mixed separators", () => {
    const headers = ["Date"];
    const rows = [["1/2/2026"], ["31-12-2026"], ["05.06.2026"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Date: "date" });
  });

  it("detects a select column: low-cardinality with repeats", () => {
    const headers = ["Status"];
    const rows = [["open"], ["open"], ["closed"], ["open"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Status: "select" });
  });

  it("falls back to rich_text when there are fewer than the minimum rows", () => {
    const headers = ["Status"];
    const rows = [["open"], ["closed"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Status: "rich_text" });
  });

  it("falls back to rich_text when distinct count exceeds the select ceiling", () => {
    const headers = ["Owner"];
    const rows = [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Owner: "rich_text" });
  });

  it("falls back to rich_text when every value is unique (no repeats)", () => {
    const headers = ["Owner"];
    const rows = [["alice"], ["bob"], ["carol"]];
    expect(inferColumnTypes(rows, headers)).toEqual({ Owner: "rich_text" });
  });

  it("pads short rows with empty strings when inferring", () => {
    const headers = ["A", "B"];
    const rows = [["x"], ["x"], ["y"]];
    const result = inferColumnTypes(rows, headers);
    expect(result.A).toBe("select");
    expect(result.B).toBe("rich_text");
  });
});

describe("loadTableRules / saveTableRules", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "c2n-tablerules-"));
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("returns an empty rule set when the file is missing", async () => {
    const result = await loadTableRules(join(dir, "does-not-exist.json"));
    expect(result).toEqual({ rules: {} });
  });

  it("round-trips a rule set through disk", async () => {
    const path = join(dir, "rules.json");
    const rules = {
      rules: {
        "status|owner": {
          isDatabase: true,
          titleColumn: "owner",
          columnTypes: { status: "select", owner: "title" } as const,
        },
      },
    };
    await saveTableRules(path, rules);
    const contents = await readFile(path, "utf8");
    expect(JSON.parse(contents)).toBeTruthy();
    const reloaded = await loadTableRules(path);
    expect(reloaded.rules["status|owner"]?.isDatabase).toBe(true);
    expect(reloaded.rules["status|owner"]?.titleColumn).toBe("owner");
    expect(reloaded.rules["status|owner"]?.columnTypes).toEqual({
      status: "select",
      owner: "title",
    });
  });

  it("creates parent directories on save", async () => {
    const path = join(dir, "nested", "a", "b", "rules.json");
    await saveTableRules(path, { rules: {} });
    const reloaded = await loadTableRules(path);
    expect(reloaded.rules).toEqual({});
  });

  it("returns an empty rule set on malformed JSON (matches Python fallback)", async () => {
    const path = join(dir, "bad.json");
    await writeFile(path, "not valid json", "utf8");
    const result = await loadTableRules(path);
    expect(result).toEqual({ rules: {} });
  });

  it("returns an empty rule set when JSON violates the schema", async () => {
    const path = join(dir, "invalid.json");
    await writeFile(
      path,
      JSON.stringify({ rules: { "status|owner": { isDatabase: true, titleColumn: "missing" } } }),
      "utf8",
    );
    const result = await loadTableRules(path);
    expect(result).toEqual({ rules: {} });
  });
});
