import * as readline from "node:readline/promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { promptField } from "../../src/cli/promptInput.js";

vi.mock("node:readline/promises", () => ({
  createInterface: vi.fn(),
}));

interface ScriptedReadline {
  question: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
}

function scriptReadline(answer: string): ScriptedReadline {
  const close = vi.fn();
  const question = vi.fn(async () => answer);
  vi.mocked(readline.createInterface).mockReturnValue({
    question,
    close,
  } as unknown as ReturnType<typeof readline.createInterface>);
  return { question, close };
}

interface StdinSnapshot {
  isTTY: boolean | undefined;
  setRawMode: ((mode: boolean) => unknown) | undefined;
}

function snapshotStdin(): StdinSnapshot {
  const stdin = process.stdin as unknown as {
    isTTY: boolean | undefined;
    setRawMode?: (mode: boolean) => unknown;
  };
  return { isTTY: stdin.isTTY, setRawMode: stdin.setRawMode };
}

function restoreStdin(snap: StdinSnapshot): void {
  Object.defineProperty(process.stdin, "isTTY", {
    configurable: true,
    value: snap.isTTY,
  });
  const stdin = process.stdin as unknown as {
    setRawMode: ((mode: boolean) => unknown) | undefined;
  };
  stdin.setRawMode = snap.setRawMode;
}

interface SecretDriver {
  setRawMode: ReturnType<typeof vi.fn>;
}

function driveSecretAnswers(answers: Buffer[]): SecretDriver {
  const remaining = [...answers];
  const setRawMode = vi.fn((mode: boolean) => {
    if (mode === true) {
      const next = remaining.shift();
      if (next === undefined) return;
      setImmediate(() => {
        process.stdin.emit("data", next);
      });
    }
  });
  return { setRawMode };
}

let stdinSnap: StdinSnapshot;

beforeEach(() => {
  stdinSnap = snapshotStdin();
});

afterEach(() => {
  restoreStdin(stdinSnap);
  vi.restoreAllMocks();
});

describe("promptField (non-secret)", () => {
  it("prints the label and returns the trimmed answer", async () => {
    const { question, close } = scriptReadline("  hello-value  ");
    const result = await promptField({ prompt: "Email", secret: false });
    expect(result).toBe("hello-value");
    expect(question).toHaveBeenCalledTimes(1);
    expect(question.mock.calls[0]?.[0]).toBe("Email: ");
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("defaults secret to false when omitted", async () => {
    const { question } = scriptReadline("plain");
    const result = await promptField({ prompt: "Name" });
    expect(result).toBe("plain");
    expect(question).toHaveBeenCalledTimes(1);
  });

  it("throws on whitespace-only answer and still closes the readline", async () => {
    const { close } = scriptReadline("   ");
    await expect(promptField({ prompt: "Email", secret: false })).rejects.toThrow(/empty/i);
    expect(close).toHaveBeenCalledTimes(1);
  });
});

describe("promptField (secret on TTY)", () => {
  it("writes the prompt label but never echoes typed characters", async () => {
    const writes: string[] = [];
    vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
      writes.push(typeof chunk === "string" ? chunk : Buffer.from(chunk as Buffer).toString());
      return true;
    }) as typeof process.stdout.write);

    const driver = driveSecretAnswers([Buffer.from("super-secret-token\r")]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const result = await promptField({ prompt: "API token", secret: true });
    expect(result).toBe("super-secret-token");

    const captured = writes.join("");
    expect(captured).toContain("API token:");
    expect(captured).not.toContain("super-secret-token");
  });

  it("trims surrounding whitespace from the captured value", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const driver = driveSecretAnswers([Buffer.from("  trimmed  \r")]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const result = await promptField({ prompt: "API token", secret: true });
    expect(result).toBe("trimmed");
  });

  it("supports backspace to delete the last buffered character", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    // Type "abcX", backspace (0x7f), then Enter — final value should be "abc".
    const driver = driveSecretAnswers([Buffer.from([0x61, 0x62, 0x63, 0x58, 0x7f, 0x0d])]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const result = await promptField({ prompt: "API token", secret: true });
    expect(result).toBe("abc");
  });

  it("treats LF as end-of-line just like CR", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const driver = driveSecretAnswers([Buffer.from("lf-value\n")]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const result = await promptField({ prompt: "API token", secret: true });
    expect(result).toBe("lf-value");
  });

  it("rejects on Ctrl-C with an Aborted error and still cleans up", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const driver = driveSecretAnswers([Buffer.from([0x03])]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const before = process.stdin.listenerCount("data");
    await expect(promptField({ prompt: "API token", secret: true })).rejects.toThrow(/abort/i);
    expect(process.stdin.listenerCount("data")).toBe(before);
    // Last setRawMode call restores prior mode (false in tests).
    expect(driver.setRawMode).toHaveBeenLastCalledWith(false);
  });

  it("throws on empty input (Enter only) and restores raw mode", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const driver = driveSecretAnswers([Buffer.from([0x0d])]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    await expect(promptField({ prompt: "API token", secret: true })).rejects.toThrow(/empty/i);
    expect(driver.setRawMode).toHaveBeenLastCalledWith(false);
  });

  it("removes its data listener after a successful read (no leaked listeners)", async () => {
    vi.spyOn(process.stdout, "write").mockImplementation(
      (() => true) as typeof process.stdout.write,
    );
    const driver = driveSecretAnswers([Buffer.from("ok\r")]);
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    (process.stdin as unknown as { setRawMode: typeof driver.setRawMode }).setRawMode =
      driver.setRawMode;

    const before = process.stdin.listenerCount("data");
    const result = await promptField({ prompt: "API token", secret: true });
    expect(result).toBe("ok");
    expect(process.stdin.listenerCount("data")).toBe(before);
  });
});
