/** fetch-based Server-Sent Events, backoff, and a tiny event emitter. Runs in Node 18+ and browsers. */

export type FetchLike = typeof fetch;

export interface SseMessage {
  event: string;
  data: string;
}

/** Incremental SSE parser: feed it text chunks, get complete messages back. */
export class SseParser {
  private buffer = "";
  private event = "message";
  private data: string[] = [];

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    let nl: number;
    // Split on \n only, then strip \r: a "\r\n" split across two chunks stays one line break.
    while ((nl = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, nl).replace(/\r$/, "");
      this.buffer = this.buffer.slice(nl + 1);
      if (line === "") {
        if (this.data.length) out.push({ event: this.event, data: this.data.join("\n") });
        this.event = "message";
        this.data = [];
      } else if (line.startsWith(":")) {
        // comment / heartbeat
      } else {
        const i = line.indexOf(":");
        const name = i < 0 ? line : line.slice(0, i);
        let value = i < 0 ? "" : line.slice(i + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (name === "event") this.event = value;
        else if (name === "data") this.data.push(value);
      }
    }
    return out;
  }
}

export class HttpError extends Error {
  constructor(public status: number) {
    super(`HTTP ${status}`);
  }
}

/**
 * Open a stream and call onMessage for each event. Resolves when the stream ends; rejects on
 * error, or when no bytes (data or heartbeat) arrive for readTimeoutMs.
 */
export async function readStream(
  fetchFn: FetchLike,
  url: string,
  headers: Record<string, string>,
  signal: AbortSignal,
  readTimeoutMs: number,
  onMessage: (m: SseMessage) => void,
): Promise<void> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(abort, readTimeoutMs);
  };
  try {
    arm();
    const res = await fetchFn(url, {
      headers: { Accept: "text/event-stream", ...headers },
      signal: controller.signal,
    });
    if (!res.ok || !res.body) throw new HttpError(res.status);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      arm();
      for (const m of parser.feed(decoder.decode(value, { stream: true }))) onMessage(m);
    }
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
    controller.abort();
  }
}

/** Exponential backoff with ±50% jitter (spec/streaming.md rule 4). */
export class Backoff {
  private attempt = 0;
  constructor(
    private baseMs = 1000,
    private capMs = 30_000,
  ) {}
  next(): number {
    const delay = Math.min(this.capMs, this.baseMs * 2 ** this.attempt++);
    return delay * (0.5 + Math.random());
  }
  reset(): void {
    this.attempt = 0;
  }
}

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(done, ms);
    (t as { unref?: () => void }).unref?.();
    function done() {
      clearTimeout(t);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });
}

type Listener<T> = (arg: T) => void;

export class Emitter<T> {
  private listeners = new Set<Listener<T>>();
  on(fn: Listener<T>): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  emit(arg: T, onError: (e: unknown) => void): void {
    for (const fn of [...this.listeners]) {
      try {
        fn(arg);
      } catch (e) {
        onError(e); // a buggy listener must not break updates
      }
    }
  }
}
