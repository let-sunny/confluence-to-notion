/** Shared stub for subcommands that are not implemented yet (PR 4/5). */
export function notImplemented(sub: string): () => never {
  return () => {
    throw new Error(`not implemented: ${sub}`);
  };
}
