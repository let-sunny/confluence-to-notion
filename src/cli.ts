import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createProgram } from "./cli/index.js";

export { createProgram } from "./cli/index.js";

const entry = process.argv[1];
const isDirectInvocation =
  entry !== undefined && resolve(fileURLToPath(import.meta.url)) === resolve(entry);

if (isDirectInvocation) {
  createProgram().parse(process.argv);
}
