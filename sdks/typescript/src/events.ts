/** Event batching. Never blocks the caller: a full buffer drops events. */

export interface ExposureEvent {
  kind: "exposure";
  user_id: string;
  flag_key: string;
  variation_index: number;
  timestamp: number;
}

export interface CustomEvent {
  kind: "custom";
  user_id: string;
  metric_key: string;
  value: number | null;
  timestamp: number;
}

export type AnalyticsEvent = ExposureEvent | CustomEvent;

const DEDUPE_LIMIT = 10_000;
const MAX_BATCH = 500;

export class EventProcessor {
  private buffer: AnalyticsEvent[] = [];
  private seen = new Set<string>();
  private timer: ReturnType<typeof setInterval>;
  private flushing: Promise<void> = Promise.resolve();
  dropped = 0;

  constructor(
    private send: (batch: AnalyticsEvent[]) => Promise<void>,
    flushIntervalMs: number,
    private capacity: number,
    private onError: (e: unknown) => void,
  ) {
    this.timer = setInterval(() => void this.flush(), flushIntervalMs);
    (this.timer as { unref?: () => void }).unref?.();
  }

  private push(e: AnalyticsEvent): void {
    if (this.buffer.length >= this.capacity) {
      this.dropped++;
      return;
    }
    this.buffer.push(e);
  }

  exposure(userId: string, flagKey: string, variationIndex: number): void {
    const key = `${userId}\u0000${flagKey}\u0000${variationIndex}`;
    if (this.seen.has(key)) return;
    if (this.seen.size >= DEDUPE_LIMIT) this.seen.clear();
    this.seen.add(key);
    this.push({ kind: "exposure", user_id: userId, flag_key: flagKey,
      variation_index: variationIndex, timestamp: Date.now() });
  }

  custom(userId: string, metricKey: string, value: number | null): void {
    this.push({ kind: "custom", user_id: userId, metric_key: metricKey, value,
      timestamp: Date.now() });
  }

  flush(): Promise<void> {
    this.flushing = this.flushing.then(async () => {
      while (this.buffer.length) {
        const batch = this.buffer.splice(0, MAX_BATCH);
        try {
          await this.send(batch);
        } catch (e) {
          this.onError(e); // analytics are best-effort
        }
      }
    });
    return this.flushing;
  }

  async close(): Promise<void> {
    clearInterval(this.timer);
    await this.flush();
  }
}
