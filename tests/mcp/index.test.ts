import { describe, expect, it } from "vitest";

describe("c2n-mcp entry", () => {
  it("imports without side effects and exposes main()", async () => {
    const mod = await import("../../src/mcp/index.js");
    expect(typeof mod.main).toBe("function");
  });
});
