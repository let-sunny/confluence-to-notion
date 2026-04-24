// Custom vitest matcher for comparing Notion block structures. Registered
// globally through vitest.config.ts `test.setupFiles` so every test picks it
// up without an explicit import.
//
// Semantics:
//  - Deep clone both sides before comparison (avoid mutating subject).
//  - Recursively sort object keys so field ordering from parse5 / JSON
//    serialisation doesn't matter.
//  - Treat a missing `annotations` key on a rich_text item as equal to
//    `annotations: {}` — the Python reference elides the key when no flag is
//    set while some handlers return an empty dict, and either should compare
//    equal.
//  - On mismatch, emit a unified diff using vitest's `this.utils.diff`.

import { expect } from "vitest";

type Anyish = unknown;

function isPlainObject(value: Anyish): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalize(value: Anyish): Anyish {
  if (Array.isArray(value)) {
    return value.map(normalize);
  }
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    const keys = Object.keys(value).sort();
    for (const key of keys) {
      out[key] = normalize(value[key]);
    }
    if (value.type === "text" && !("annotations" in value)) {
      out.annotations = {};
    }
    return out;
  }
  return value;
}

expect.extend({
  toMatchNotionBlocks(received: unknown, expected: unknown) {
    const normReceived = normalize(received);
    const normExpected = normalize(expected);
    const pass = this.equals(normReceived, normExpected);
    if (pass) {
      return {
        pass: true,
        message: () =>
          `Expected blocks NOT to match Notion structure, but they did:\n${this.utils.stringify(normReceived)}`,
      };
    }
    const diff = this.utils.diff(normExpected, normReceived, { expand: false });
    return {
      pass: false,
      message: () =>
        `Notion blocks did not match.\n${diff ?? `expected ${this.utils.stringify(normExpected)} received ${this.utils.stringify(normReceived)}`}`,
    };
  },
});

declare module "vitest" {
  interface Assertion<T> {
    toMatchNotionBlocks(expected: unknown): T;
  }
  interface AsymmetricMatchersContaining {
    toMatchNotionBlocks(expected: unknown): unknown;
  }
}
