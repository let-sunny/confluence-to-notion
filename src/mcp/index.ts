// c2n-mcp bin entry: connect createServer() to stdio with graceful shutdown.

import { realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createServer } from "./server.js";

function realpathOrSelf(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return p;
  }
}

export async function main(): Promise<void> {
  const server = createServer();
  const transport = new StdioServerTransport();

  let shuttingDown = false;
  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    process.stderr.write(`c2n-mcp: received ${signal}, closing transport\n`);
    try {
      await server.close();
    } finally {
      process.exit(0);
    }
  };

  process.on("SIGINT", () => {
    void shutdown("SIGINT");
  });
  process.on("SIGTERM", () => {
    void shutdown("SIGTERM");
  });

  await server.connect(transport);
}

const invokedDirectly =
  typeof process.argv[1] === "string" &&
  realpathOrSelf(resolve(fileURLToPath(import.meta.url))) ===
    realpathOrSelf(resolve(process.argv[1]));
if (invokedDirectly) {
  main().catch((error: unknown) => {
    const message = error instanceof Error ? (error.stack ?? error.message) : String(error);
    process.stderr.write(`c2n-mcp: fatal: ${message}\n`);
    process.exit(1);
  });
}
