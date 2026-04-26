import { realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createProgram } from "./cli/index.js";

export { createProgram } from "./cli/index.js";

function realpathOrSelf(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return p;
  }
}

const entry = process.argv[1];
const isDirectInvocation =
  entry !== undefined &&
  realpathOrSelf(resolve(fileURLToPath(import.meta.url))) === realpathOrSelf(resolve(entry));

if (isDirectInvocation) {
  createProgram().parse(process.argv);
}
