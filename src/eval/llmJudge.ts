/**
 * LLM-as-judge pass (ADR-004 signal-only). Full Anthropic integration is deferred;
 * the harness leaves `llm_judge` null unless a future commit wires `@anthropic-ai/sdk`.
 */
export async function runLlmJudgeIfConfigured(_args: {
  outputDir: string;
  samplesDir: string;
}): Promise<unknown | null> {
  if (!process.env.ANTHROPIC_API_KEY?.trim()) {
    return null;
  }
  return null;
}
