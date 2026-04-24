import { join } from "node:path";
import type { AgentOutputSchemaName } from "../agentOutput/schemas.js";
import { validateOutputFile } from "../cli/validate.js";

const EVAL_AGENT_FILES: Array<[string, AgentOutputSchemaName]> = [
  ["patterns.json", "discovery"],
  ["proposals.json", "proposer"],
];

/**
 * Validates agent JSON artifacts under `outputDir` that the eval harness depends on.
 * Delegates to the same zod paths as `c2n validate-output` (single source of truth).
 */
export async function validateEvalAgentOutputs(outputDir: string): Promise<void> {
  for (const [name, schema] of EVAL_AGENT_FILES) {
    await validateOutputFile(join(outputDir, name), schema);
  }
}
