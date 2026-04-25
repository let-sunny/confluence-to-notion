import { defineConfig } from "tsup";

export default defineConfig([
  {
    entry: { cli: "src/cli.ts", mcp: "src/mcp/index.ts" },
    format: ["esm"],
    target: "node20",
    platform: "node",
    outDir: "dist",
    dts: true,
    clean: true,
    splitting: false,
    sourcemap: true,
    banner: { js: "#!/usr/bin/env node" },
  },
  {
    entry: { index: "src/index.ts" },
    format: ["esm"],
    target: "node20",
    platform: "node",
    outDir: "dist",
    dts: true,
    clean: false,
    splitting: false,
    sourcemap: true,
  },
]);
