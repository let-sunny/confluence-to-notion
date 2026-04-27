import * as readline from "node:readline/promises";

export interface PromptFieldOptions {
  prompt: string;
  secret?: boolean;
}

const ETX = 0x03; // Ctrl-C
const BS = 0x08; // backspace
const LF = 0x0a;
const CR = 0x0d;
const DEL = 0x7f; // backspace on most terminals

export async function promptField(opts: PromptFieldOptions): Promise<string> {
  if (opts.secret === true) {
    return readSecretLine(opts.prompt);
  }
  return readPlainLine(opts.prompt);
}

async function readPlainLine(label: string): Promise<string> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await rl.question(`${label}: `)).trim();
    if (answer.length === 0) {
      throw new Error("Empty input");
    }
    return answer;
  } finally {
    rl.close();
  }
}

interface RawStdin {
  isRaw?: boolean;
  setRawMode?: (mode: boolean) => unknown;
  on(event: "data", listener: (chunk: Buffer) => void): unknown;
  off(event: "data", listener: (chunk: Buffer) => void): unknown;
  resume(): unknown;
  pause(): unknown;
}

async function readSecretLine(label: string): Promise<string> {
  const stdin = process.stdin as unknown as RawStdin;
  process.stdout.write(`${label}: `);

  const wasRaw = stdin.isRaw === true;
  stdin.setRawMode?.(true);
  stdin.resume();

  let onData: ((chunk: Buffer) => void) | null = null;
  try {
    const raw = await new Promise<string>((resolve, reject) => {
      let buffer = "";
      onData = (chunk: Buffer) => {
        for (const byte of chunk) {
          if (byte === ETX) {
            reject(new Error("Aborted by user"));
            return;
          }
          if (byte === CR || byte === LF) {
            resolve(buffer);
            return;
          }
          if (byte === DEL || byte === BS) {
            if (buffer.length > 0) buffer = buffer.slice(0, -1);
            continue;
          }
          buffer += String.fromCharCode(byte);
        }
      };
      stdin.on("data", onData);
    });
    process.stdout.write("\n");
    const trimmed = raw.trim();
    if (trimmed.length === 0) {
      throw new Error("Empty input");
    }
    return trimmed;
  } finally {
    if (onData) stdin.off("data", onData);
    stdin.setRawMode?.(wasRaw);
    stdin.pause();
  }
}
