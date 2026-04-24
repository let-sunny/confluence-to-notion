// Deterministic resolver fixture used by converter unit tests (PR 2b-iii) and
// the upcoming 2c equivalence tests. Mirrors the Python test resolver
// behaviour: every UnresolvedItem of every supported kind maps to a stable
// `notion.so/placeholder/<identifier>` URL via a pure in-memory lookup. No
// I/O, no clock, no randomness.

import type { ResolveReport, ResolverLike } from "../../src/converter/resolver.js";
import type { ResolutionEntry, UnresolvedItem } from "../../src/converter/schemas.js";

function placeholderEntry(item: UnresolvedItem): ResolutionEntry {
  const url = `https://notion.so/placeholder/${item.identifier}`;
  const value: Record<string, unknown> = { url };
  switch (item.kind) {
    case "page_link":
      value.notion_page_id = item.identifier;
      break;
    case "synced_block":
      value.original_block_id = item.identifier;
      break;
    case "table":
      value.database_id = item.identifier;
      break;
    case "jira_server":
      value.issue_url = url;
      break;
    case "macro":
      value.notion_blocks = [];
      break;
  }
  return {
    resolvedBy: "auto_lookup",
    value,
    resolvedAt: new Date(0),
  };
}

export class MockResolver implements ResolverLike {
  private readonly entries = new Map<string, ResolutionEntry>();

  lookup(key: string): ResolutionEntry | undefined {
    return this.entries.get(key);
  }

  async resolve(items: UnresolvedItem[]): Promise<ResolveReport> {
    const report: ResolveReport = {
      resolvedCount: 0,
      fromStore: 0,
      newlyResolved: 0,
      stillUnresolved: [],
    };
    const seen = new Set<string>();
    for (const item of items) {
      const key = `${item.kind}:${item.identifier}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (this.entries.has(key)) {
        report.resolvedCount += 1;
        report.fromStore += 1;
        continue;
      }
      this.entries.set(key, placeholderEntry(item));
      report.resolvedCount += 1;
      report.newlyResolved += 1;
    }
    return report;
  }
}

export function createMockResolver(): MockResolver {
  return new MockResolver();
}
