import { z } from "zod";

const pageSchema = z.object({
  kind: z.literal("page"),
  spaceKey: z.string(),
  pageId: z.string(),
  title: z.string().optional(),
});

const displaySchema = z.object({
  kind: z.literal("display"),
  spaceKey: z.string(),
  title: z.string(),
});

const shortlinkSchema = z.object({
  kind: z.literal("shortlink"),
  token: z.string(),
});

const pageIdSchema = z.object({
  kind: z.literal("pageId"),
  pageId: z.string(),
});

export const ParsedConfluenceUrlSchema = z.discriminatedUnion("kind", [
  pageSchema,
  displaySchema,
  shortlinkSchema,
  pageIdSchema,
]);

export type ParsedConfluenceUrl = z.infer<typeof ParsedConfluenceUrlSchema>;

const BARE_NUMERIC = /^\d+$/;

function unrecognised(input: string): never {
  throw new TypeError(`Unrecognised Confluence URL: ${input}`);
}

function splitPath(pathname: string): string[] {
  return pathname.split("/").filter((segment) => segment.length > 0);
}

function decodeTitle(raw: string): string {
  return decodeURIComponent(raw.replace(/\+/g, " "));
}

function matchDisplay(segments: string[]): ParsedConfluenceUrl | undefined {
  const index = segments.indexOf("display");
  if (index < 0) return undefined;
  const spaceKey = segments[index + 1];
  const rawTitle = segments[index + 2];
  if (spaceKey === undefined || rawTitle === undefined) return undefined;
  return {
    kind: "display",
    spaceKey,
    title: decodeTitle(rawTitle),
  };
}

function matchShortlink(segments: string[]): ParsedConfluenceUrl | undefined {
  const index = segments.indexOf("x");
  if (index < 0) return undefined;
  const token = segments[index + 1];
  if (token === undefined) return undefined;
  return { kind: "shortlink", token };
}

function matchSpacesPage(segments: string[]): ParsedConfluenceUrl | undefined {
  const spacesIndex = segments.indexOf("spaces");
  if (spacesIndex < 0) return undefined;
  const spaceKey = segments[spacesIndex + 1];
  if (spaceKey === undefined) return undefined;
  for (let i = spacesIndex + 2; i < segments.length - 1; i += 1) {
    if (segments[i] === "pages") {
      const pageId = segments[i + 1];
      if (pageId === undefined) return undefined;
      const title = segments[i + 2];
      if (title === undefined) {
        return { kind: "page", spaceKey, pageId };
      }
      return { kind: "page", spaceKey, pageId, title };
    }
  }
  return undefined;
}

export function parseConfluenceUrl(input: string): ParsedConfluenceUrl {
  if (typeof input !== "string" || input.length === 0) {
    unrecognised(input);
  }

  if (BARE_NUMERIC.test(input)) {
    return { kind: "pageId", pageId: input };
  }

  let parsed: URL;
  try {
    parsed = new URL(input);
  } catch {
    unrecognised(input);
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    unrecognised(input);
  }

  const segments = splitPath(parsed.pathname);

  return (
    matchSpacesPage(segments) ??
    matchDisplay(segments) ??
    matchShortlink(segments) ??
    unrecognised(input)
  );
}
