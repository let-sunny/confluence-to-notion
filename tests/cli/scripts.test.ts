import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Command } from "commander";
import { describe, expect, it } from "vitest";
import { createProgram } from "../../src/cli/index.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const SCRIPTS_DIR = join(__dirname, "..", "..", "scripts");

interface Invocation {
  file: string;
  line: number;
  prefix: "pnpm exec" | "uv run" | "node ./dist/cli.js";
  argv: string[];
}

// Strip shell quoting while preserving token boundaries. Keeps `${VAR}`
// references intact so commander sees them as opaque strings.
function tokenize(input: string): string[] {
  const tokens: string[] = [];
  let curr = "";
  let i = 0;
  let inSingle = false;
  let inDouble = false;
  const flush = (): void => {
    if (curr !== "") {
      tokens.push(curr);
      curr = "";
    }
  };
  while (i < input.length) {
    const ch = input[i] ?? "";
    if (inSingle) {
      if (ch === "'") {
        inSingle = false;
      } else {
        curr += ch;
      }
      i++;
      continue;
    }
    if (inDouble) {
      if (ch === '"') {
        inDouble = false;
      } else if (ch === "\\" && i + 1 < input.length) {
        curr += input[i + 1];
        i++;
      } else {
        curr += ch;
      }
      i++;
      continue;
    }
    if (ch === "'") {
      inSingle = true;
      i++;
      continue;
    }
    if (ch === '"') {
      inDouble = true;
      i++;
      continue;
    }
    if (ch === "\\" && i + 1 < input.length) {
      curr += input[i + 1];
      i += 2;
      continue;
    }
    if (/\s/.test(ch)) {
      flush();
      i++;
      continue;
    }
    curr += ch;
    i++;
  }
  flush();
  return tokens;
}

// Join `\`-continued lines, strip simple heredoc contents, and emit the
// (lineNumber, logicalLine) pairs that survive.
function joinScriptLines(content: string): { line: number; text: string }[] {
  const lines = content.split("\n").map((l) => l.replace(/\r$/, ""));
  const out: { line: number; text: string }[] = [];
  let buffer = "";
  let bufferStart = 1;
  let heredocMarker: string | null = null;
  const heredocStartRe = /<<-?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)['"]?/;

  lines.forEach((raw, idx) => {
    const lineNo = idx + 1;
    if (heredocMarker !== null) {
      if (raw.trim() === heredocMarker) heredocMarker = null;
      return;
    }
    const hdStart = heredocStartRe.exec(raw);
    if (hdStart) {
      heredocMarker = hdStart[1] ?? null;
      // still push the start line itself (contains the `<<EOF` marker, not body)
      out.push({ line: lineNo, text: raw });
      return;
    }
    if (raw.endsWith("\\")) {
      if (buffer === "") bufferStart = lineNo;
      buffer += `${raw.slice(0, -1)} `;
      return;
    }
    if (buffer !== "") {
      out.push({ line: bufferStart, text: buffer + raw });
      buffer = "";
      return;
    }
    out.push({ line: lineNo, text: raw });
  });
  if (buffer !== "") out.push({ line: bufferStart, text: buffer });
  return out;
}

const INVOCATION_RE = /(pnpm exec|uv run|node \.\/dist\/cli\.js)\s+c2n(\s+.*)?$/;

function extractInvocations(file: string, content: string): Invocation[] {
  const invocations: Invocation[] = [];
  const logical = joinScriptLines(content);
  for (const { line, text } of logical) {
    const trimmed = text.trim();
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    // Skip lines where the c2n token is inside a printed string. This catches
    // `echo "... uv run c2n ..."` and `printf ...` guidance output.
    if (/^\s*(echo|printf)\s/.test(trimmed)) continue;

    const match = INVOCATION_RE.exec(trimmed);
    if (!match) continue;
    const prefix = match[1] as Invocation["prefix"];
    let rest = (match[2] ?? "").trim();
    rest = rest.replace(/;\s*then\s*$/, "");
    rest = rest.replace(/\s*;\s*$/, "");
    const argv = tokenize(rest);
    invocations.push({ file, line, prefix, argv });
  }
  return invocations;
}

function makeParseOnlyProgram(): Command {
  const program = createProgram();
  program.exitOverride();
  for (const cmd of program.commands) {
    cmd.exitOverride();
    // Replace the `throw new Error('not implemented')` action with a no-op so
    // parseAsync can complete without the stub firing.
    cmd.action(() => {});
  }
  return program;
}

function collectInvocations(): Invocation[] {
  const entries = readdirSync(SCRIPTS_DIR).filter((f) => f.endsWith(".sh"));
  const all: Invocation[] = [];
  for (const name of entries) {
    const path = join(SCRIPTS_DIR, name);
    const content = readFileSync(path, "utf8");
    all.push(...extractInvocations(name, content));
  }
  return all;
}

describe("scripts/*.sh c2n invocations", () => {
  const invocations = collectInvocations();

  it("finds at least one c2n invocation (scan sanity check)", () => {
    expect(invocations.length).toBeGreaterThan(0);
  });

  for (const inv of invocations) {
    const label = `${inv.file}:${inv.line} [${inv.prefix}] c2n ${inv.argv.join(" ")}`;

    it(`uses a TypeScript runtime (not uv run) — ${label}`, () => {
      expect(inv.prefix).not.toBe("uv run");
    });

    it(`parses against the frozen CLI surface — ${label}`, async () => {
      const program = makeParseOnlyProgram();
      await expect(program.parseAsync(inv.argv, { from: "user" })).resolves.not.toThrow();
    });
  }
});
