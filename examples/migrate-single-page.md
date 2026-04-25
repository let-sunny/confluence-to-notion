# Migrate a single Confluence page to Notion

A short walkthrough for the simplest happy path: pick one Confluence page,
land it under a Notion parent page.

## 1. Install

```bash
npm i -g confluence-to-notion        # or: npx confluence-to-notion c2n --help
```

Requires Node 20 LTS or newer.

## 2. Set environment variables

The full table — required vs. optional, defaults — lives in
[`CONTRIBUTING.md` § 1](../CONTRIBUTING.md#1-development-environment-setup).
Two minimum-viable shapes:

**Public wiki** (e.g. `cwiki.apache.org`) — only the base URL is needed for
fetching. You still need a Notion token to write.

```bash
export CONFLUENCE_BASE_URL="https://cwiki.apache.org/confluence"
export NOTION_API_TOKEN="ntn_..."
export NOTION_ROOT_PAGE_ID="<notion-page-id>"
```

**Private Atlassian Cloud wiki** — add email + API token.

```bash
export CONFLUENCE_BASE_URL="https://your-org.atlassian.net/wiki"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="<atlassian-api-token>"
export NOTION_API_TOKEN="ntn_..."
export NOTION_ROOT_PAGE_ID="<notion-page-id>"
```

Never paste credentials into source files; load them from your shell or a
`.env` file that is git-ignored.

## 3. Verify the Notion integration

```bash
c2n notion-ping
```

If it fails, the token is wrong or the integration is not shared with the
parent page.

## 4. Migrate the page

`c2n migrate` takes the Confluence page URL (URL-dispatch form) and writes
the converted blocks to the Notion parent in `NOTION_ROOT_PAGE_ID` (or the
`--to` override).

```bash
c2n migrate "https://your-org.atlassian.net/wiki/spaces/DOC/pages/123456789/My+Page"
```

Add `--dry-run` to fetch + convert without writing to Notion — handy for a
first sanity check.

## 5. Inspect the result

Open the Notion parent page; the new child page appears at the top. Per-run
artifacts (source XHTML, converted JSON, report) land under
`output/runs/<slug>/` so you can re-inspect or re-run later.

## Next steps

- Whole subtree: `c2n migrate-tree-pages --root-id <id> --url <url>` —
  multi-pass migration including table rule discovery. See the
  [Quickstart in the README](../README.md#quickstart).
- Empty hierarchy first: `c2n migrate-tree` creates the Notion page tree
  without uploading bodies.
- Full command surface: [ADR-00M](../.claude/docs/ADR-00M-cli-surface-freeze.md).
