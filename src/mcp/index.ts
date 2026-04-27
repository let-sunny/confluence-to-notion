// c2n-mcp bin entry: connect createServer() to stdio with graceful shutdown.

import { realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import {
  ConfigStoreError,
  type ConfigStoreOptions,
  getConfluenceCreds,
  resolveProfileName,
} from "../configStore.js";
import {
  type ConfluenceAdapter,
  type FetchLike,
  createConfluenceClient,
} from "../confluence/client.js";
import { type CreateServerOptions, createServer } from "./server.js";

function realpathOrSelf(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return p;
  }
}

function resolveConfigDirOpts(): ConfigStoreOptions {
  const dir = process.env.C2N_CONFIG_DIR?.trim();
  return dir !== undefined && dir.length > 0 ? { configDir: dir } : {};
}

function asInvalidRequest(err: unknown): McpError {
  if (err instanceof ConfigStoreError) {
    return new McpError(
      ErrorCode.InvalidRequest,
      `${err.message}; set creds via \`c2n init\` or env vars`,
    );
  }
  if (err instanceof Error) {
    return new McpError(ErrorCode.InvalidRequest, err.message);
  }
  return new McpError(ErrorCode.InvalidRequest, String(err));
}

function buildConfluenceFactory(
  profile: string,
): (overrides?: { baseUrl?: string }) => ConfluenceAdapter {
  return (overrides) => {
    let creds: ReturnType<typeof getConfluenceCreds>;
    try {
      creds = getConfluenceCreds(profile, resolveConfigDirOpts());
    } catch (e) {
      throw asInvalidRequest(e);
    }
    const baseUrl = overrides?.baseUrl ?? creds.baseUrl;
    const trimmedBaseUrl = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
    const useGlobal = process.env.C2N_USE_GLOBAL_FETCH === "1";
    const g = globalThis as { fetch?: FetchLike };
    return createConfluenceClient({
      email: creds.email,
      token: creds.apiToken,
      baseUrl: trimmedBaseUrl,
      ...(useGlobal && typeof g.fetch === "function" ? { fetchImpl: g.fetch } : {}),
    });
  };
}

export function buildServerOptions(): CreateServerOptions {
  const profile = resolveProfileName(undefined, resolveConfigDirOpts());
  return {
    confluenceFactory: buildConfluenceFactory(profile),
  };
}

export async function main(): Promise<void> {
  const server = createServer(buildServerOptions());
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
