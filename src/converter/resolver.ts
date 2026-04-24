// Port of `src/confluence_to_notion/converter/resolver.py` (see
// `git show 112afeb^:src/confluence_to_notion/converter/resolver.py`).
// The Python Protocol / Pydantic report become a structural TS interface and
// a plain type here. `ResolverLike` is exported separately so the converter
// slice (PR 2b-iii) can stub a resolver without pulling in the class.

import type { ResolutionStore } from "./resolution.js";
import type { ResolutionEntry, UnresolvedItem } from "./schemas.js";

export interface ResolveStrategy {
  tryResolve(item: UnresolvedItem): Promise<ResolutionEntry | null>;
}

export type ResolveReport = {
  resolvedCount: number;
  fromStore: number;
  newlyResolved: number;
  stillUnresolved: UnresolvedItem[];
};

export interface ResolverLike {
  resolve(items: UnresolvedItem[]): Promise<ResolveReport>;
}

export class Resolver implements ResolverLike {
  private readonly store: ResolutionStore;
  private readonly strategies: ResolveStrategy[];

  constructor(store: ResolutionStore, strategies?: ResolveStrategy[]) {
    this.store = store;
    this.strategies = strategies ?? [];
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

      const existing = this.store.lookup(key);
      if (existing !== undefined) {
        report.resolvedCount += 1;
        report.fromStore += 1;
        console.debug(`Store hit: ${key}`);
        continue;
      }

      const entry = await this.tryStrategies(item);
      if (entry !== null) {
        this.store.add(key, {
          resolvedBy: entry.resolvedBy,
          value: entry.value,
          ...(entry.confidence !== undefined ? { confidence: entry.confidence } : {}),
        });
        report.resolvedCount += 1;
        report.newlyResolved += 1;
        console.info(`Resolved: ${key} via ${entry.resolvedBy}`);
      } else {
        report.stillUnresolved.push(item);
        console.info(`Unresolved: ${key}`);
      }
    }

    if (report.newlyResolved > 0) {
      await this.store.save();
    }

    return report;
  }

  private async tryStrategies(item: UnresolvedItem): Promise<ResolutionEntry | null> {
    for (const strategy of this.strategies) {
      const entry = await strategy.tryResolve(item);
      if (entry !== null) return entry;
    }
    return null;
  }
}
