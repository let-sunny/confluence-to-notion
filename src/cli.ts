import { createProgram } from "./cli/index.js";

export { createProgram } from "./cli/index.js";

const isDirectInvocation =
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith("/dist/cli.js") === true;

if (isDirectInvocation) {
  createProgram().parse(process.argv);
}
