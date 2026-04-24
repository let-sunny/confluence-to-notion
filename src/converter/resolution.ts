// Port of `src/confluence_to_notion/converter/resolution.py` (see
// `git show 112afeb^:src/confluence_to_notion/converter/resolution.py`).
// The Python synchronous constructor doesn't translate cleanly to async fs,
// so this module exposes `ResolutionStore.open(path)` as the async initializer
// and keeps the rest of the API (lookup / add / keys / save) in sync with the
// Python reference. Field names use camelCase at the TS boundary, matching
// schemas.ts; the on-disk JSON therefore also uses camelCase (no aliases in
// the existing Zod schema).

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import {
  type ResolutionData,
  ResolutionDataSchema,
  type ResolutionEntry,
  ResolutionEntrySchema,
} from "./schemas.js";

export type ResolutionEntryInput = {
  resolvedBy: ResolutionEntry["resolvedBy"];
  value: Record<string, unknown>;
  confidence?: number;
};

export class ResolutionStore {
  private readonly path: string;
  data: ResolutionData;

  private constructor(path: string, data: ResolutionData) {
    this.path = path;
    this.data = data;
  }

  static async open(path: string): Promise<ResolutionStore> {
    const data = await ResolutionStore.load(path);
    return new ResolutionStore(path, data);
  }

  private static async load(path: string): Promise<ResolutionData> {
    let raw: string;
    try {
      raw = await readFile(path, "utf8");
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        return { entries: {} };
      }
      console.warn(`Failed to load ${path}, starting fresh`);
      return { entries: {} };
    }
    try {
      const json = JSON.parse(raw) as unknown;
      return ResolutionDataSchema.parse(json);
    } catch {
      console.warn(`Failed to load ${path}, starting fresh`);
      return { entries: {} };
    }
  }

  lookup(key: string): ResolutionEntry | undefined {
    return this.data.entries[key];
  }

  add(key: string, input: ResolutionEntryInput): void {
    const entry = ResolutionEntrySchema.parse({
      resolvedBy: input.resolvedBy,
      value: input.value,
      confidence: input.confidence,
    });
    this.data.entries[key] = entry;
  }

  keys(): string[] {
    return Object.keys(this.data.entries);
  }

  async save(): Promise<void> {
    const validated = ResolutionDataSchema.parse(this.data);
    await mkdir(dirname(this.path), { recursive: true });
    await writeFile(this.path, `${JSON.stringify(validated, null, 2)}\n`, "utf8");
  }
}
