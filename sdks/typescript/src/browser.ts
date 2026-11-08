/**
 * Browser SDK. Browsers can't keep secrets, so this client never sees rules: it sends the
 * user to the server, which evaluates and returns only values of flags marked client_side.
 * It then listens for "something changed" pings and re-evaluates.
 *
 * Same contract as the server SDK: nothing throws or rejects, and every read takes a default.
 */
import { EventProcessor, type AnalyticsEvent } from "./events.js";
import { Backoff, Emitter, HttpError, readStream, sleep, type FetchLike } from "./transport.js";
import { silentLogger, type EvaluationDetail, type JsonValue, type Logger, type User } from "./types.js";

export interface BrowserClientOptions {
  baseUrl?: string;
  stream?: boolean;
  sendEvents?: boolean;
  eventsFlushIntervalMs?: number;
  /** Values to show before the first response (e.g. rendered by your server). */
  bootstrap?: Record<string, EvaluationDetail>;
  logger?: Logger;
  fetch?: FetchLike;
  backoff?: () => number;
}

const READ_TIMEOUT_MS = 45_000;

export class BrowserFlagClient {
  private values: Record<string, EvaluationDetail>;
  private envVersion = -1;
  private user: User;
  private requestSeq = 0;
  private readyResolve!: () => void;
  private readonly ready = new Promise<void>((r) => (this.readyResolve = r));
  private initialized = false;
  private readonly closed = new AbortController();
  private readonly changes = new Emitter<string[]>();
  private readonly events?: EventProcessor;
  private readonly base: string;
  private readonly fetchFn: FetchLike;
  private readonly log: Logger;

  constructor(
    private readonly clientId: string,
    user: User,
    private readonly options: BrowserClientOptions = {},
  ) {
    this.user = user;
    this.values = { ...(options.bootstrap ?? {}) };
    this.base = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.log = options.logger ?? silentLogger;
    if (options.sendEvents !== false) {
      this.events = new EventProcessor(
        (batch) => this.postEvents(batch),
        options.eventsFlushIntervalMs ?? 5000,
        1000,
        (e) => this.log.warn("featureflags: dropped events", e),
      );
    }
    void this.refresh();
    if (options.stream !== false) void this.streamLoop();
  }

  /** Resolves true once values are loaded, false on timeout. Never rejects. */
  async waitForInitialization(timeoutMs = 5000): Promise<boolean> {
    if (this.initialized) return true;
    let t: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<boolean>((r) => (t = setTimeout(() => r(false), timeoutMs)));
    const ok = await Promise.race([this.ready.then(() => true), timeout]);
    clearTimeout(t);
    return ok;
  }

  isReady(): boolean {
    return this.initialized;
  }

  /** Switch user (e.g. after login). Resolves when the new values have arrived (or failed). */
  async identify(user: User): Promise<void> {
    this.user = user;
    await this.refresh();
  }

  bool(key: string, defaultValue: boolean): boolean {
    return this.read(key, defaultValue, (v) => typeof v === "boolean").value as boolean;
  }
  string(key: string, defaultValue: string): string {
    return this.read(key, defaultValue, (v) => typeof v === "string").value as string;
  }
  number(key: string, defaultValue: number): number {
    return this.read(key, defaultValue, (v) => typeof v === "number").value as number;
  }
  json<T extends JsonValue>(key: string, defaultValue: T): T {
    return this.read(key, defaultValue, () => true).value as T;
  }
  variationDetail<T extends JsonValue>(key: string, defaultValue: T): EvaluationDetail<T> {
    return this.read(key, defaultValue, () => true) as EvaluationDetail<T>;
  }
  allFlags(): Record<string, JsonValue> {
    return Object.fromEntries(Object.entries(this.values).map(([k, d]) => [k, d.value]));
  }

  track(metricKey: string, value: number | null = null): void {
    try {
      this.events?.custom(this.user.id, metricKey, value);
    } catch {
      /* never throw into the app */
    }
  }

  /** fn(changedKeys) after values change. Returns an unsubscribe function. */
  onChange(fn: (keys: string[]) => void): () => void {
    return this.changes.on(fn);
  }

  async flush(): Promise<void> {
    await this.events?.flush().catch(() => undefined);
  }

  async close(): Promise<void> {
    if (this.closed.signal.aborted) return;
    this.closed.abort();
    await this.events?.close().catch(() => undefined);
  }

  // ------------------------------------------------------------------------------

  private read(key: string, defaultValue: JsonValue, check: (v: unknown) => boolean): EvaluationDetail {
    try {
      const d = Object.prototype.hasOwnProperty.call(this.values, key) ? this.values[key] : undefined;
      if (!d) {
        const kind = this.initialized ? "FLAG_NOT_FOUND" : "CLIENT_NOT_READY";
        return { value: defaultValue, variation_index: null, reason: { kind: "ERROR", error_kind: kind } };
      }
      if (d.variation_index === null) return { ...d, value: defaultValue };
      if (!check(d.value)) {
        return { value: defaultValue, variation_index: null, reason: { kind: "ERROR", error_kind: "WRONG_TYPE" } };
      }
      if ("in_experiment" in d.reason && d.reason.in_experiment) {
        this.events?.exposure(this.user.id, key, d.variation_index);
      }
      return d;
    } catch {
      return { value: defaultValue, variation_index: null, reason: { kind: "ERROR", error_kind: "EXCEPTION" } };
    }
  }

  private async refresh(): Promise<void> {
    const seq = ++this.requestSeq;
    const user = this.user;
    try {
      const res = await this.fetchFn(`${this.base}/sdk/v1/evaluate`, {
        method: "POST",
        headers: { "X-Client-Id": this.clientId, "Content-Type": "application/json" },
        body: JSON.stringify({ user }),
        signal: this.closed.signal,
      });
      if (!res.ok) throw new HttpError(res.status);
      const body = await res.json();
      // A slower, older response (e.g. for the previous user) must not overwrite a newer one.
      if (seq !== this.requestSeq) return;
      const old = this.values;
      this.values = body.flags;
      this.envVersion = body.env_version;
      const changed = [...new Set([...Object.keys(old), ...Object.keys(body.flags)])].filter(
        (k) => JSON.stringify(old[k]?.value) !== JSON.stringify(body.flags[k]?.value),
      );
      if (!this.initialized) {
        this.initialized = true;
        this.readyResolve();
      }
      if (changed.length) this.changes.emit(changed, (e) => this.log.error("listener threw", e));
    } catch (e) {
      if (!this.closed.signal.aborted) this.log.warn("featureflags: evaluate failed; keeping last values", e);
    }
  }

  private async streamLoop(): Promise<void> {
    const backoff = new Backoff();
    while (!this.closed.signal.aborted) {
      try {
        await readStream(
          this.fetchFn, `${this.base}/sdk/v1/client-stream`, { "X-Client-Id": this.clientId },
          this.closed.signal, READ_TIMEOUT_MS,
          (m) => {
            if (m.event !== "change") return;
            backoff.reset();
            const { env_version } = JSON.parse(m.data);
            if (env_version !== this.envVersion) void this.refresh();
          },
        );
      } catch (e) {
        if (this.closed.signal.aborted) return;
        this.log.warn("featureflags: change stream error; keeping last values", e);
      }
      await sleep(this.options.backoff?.() ?? backoff.next(), this.closed.signal);
    }
  }

  private async postEvents(batch: AnalyticsEvent[]): Promise<void> {
    const res = await this.fetchFn(`${this.base}/sdk/v1/events`, {
      method: "POST",
      headers: { "X-Client-Id": this.clientId, "Content-Type": "application/json" },
      body: JSON.stringify({ events: batch }),
      keepalive: true,
    });
    if (!res.ok) throw new HttpError(res.status);
  }
}

export type { EvaluationDetail, JsonValue, User } from "./types.js";
