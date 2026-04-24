// Shared zod schemas for Confluence REST shapes consumed by the converter.
// Mirrors the surface in src/confluence/schemas.ts but lives under
// src/schemas/* alongside the Notion shared schemas. Purely additive — the
// adapter boundary in src/confluence/schemas.ts is untouched.
//
// Confluence routinely augments stable endpoints with extra fields
// (`_expandable`, `extensions`, `_links`); every object schema below uses
// .passthrough() so a new field never breaks a migration run.

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
