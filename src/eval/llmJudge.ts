import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import { DiscoveryOutputSchema } from "../agentOutput/schemas.js";

const ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
/** Small, cost-effective model for batch eval; swap only via intentional ADR change. */
const JUDGE_MODEL = "claude-3-5-haiku-20241022";

const JudgeRowSchema = z.object({
  scores: z.record(z.number()),
  rationale: z.string().optional(),
});

const JudgeResponseSchema = z.array(JudgeRowSchema);

/**
 * LLM-as-judge pass (ADR-004). Uses the Anthropic Messages HTTP API (no SDK) to
 * keep the published CLI bundle small; requires `ANTHROPIC_API_KEY` when enabled.
 */
export async function runLlmJudgeIfConfigured(args: {
  outputDir: string;
  samplesDir: string;
}): Promise<unknown | null> {
  const key = process.env.ANTHROPIC_API_KEY?.trim();
  if (!key) return null;

  const patternsPath = join(args.outputDir, "patterns.json");
  const raw = await readFile(patternsPath, "utf8");
  const patterns = DiscoveryOutputSchema.parse(JSON.parse(raw) as unknown);

  const prompt = [
    "You evaluate discovery output for a Confluence → Notion migration pipeline.",
    "Return ONLY a JSON array (no markdown fences) with 1 to 3 objects of this exact shape:",
    '{"scores":{"relevance":0,"specificity":0,"actionability":0},"rationale":"short text"}',
    "Each score must be a number from 0 (worst) to 1 (best), judging whether patterns are specific and actionable for engineers.",
    "",
    `Pattern count: ${String(patterns.patterns.length)}`,
    `First patterns (truncated JSON): ${JSON.stringify(patterns.patterns.slice(0, 8)).slice(0, 12_000)}`,
    `Sample XHTML directory (for context only): ${args.samplesDir}`,
  ].join("\n");

  const res = await fetch(ANTHROPIC_MESSAGES_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": key,
      "anthropic-version": ANTHROPIC_VERSION,
    },
    body: JSON.stringify({
      model: JUDGE_MODEL,
      max_tokens: 2048,
      messages: [{ role: "user", content: prompt }],
    }),
  });

  const responseText = await res.text();
  if (!res.ok) {
    throw new Error(`Anthropic API error: ${String(res.status)} ${responseText.slice(0, 500)}`);
  }

  const body = JSON.parse(responseText) as {
    content?: Array<{ type: string; text?: string }>;
  };
  const textBlock = body.content?.find((c) => c.type === "text")?.text?.trim() ?? "";
  const parsed = extractJsonArray(textBlock);
  const safe = JudgeResponseSchema.safeParse(parsed);
  if (!safe.success) {
    return [
      {
        scores: { parse_error: 0 },
        rationale: `Judge JSON did not match schema: ${safe.error.message}`,
      },
    ];
  }
  return safe.data;
}

function extractJsonArray(text: string): unknown {
  const fence = /^```(?:json)?\s*([\s\S]*?)```$/m.exec(text);
  if (fence?.[1]) {
    try {
      return JSON.parse(fence[1].trim()) as unknown;
    } catch {
      /* fall through */
    }
  }
  const start = text.indexOf("[");
  const end = text.lastIndexOf("]");
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1)) as unknown;
    } catch {
      /* fall through */
    }
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return [];
  }
}
