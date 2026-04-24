import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Command } from "commander";
import { describe, expect, it } from "vitest";
import { createProgram } from "../../src/cli/index.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ADR_PATH = join(__dirname, "..", "..", ".claude", "docs", "ADR-00M-cli-surface-freeze.md");

interface FlagSpec {
  name: string;
  default: string | undefined;
  required: boolean;
  envFallback: string | undefined;
}

interface PositionalSpec {
  name: string;
  default: string | undefined;
  required: boolean;
}

interface SubcommandSpec {
  name: string;
  flags: FlagSpec[];
  positionals: PositionalSpec[];
}

function parseDefault(cell: string): string | undefined {
  const trimmed = cell.trim();
  if (!trimmed || /^_none_$/i.test(trimmed)) return undefined;
  const match = /`([^`]+)`/.exec(trimmed);
  return match?.[1];
}

function parseEnv(cell: string): string | undefined {
  const match = /`([A-Z_][A-Z0-9_]*)`/.exec(cell);
  return match?.[1];
}

function parseRequired(cell: string): boolean {
  // Strict Yes / **Yes** only. Conditional phrases ("One of...", "Yes (in legacy form)",
  // "No (but required for the preferred form)") are treated as NOT strictly required
  // because commander cannot enforce cross-flag conditions at parse time.
  return /^(\*\*)?yes(\*\*)?$/i.test(cell.trim());
}

function parseTableRow(spec: SubcommandSpec, headers: string[], cells: string[]): void {
  const row: Record<string, string> = {};
  headers.forEach((h, i) => {
    row[h] = cells[i] ?? "";
  });

  const firstKey = headers[0];
  if (!firstKey) return;
  const firstVal = row[firstKey] ?? "";
  const backtickMatch = /`([^`]+)`/.exec(firstVal);
  if (!backtickMatch) return;
  const inner = backtickMatch[1] ?? "";

  const defaultValue = parseDefault(row.default ?? "");
  const required = parseRequired(row.required ?? "");
  const envFallback = parseEnv(row["env fallback"] ?? "");

  if (inner.startsWith("--")) {
    const name = inner;
    if (spec.flags.some((f) => f.name === name)) return;
    spec.flags.push({ name, default: defaultValue, required, envFallback });
    return;
  }

  if (/^[A-Z_]/.test(inner)) {
    const name = inner.split(/\s/)[0] ?? inner;
    if (spec.positionals.some((p) => p.name === name)) return;
    spec.positionals.push({ name, default: defaultValue, required });
  }
}

function parseAdr(): Map<string, SubcommandSpec> {
  const md = readFileSync(ADR_PATH, "utf8");
  const lines = md.split("\n");
  const specs = new Map<string, SubcommandSpec>();
  let current: SubcommandSpec | null = null;
  let headers: string[] = [];
  let inTable = false;

  const commit = (): void => {
    if (current) specs.set(current.name, current);
  };

  const subHeaderRe = /^###\s+`c2n\s+([a-z-]+)`/;
  const tableRowRe = /^\|(.+)\|\s*$/;
  const separatorRe = /^\|[\s:|-]+\|\s*$/;

  for (const line of lines) {
    const headerMatch = subHeaderRe.exec(line);
    if (headerMatch) {
      commit();
      current = { name: headerMatch[1] ?? "", flags: [], positionals: [] };
      inTable = false;
      headers = [];
      continue;
    }
    if (!current) continue;

    const rowMatch = tableRowRe.exec(line);
    if (rowMatch) {
      if (separatorRe.test(line)) continue;
      const cells = (rowMatch[1] ?? "").split("|").map((s) => s.trim());
      if (!inTable) {
        headers = cells.map((c) => c.toLowerCase());
        inTable = true;
        continue;
      }
      parseTableRow(current, headers, cells);
      continue;
    }
    inTable = false;
  }
  commit();
  return specs;
}

const EXPECTED_SUBCOMMANDS = [
  "fetch",
  "fetch-tree",
  "notion-ping",
  "discover",
  "validate-output",
  "finalize",
  "convert",
  "migrate",
  "migrate-tree",
  "migrate-tree-pages",
] as const;

function getSubcommands(program: Command): Map<string, Command> {
  const map = new Map<string, Command>();
  for (const cmd of program.commands) {
    map.set(cmd.name(), cmd);
  }
  return map;
}

describe("CLI surface: ADR-00M compliance", () => {
  const adrSpecs = parseAdr();
  const program = createProgram();
  const actual = getSubcommands(program);

  it("ADR-00M lists every expected subcommand", () => {
    const parsed = [...adrSpecs.keys()].sort();
    const expected = [...EXPECTED_SUBCOMMANDS].sort();
    expect(parsed).toEqual(expected);
  });

  it("registers exactly the frozen subcommand set (no drift)", () => {
    const actualNames = [...actual.keys()].sort();
    const expectedNames = [...EXPECTED_SUBCOMMANDS].sort();
    expect(actualNames).toEqual(expectedNames);
  });

  for (const subName of EXPECTED_SUBCOMMANDS) {
    describe(`c2n ${subName}`, () => {
      const spec = adrSpecs.get(subName);
      const cmd = actual.get(subName);

      it("is registered", () => {
        expect(cmd, `subcommand ${subName} missing`).toBeDefined();
        expect(spec, `ADR spec for ${subName} missing`).toBeDefined();
      });

      it("exposes exactly the ADR flag set", () => {
        if (!cmd || !spec) return;
        const actualFlags = cmd.options
          .map((o) => o.long ?? o.short ?? "")
          .filter((f) => f !== "")
          .sort();
        const expectedFlags = spec.flags.map((f) => f.name).sort();
        expect(actualFlags).toEqual(expectedFlags);
      });

      it("exposes exactly the ADR positional set", () => {
        if (!cmd || !spec) return;
        const actualArgs = cmd.registeredArguments.map((a) => a.name().toUpperCase()).sort();
        const expectedArgs = spec.positionals.map((p) => p.name.toUpperCase()).sort();
        expect(actualArgs).toEqual(expectedArgs);
      });

      it("each flag matches ADR default / required / env fallback", () => {
        if (!cmd || !spec) return;
        for (const flag of spec.flags) {
          const opt = cmd.options.find((o) => o.long === flag.name);
          expect(opt, `option ${flag.name} missing on ${subName}`).toBeDefined();
          if (!opt) continue;

          if (flag.default === undefined) {
            // Commander stores `undefined` (or `false` for boolean flags without a
            // user-supplied default) when no default is set. Accept either.
            expect(
              opt.defaultValue === undefined || opt.defaultValue === false,
              `${subName} ${flag.name} expected no default, got ${String(opt.defaultValue)}`,
            ).toBe(true);
          } else {
            expect(String(opt.defaultValue), `${subName} ${flag.name} default mismatch`).toBe(
              flag.default,
            );
          }

          expect(opt.mandatory, `${subName} ${flag.name} mandatory mismatch`).toBe(flag.required);

          if (flag.envFallback) {
            expect(opt.envVar, `${subName} ${flag.name} env fallback mismatch`).toBe(
              flag.envFallback,
            );
          }
        }
      });

      it("each positional matches ADR default / required", () => {
        if (!cmd || !spec) return;
        for (const pos of spec.positionals) {
          const arg = cmd.registeredArguments.find(
            (a) => a.name().toUpperCase() === pos.name.toUpperCase(),
          );
          expect(arg, `positional ${pos.name} missing on ${subName}`).toBeDefined();
          if (!arg) continue;
          expect(arg.required, `${subName} ${pos.name} required mismatch`).toBe(pos.required);
          if (pos.default === undefined) {
            expect(arg.defaultValue).toBeUndefined();
          } else {
            expect(String(arg.defaultValue)).toBe(pos.default);
          }
        }
      });
    });
  }
});
