/**
 * Server-side SDK (Node). Same guarantees as the Python SDK:
 * - evaluation is local, synchronous and does no I/O;
 * - no public method throws or rejects; failures return the caller's default plus a reason;
 * - losing the server keeps the last known flags while reconnecting in the background.
 */
import { evaluate } from "./evaluation.js";
import { EventProcessor, type AnalyticsEvent } from "./events.js";
import { Backoff, Emitter, HttpError, readStream, sleep, type FetchLike } from "./transport.js";
import {
  silentLogger,
  type ErrorKind,
  type EvaluationDetail,
  type FlagConfig,
  type JsonValue,
  type Logger,
  type User,
} from "./types.js";

export interface FlagClientOptions {
  baseUrl?: string;
  /** Stream updates (default) or poll every pollIntervalMs. */
  stream?: boolean;
  pollIntervalMs?: number;
  sendEvents?: boolean;
  eventsFlushIntervalMs?: number;
  eventsCapacity?: number;
  /** No network at all; serve bootstrap data or defaults. */
  offline?: boolean;
  bootstrap?: { env_version: number; flags: Record<string, FlagConfig> };
  logger?: Logger;
  fetch?: FetchLike;
  /** For tests: override reconnect delay. */
  backoff?: () => number;
}

const READ_TIMEOUT_MS = 45_000;
const HEALTHY_AFTER_MS = 60_000;

const err = (kind: ErrorKind) => ({ kind: "ERROR" as const, error_kind: kind });

type Check = (v: unknown) => boolean;
const isBool: Check = (v) => typeof v === "boolean";
const isStr: Check = (v) => typeof v === "string";
const isNum: Check = (v) => typeof v === "number";
const any: Check = () => true;

export class FlagClient {
  private flags: Record<string, FlagConfig> = {};
  private envVersion = 0;
  private initialized = false;
  private readonly closed = new AbortController();
  private readonly changes = new Emitter<string>();
  private readyResolve!: () => void;
  private readonly ready = new Promise<void>((r) => (this.readyResolve = r));
  private readonly events?: EventProcessor;
  private readonly base: string;
  private readonly fetchFn: FetchLike;
  private readonly log: Logger;

  constructor(
    private readonly sdkKey: string,
    private readonly options: FlagClientOptions = {},
  ) {
    this.base = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.log = options.logger ?? silentLogger;
    if (options.bootstrap) this.replace(options.bootstrap.env_version, options.bootstrap.flags);
    if (options.offline) return;
    if (options.sendEvents !== false) {
      this.events = new EventProcessor(
        (batch) => this.postEvents(batch),
        options.eventsFlushIntervalMs ?? 5000,
        options.eventsCapacity ?? 10_000,
        (e) => this.log.warn("featureflags: dropped events", e),
      );
    }
    void (options.stream === false ? this.pollLoop() : this.streamLoop());
  }

  /** Create a client and wait (bounded) for the first flag data. Never rejects. */
  static async init(sdkKey: string, options: FlagClientOptions & { initTimeoutMs?: number } = {}) {
    const client = new FlagClient(sdkKey, options);
    await client.waitForInitialization(options.initTimeoutMs ?? 5000);
    return client;
  }

  /** Resolves true once flags are loaded, false on timeout. Never rejects. */
  async waitForInitialization(timeoutMs = 5000): Promise<boolean> {
    if (this.initialized) return true;
    let t: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<boolean>((r) => (t = setTimeout(() => r(false), timeoutMs)));
    const ok = await Promise.race([this.ready.then(() => true), timeout]);
    clearTimeout(t);
    if (!ok) this.log.warn(`featureflags: not initialized after ${timeoutMs}ms; serving defaults`);
    return ok;
  }

  isReady(): boolean {
    return this.initialized;
  }

  bool(key: string, user: User, defaultValue: boolean): boolean {
    return this.typed(key, user, defaultValue, isBool).value as boolean;
  }
  string(key: string, user: User, defaultValue: string): string {
    return this.typed(key, user, defaultValue, isStr).value as string;
  }
  number(key: string, user: User, defaultValue: number): number {
    return this.typed(key, user, defaultValue, isNum).value as number;
  }
  json<T extends JsonValue>(key: string, user: User, defaultValue: T): T {
    return this.typed(key, user, defaultValue, any).value as T;
  }
  variationDetail<T extends JsonValue>(key: string, user: User, defaultValue: T): EvaluationDetail<T> {
    return this.typed(key, user, defaultValue, any) as EvaluationDetail<T>;
  }

  allFlags(user: User): Record<string, JsonValue> {
    try {
      const out: Record<string, JsonValue> = {};
      for (const [k, f] of Object.entries(this.flags)) out[k] = evaluate(f, user).value;
      return out;
    } catch {
      return {};
    }
  }

  track(user: User, metricKey: string, value: number | null = null): void {
    try {
      if (user && typeof user.id === "string") this.events?.custom(user.id, metricKey, value);
    } catch (e) {
      this.log.error("featureflags: track failed", e);
    }
  }

  /** fn(flagKey) runs whenever a flag changes. Returns an unsubscribe function. */
  onChange(fn: (flagKey: string) => void): () => void {
    return this.changes.on(fn);
  }

  async flush(): Promise<void> {
    try {
      await this.events?.flush();
    } catch (e) {
      this.log.error("featureflags: flush failed", e);
    }
  }

  async close(): Promise<void> {
    if (this.closed.signal.aborted) return;
    this.closed.abort();
    try {
      await this.events?.close();
    } catch {
      /* best effort */
    }
  }

  get droppedEvents(): number {
    return this.events?.dropped ?? 0;
  }

  // ------------------------------------------------------------------ evaluation

  private typed(key: string, user: User, defaultValue: JsonValue, check: Check): EvaluationDetail {
    try {
      if (!this.initialized) return { value: defaultValue, variation_index: null, reason: err("CLIENT_NOT_READY") };
      const flag = Object.prototype.hasOwnProperty.call(this.flags, key) ? this.flags[key] : undefined;
      if (!flag) return { value: defaultValue, variation_index: null, reason: err("FLAG_NOT_FOUND") };
      const result = evaluate(flag, user);
      if (result.variation_index === null) return { ...result, value: defaultValue };
      if (!check(result.value)) return { value: defaultValue, variation_index: null, reason: err("WRONG_TYPE") };
      if ("in_experiment" in result.reason && result.reason.in_experiment) {
        this.events?.exposure(user.id, key, result.variation_index);
      }
      return result;
    } catch (e) {
      this.log.error(`featureflags: evaluation of ${key} failed`, e);
      return { value: defaultValue, variation_index: null, reason: err("EXCEPTION") };
    }
  }

  // --------------------------------------------------------------------- updates

  private replace(envVersion: number, flags: Record<string, FlagConfig>): void {
    const old = this.flags;
    this.flags = { ...flags };
    this.envVersion = envVersion;
    if (!this.initialized) {
      this.initialized = true;
      this.readyResolve();
    }
    for (const key of new Set([...Object.keys(old), ...Object.keys(flags)])) {
      if (JSON.stringify(old[key]) !== JSON.stringify(flags[key])) this.emitChange(key);
    }
  }

  private emitChange(key: string): void {
    this.changes.emit(key, (e) => this.log.error("featureflags: change listener threw", e));
  }

  private async fetchSnapshot(): Promise<void> {
    const res = await this.fetchFn(`${this.base}/sdk/v1/flags`, {
      headers: { Authorization: this.sdkKey, Accept: "application/json" },
      signal: this.closed.signal,
    });
    if (!res.ok) throw new HttpError(res.status);
    const body = await res.json();
    this.replace(body.env_version, body.flags);
  }

  private async handle(event: string, data: string): Promise<void> {
    if (event === "put") {
      const body = JSON.parse(data);
      this.replace(body.env_version, body.flags);
    } else if (event === "patch") {
      const { env_version, key, flag } = JSON.parse(data);
      if (!this.initialized || env_version > this.envVersion + 1) {
        this.log.warn("featureflags: missed an update, re-syncing");
        await this.fetchSnapshot();
      } else if (env_version === this.envVersion + 1) {
        const next = { ...this.flags };
        if (flag === null) delete next[key];
        else next[key] = flag;
        this.flags = next;
        this.envVersion = env_version;
        this.emitChange(key);
      } // else: stale or duplicate, ignore
    }
  }

  private async streamLoop(): Promise<void> {
    const backoff = new Backoff();
    while (!this.closed.signal.aborted) {
      const started = Date.now();
      let queue = Promise.resolve();
      try {
        await readStream(
          this.fetchFn, `${this.base}/sdk/v1/stream`, { Authorization: this.sdkKey },
          this.closed.signal, READ_TIMEOUT_MS,
          (m) => {
            // Process messages strictly in order, even when one needs a re-sync fetch.
            queue = queue.then(() => this.handle(m.event, m.data)).catch((e) =>
              this.log.warn("featureflags: failed to apply update", e));
            if (Date.now() - started > HEALTHY_AFTER_MS) backoff.reset();
          },
        );
        await queue;
      } catch (e) {
        if (this.closed.signal.aborted) return;
        this.log.warn("featureflags: stream error; keeping last known flags", e);
        if (e instanceof HttpError && (e.status === 401 || e.status === 403)) {
          this.log.error("featureflags: SDK key rejected; check your key");
        }
      }
      await sleep(this.options.backoff?.() ?? backoff.next(), this.closed.signal);
    }
  }

  private async pollLoop(): Promise<void> {
    while (!this.closed.signal.aborted) {
      try {
        await this.fetchSnapshot();
      } catch (e) {
        if (this.closed.signal.aborted) return;
        this.log.warn("featureflags: poll failed; keeping last known flags", e);
      }
      await sleep(this.options.pollIntervalMs ?? 30_000, this.closed.signal);
    }
  }

  private async postEvents(batch: AnalyticsEvent[]): Promise<void> {
    const res = await this.fetchFn(`${this.base}/sdk/v1/events`, {
      method: "POST",
      headers: { Authorization: this.sdkKey, "Content-Type": "application/json" },
      body: JSON.stringify({ events: batch }),
    });
    if (!res.ok) throw new HttpError(res.status);
  }
}
