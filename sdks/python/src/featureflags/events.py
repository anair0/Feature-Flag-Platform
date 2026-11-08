"""Background event batching. Never blocks the caller: a full buffer drops events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("featureflags")

DEDUPE_LIMIT = 10_000
MAX_BATCH = 500


class EventProcessor:
    def __init__(
        self,
        send: Callable[[list[dict]], None],
        flush_interval: float = 5.0,
        capacity: int = 10_000,
    ) -> None:
        self._send = send
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=capacity)
        self._flush_interval = flush_interval
        self._seen_exposures: set[tuple] = set()
        self._seen_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="featureflags-events", daemon=True)
        self._thread.start()

    def _enqueue(self, event: dict) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    def record_exposure(self, user_id: str, flag_key: str, variation_index: int) -> None:
        key = (user_id, flag_key, variation_index)
        with self._seen_lock:
            if key in self._seen_exposures:
                return
            if len(self._seen_exposures) >= DEDUPE_LIMIT:
                self._seen_exposures.clear()
            self._seen_exposures.add(key)
        self._enqueue(
            {
                "kind": "exposure",
                "user_id": user_id,
                "flag_key": flag_key,
                "variation_index": variation_index,
                "timestamp": int(time.time() * 1000),
            }
        )

    def record_custom(self, user_id: str, metric_key: str, value: Optional[float]) -> None:
        self._enqueue(
            {
                "kind": "custom",
                "user_id": user_id,
                "metric_key": metric_key,
                "value": value,
                "timestamp": int(time.time() * 1000),
            }
        )

    def flush(self) -> None:
        with self._send_lock:
            while True:
                batch: list[dict] = []
                while len(batch) < MAX_BATCH:
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                if not batch:
                    return
                try:
                    self._send(batch)
                except Exception as e:  # analytics are best-effort
                    log.warning("featureflags: dropped %d events: %s", len(batch), e)

    def _run(self) -> None:
        while not self._stop.wait(self._flush_interval):
            self.flush()

    def close(self) -> None:
        self._stop.set()
        self.flush()
