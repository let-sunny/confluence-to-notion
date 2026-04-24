// Runtime validation at the Confluence REST adapter boundary. Only the fields
// the adapter and converter actually consume are pinned here; everything else
// passes through so Confluence's habit of adding fields to stable endpoints
// (`_expandable`, `extensions`, etc.) never breaks a migration run.

import { z } from "zod";

export const ConfluencePageSchema = z
  .object({
    id: z.string().min(1),
    title: z.string(),
    type: z.string(),
    space: z
      .object({
        key: z.string(),
        name: z.string(),
      })
      .passthrough(),
    body: z
      .object({
        storage: z
          .object({
            value: z.string(),
            representation: z.string(),
          })
          .passthrough(),
      })
      .passthrough(),
    version: z
      .object({
        number: z.number(),
      })
      .passthrough(),
  })
  .passthrough();
export type ConfluencePage = z.infer<typeof ConfluencePageSchema>;

export interface PageTreeNode {
  id: string;
  title: string;
  children: PageTreeNode[];
}

export const PageTreeNodeSchema: z.ZodType<PageTreeNode> = z.lazy(() =>
  z
    .object({
      id: z.string().min(1),
      title: z.string(),
      children: z.array(PageTreeNodeSchema),
    })
    .passthrough(),
);

// ConfluenceUserSchema and ConfluenceAttachmentSchema are exported for planned
// downstream consumers (attachment metadata + mention/resolver flows) and are
// not yet used by the adapter surface in this file.
export const ConfluenceUserSchema = z
  .object({
    accountId: z.string().min(1),
    displayName: z.string(),
    email: z.string(),
  })
  .passthrough();
export type ConfluenceUser = z.infer<typeof ConfluenceUserSchema>;

export const ConfluenceAttachmentSchema = z
  .object({
    id: z.string().min(1),
    title: z.string(),
    mediaType: z.string(),
    _links: z
      .object({
        download: z.string(),
      })
      .passthrough(),
  })
  .passthrough();
export type ConfluenceAttachment = z.infer<typeof ConfluenceAttachmentSchema>;
