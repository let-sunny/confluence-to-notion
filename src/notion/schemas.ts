// Runtime validation at the @notionhq/client adapter boundary. The SDK owns
// the full TypeScript type tree; this file exists only to pin the shapes the
// converter emits today (paragraph, heading_1-3, bulleted_list_item) so a
// drift in the SDK does not silently propagate into create-page calls.

import { z } from "zod";

export const NotionPageRefSchema = z.object({
  id: z.string().min(1),
  url: z.string().optional(),
});
export type NotionPageRef = z.infer<typeof NotionPageRefSchema>;

const RichTextItemSchema = z
  .object({
    type: z.literal("text"),
    text: z.object({
      content: z.string(),
      link: z.object({ url: z.string() }).nullable().optional(),
    }),
  })
  .passthrough();

const RichTextPayloadSchema = z
  .object({
    rich_text: z.array(RichTextItemSchema),
  })
  .passthrough();

const ParagraphBlockSchema = z.object({
  type: z.literal("paragraph"),
  paragraph: RichTextPayloadSchema,
});
const Heading1BlockSchema = z.object({
  type: z.literal("heading_1"),
  heading_1: RichTextPayloadSchema,
});
const Heading2BlockSchema = z.object({
  type: z.literal("heading_2"),
  heading_2: RichTextPayloadSchema,
});
const Heading3BlockSchema = z.object({
  type: z.literal("heading_3"),
  heading_3: RichTextPayloadSchema,
});
const BulletedListItemBlockSchema = z.object({
  type: z.literal("bulleted_list_item"),
  bulleted_list_item: RichTextPayloadSchema,
});

export const NotionBlockSchema = z.discriminatedUnion("type", [
  ParagraphBlockSchema,
  Heading1BlockSchema,
  Heading2BlockSchema,
  Heading3BlockSchema,
  BulletedListItemBlockSchema,
]);
export type NotionBlock = z.infer<typeof NotionBlockSchema>;

export const CreatePageInputSchema = z.object({
  parent: NotionPageRefSchema,
  title: z.string().min(1),
  blocks: z.array(NotionBlockSchema),
});
export type CreatePageInput = z.infer<typeof CreatePageInputSchema>;
