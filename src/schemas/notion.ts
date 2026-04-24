// Shared zod schemas for Notion block shapes. These pin the surface the
// converter may emit — rich_text-shaped containers, media blocks, tables,
// columns, links, child pages, and synced blocks — so drift in the
// @notionhq/client types surfaces at parse time instead of during a
// create-page call.
//
// Purely additive: src/notion/schemas.ts continues to own the adapter
// boundary for the blocks the converter currently emits.

import { z } from "zod";

const RichTextItemSchema = z
  .object({
    type: z.literal("text"),
    text: z.object({
      content: z.string(),
      link: z.object({ url: z.string() }).nullable().optional(),
    }),
  })
  .passthrough();
export type RichTextItem = z.infer<typeof RichTextItemSchema>;

const RichTextPayloadSchema = z
  .object({
    rich_text: z.array(RichTextItemSchema),
  })
  .passthrough();
export type RichTextPayload = z.infer<typeof RichTextPayloadSchema>;

export const ParagraphBlockSchema = z.object({
  type: z.literal("paragraph"),
  paragraph: RichTextPayloadSchema,
});
export const Heading1BlockSchema = z.object({
  type: z.literal("heading_1"),
  heading_1: RichTextPayloadSchema,
});
export const Heading2BlockSchema = z.object({
  type: z.literal("heading_2"),
  heading_2: RichTextPayloadSchema,
});
export const Heading3BlockSchema = z.object({
  type: z.literal("heading_3"),
  heading_3: RichTextPayloadSchema,
});
export const BulletedListItemBlockSchema = z.object({
  type: z.literal("bulleted_list_item"),
  bulleted_list_item: RichTextPayloadSchema,
});
export const NumberedListItemBlockSchema = z.object({
  type: z.literal("numbered_list_item"),
  numbered_list_item: RichTextPayloadSchema,
});
export const ToggleBlockSchema = z.object({
  type: z.literal("toggle"),
  toggle: RichTextPayloadSchema,
});
export const QuoteBlockSchema = z.object({
  type: z.literal("quote"),
  quote: RichTextPayloadSchema,
});

export const ToDoBlockSchema = z.object({
  type: z.literal("to_do"),
  to_do: z
    .object({
      rich_text: z.array(RichTextItemSchema),
      checked: z.boolean(),
    })
    .passthrough(),
});

export const CodeBlockSchema = z.object({
  type: z.literal("code"),
  code: z
    .object({
      rich_text: z.array(RichTextItemSchema),
      language: z.string(),
    })
    .passthrough(),
});

export const CalloutBlockSchema = z.object({
  type: z.literal("callout"),
  callout: z
    .object({
      rich_text: z.array(RichTextItemSchema),
    })
    .passthrough(),
});

const ExternalFileSchema = z
  .object({
    type: z.literal("external"),
    external: z.object({ url: z.string() }).passthrough(),
  })
  .passthrough();

const HostedFileSchema = z
  .object({
    type: z.literal("file"),
    file: z.object({ url: z.string(), expiry_time: z.string().optional() }).passthrough(),
  })
  .passthrough();

const FilePayloadSchema = z.discriminatedUnion("type", [ExternalFileSchema, HostedFileSchema]);

export const ImageBlockSchema = z.object({
  type: z.literal("image"),
  image: FilePayloadSchema,
});
export const VideoBlockSchema = z.object({
  type: z.literal("video"),
  video: FilePayloadSchema,
});
export const FileBlockSchema = z.object({
  type: z.literal("file"),
  file: FilePayloadSchema,
});

export const DividerBlockSchema = z.object({
  type: z.literal("divider"),
  divider: z.object({}).passthrough(),
});

export const TableBlockSchema = z.object({
  type: z.literal("table"),
  table: z
    .object({
      table_width: z.number().int().nonnegative(),
      has_column_header: z.boolean(),
      has_row_header: z.boolean(),
    })
    .passthrough(),
});

export const TableRowBlockSchema = z.object({
  type: z.literal("table_row"),
  table_row: z
    .object({
      cells: z.array(z.array(RichTextItemSchema)),
    })
    .passthrough(),
});

export const ColumnListBlockSchema = z.object({
  type: z.literal("column_list"),
  column_list: z.object({}).passthrough(),
});

export const ColumnBlockSchema = z.object({
  type: z.literal("column"),
  column: z.object({}).passthrough(),
});

const LinkPayloadSchema = z
  .object({
    url: z.string(),
    caption: z.array(RichTextItemSchema).optional(),
  })
  .passthrough();

export const BookmarkBlockSchema = z.object({
  type: z.literal("bookmark"),
  bookmark: LinkPayloadSchema,
});
export const EmbedBlockSchema = z.object({
  type: z.literal("embed"),
  embed: LinkPayloadSchema,
});
export const LinkPreviewBlockSchema = z.object({
  type: z.literal("link_preview"),
  link_preview: LinkPayloadSchema,
});

export const ChildPageBlockSchema = z.object({
  type: z.literal("child_page"),
  child_page: z.object({ title: z.string() }).passthrough(),
});

export const SyncedBlockSchema = z.object({
  type: z.literal("synced_block"),
  synced_block: z
    .object({
      synced_from: z
        .object({
          type: z.literal("block_id"),
          block_id: z.string().min(1),
        })
        .passthrough()
        .nullable(),
    })
    .passthrough(),
});

export const NotionBlockSchema = z.discriminatedUnion("type", [
  ParagraphBlockSchema,
  Heading1BlockSchema,
  Heading2BlockSchema,
  Heading3BlockSchema,
  BulletedListItemBlockSchema,
  NumberedListItemBlockSchema,
  ToDoBlockSchema,
  ToggleBlockSchema,
  CodeBlockSchema,
  QuoteBlockSchema,
  CalloutBlockSchema,
  ImageBlockSchema,
  VideoBlockSchema,
  FileBlockSchema,
  DividerBlockSchema,
  TableBlockSchema,
  TableRowBlockSchema,
  ColumnListBlockSchema,
  ColumnBlockSchema,
  BookmarkBlockSchema,
  EmbedBlockSchema,
  LinkPreviewBlockSchema,
  ChildPageBlockSchema,
  SyncedBlockSchema,
]);
export type NotionBlock = z.infer<typeof NotionBlockSchema>;

export { RichTextItemSchema, RichTextPayloadSchema };
