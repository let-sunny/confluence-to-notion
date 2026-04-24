import { describe, expect, it } from "vitest";
import pkg from "../package.json" with { type: "json" };
import { createProgram } from "../src/cli.js";

describe("c2n CLI skeleton", () => {
  it("exposes the version from package.json", () => {
    const program = createProgram();
    expect(program.version()).toBe(pkg.version);
  });

  it("registers the program as `c2n`", () => {
    const program = createProgram();
    expect(program.name()).toBe("c2n");
  });
});
