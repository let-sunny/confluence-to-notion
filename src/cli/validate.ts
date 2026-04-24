import { readFile } from "node:fs/promises";
import type { Command } from "commander";
import {
  type AgentOutputSchemaName,
  AgentOutputSchemaNameSchema,
  parseAgentOutput,
} from "../agentOutput/schemas.js";

export async function validateOutputFile(
  filePath: string,
  schemaName: AgentOutputSchemaName,
): Promise<void> {
  let rawText: string;
  try {
    rawText = await readFile(filePath, "utf8");
  } catch (e) {
    throw new Error(`Cannot read file: ${filePath}: ${String(e)}`);
  }
  let json: unknown;
  try {
    json = JSON.parse(rawText) as unknown;
  } catch (e) {
    throw new SyntaxError(`Invalid JSON in ${filePath}: ${String(e)}`);
  }
  parseAgentOutput(schemaName, json);
}

function printZodError(err: unknown, filePath: string): void {
  if (
    err &&
    typeof err === "object" &&
    "issues" in err &&
    Array.isArray((err as { issues: unknown }).issues)
  ) {
    const zerr = err as { issues: Array<{ path: (string | number)[]; message: string }> };
    for (const issue of zerr.issues) {
      const path = issue.path.length > 0 ? issue.path.join(".") : "(root)";
      process.stderr.write(`${filePath}: ${path}: ${issue.message}\n`);
    }
    return;
  }
  process.stderr.write(`${filePath}: ${String(err)}\n`);
}

export function registerValidateCommands(program: Command): void {
  program
    .command("validate-output")
    .description("Validate an agent output file against its schema.")
    .argument("<file>", "JSON file to validate")
    .argument("<schema>", "schema name: discovery | proposer | scout")
    .action(async (file: string, schema: string) => {
      const parsed = AgentOutputSchemaNameSchema.safeParse(schema);
      if (!parsed.success) {
        process.stderr.write(
          `Invalid schema name "${schema}". Use discovery, proposer, or scout.\n`,
        );
        process.exit(1);
      }
      try {
        await validateOutputFile(file, parsed.data);
      } catch (e) {
        printZodError(e, file);
        process.exit(1);
      }
    });
}
