// Thin retry-aware wrapper over `@notionhq/client`. The adapter boundary is
// the only place we validate payloads against the shapes defined in
// ./schemas.ts — callers (and the converter) can stay honest about what they
// send to the Notion API without hauling the SDK's full generic surface
// through every layer.

import { Client } from "@notionhq/client";
import {
  type CreatePageInput,
  CreatePageInputSchema,
  type NotionBlock,
  NotionBlockSchema,
  type NotionPageRef,
  NotionPageRefSchema,
} from "./schemas.js";

const DEFAULT_MAX_RETRIES = 5;
const BASE_BACKOFF_MS = 500;
const JITTER_MS = 250;
const RATE_LIMITED_STATUS = 429;

// Structural subset of the SDK's Client we actually call. Letting the adapter
// accept any object with this shape keeps tests honest (no module mocking,
// no globalThis patching) while staying compatible with the real Client.
export interface NotionClientLike {
  pages: {
    create: (args: Record<string, unknown>) => Promise<unknown>;
    update: (args: Record<string, unknown>) => Promise<unknown>;
  };
  blocks: {
    children: {
      append: (args: Record<string, unknown>) => Promise<unknown>;
    };
  };
}

export interface CreateNotionClientOptions {
  token: string;
  maxRetries?: number;
  client?: NotionClientLike;
}

export interface NotionAdapter {
  createPage: (input: CreatePageInput) => Promise<NotionPageRef>;
  appendBlocks: (pageId: string, blocks: NotionBlock[]) => Promise<void>;
  updatePageTitle: (pageId: string, title: string) => Promise<void>;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function isRateLimited(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "status" in err &&
    (err as { status: unknown }).status === RATE_LIMITED_STATUS
  );
}

function backoffDelay(attempt: number): number {
  return BASE_BACKOFF_MS * 2 ** attempt + Math.random() * JITTER_MS;
}

async function withRetry<T>(call: () => Promise<T>, maxRetries: number): Promise<T> {
  let attempt = 0;
  // Total attempts = 1 initial + maxRetries retries.
  while (true) {
    try {
      return await call();
    } catch (err) {
      if (!isRateLimited(err) || attempt >= maxRetries) {
        throw err;
      }
      await sleep(backoffDelay(attempt));
      attempt += 1;
    }
  }
}

function titleProperty(title: string): Record<string, unknown> {
  return {
    title: { title: [{ type: "text", text: { content: title } }] },
  };
}

export function createNotionClient(options: CreateNotionClientOptions): NotionAdapter {
  const { token, maxRetries = DEFAULT_MAX_RETRIES } = options;
  const sdk: NotionClientLike =
    options.client ?? (new Client({ auth: token }) as unknown as NotionClientLike);

  return {
    async createPage(input) {
      const { parent, title, blocks } = CreatePageInputSchema.parse(input);
      const response = await withRetry(
        () =>
          sdk.pages.create({
            parent: { type: "page_id", page_id: parent.id },
            properties: titleProperty(title),
            children: blocks,
          }),
        maxRetries,
      );
      return NotionPageRefSchema.parse(response);
    },

    async appendBlocks(pageId, blocks) {
      const validated = blocks.map((block) => NotionBlockSchema.parse(block));
      await withRetry(
        () =>
          sdk.blocks.children.append({
            block_id: pageId,
            children: validated,
          }),
        maxRetries,
      );
    },

    async updatePageTitle(pageId, title) {
      await withRetry(
        () =>
          sdk.pages.update({
            page_id: pageId,
            properties: titleProperty(title),
          }),
        maxRetries,
      );
    },
  };
}
