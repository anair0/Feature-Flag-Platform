"""Server-side SDK client.

Guarantees (see spec/streaming.md and docs/design-decisions.md):
- Evaluation is local and does no I/O.
- No public method raises. Every failure returns the caller's default and a reason.
- Losing the server keeps the last known flags; the client reconnects in the background.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import evaluation
from .events import EventProcessor
from .store import APPLIED, GAP, FlagStore
from .transport import Backoff, open_stream, parse_sse, request_json

log = logging.getLogger("featureflags")

READ_TIMEOUT = 45.0
HEALTHY_AFTER = 60.0


@dataclass(frozen=True)
class EvaluationDetail:
    value: Any
    variation_index: Optional[int]
    reason: dict


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _any(v: Any) -> bool:
    return True


class FlagClient:
    def __init__(
        self,
        sdk_key: str,
        base_url: str = "http://localhost:8000",
        *,
        stream: bool = True,
        poll_interval: float = 30.0,
        init_timeout: float = 5.0,
        send_events: bool = True,
        events_flush_interval: float = 5.0,
        events_capacity: int = 10_000,
        offline: bool = False,
        bootstrap: Optional[dict] = None,
    ) -> None:
        self._sdk_key = sdk_key
        self._base = base_url.rstrip("/")
        self._stream_enabled = stream
        self._poll_interval = poll_interval
        self._store = FlagStore()
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._listeners: list[Callable[[str], None]] = []
        self._response = None
        self._events: Optional[EventProcessor] = None

        if bootstrap is not None:
            self._store.replace(bootstrap.get("env_version", 0), bootstrap.get("flags", {}))
            self._ready.set()
        if offline:
            return
        if send_events:
            self._events = EventProcessor(self._post_events, events_flush_interval, events_capacity)
        target = self._stream_loop if stream else self._poll_loop
        self._thread = threading.Thread(target=target, name="featureflags-updates", daemon=True)
        self._thread.start()
        if init_timeout > 0 and not self._ready.wait(init_timeout):
            log.warning("featureflags: not initialized after %.1fs; serving defaults", init_timeout)

    # ------------------------------------------------------------ public API

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        return self._ready.wait(timeout)

    def bool(self, key: str, user: dict, default: bool) -> bool:
        return self._typed(key, user, default, _is_bool).value

    def string(self, key: str, user: dict, default: str) -> str:
        return self._typed(key, user, default, _is_str).value

    def number(self, key: str, user: dict, default: float) -> float:
        return self._typed(key, user, default, _is_num).value

    def json(self, key: str, user: dict, default: Any) -> Any:
        return self._typed(key, user, default, _any).value

    def variation(self, key: str, user: dict, default: Any) -> Any:
        return self._typed(key, user, default, _any).value

    def variation_detail(self, key: str, user: dict, default: Any) -> EvaluationDetail:
        return self._typed(key, user, default, _any)

    def all_flags(self, user: dict) -> dict[str, Any]:
        try:
            return {k: evaluation.evaluate(f, user).value for k, f in self._store.all().items()}
        except Exception:
            return {}

    def track(self, user: dict, metric_key: str, value: Optional[float] = None) -> None:
        try:
            if self._events and isinstance(user, dict) and isinstance(user.get("id"), str):
                self._events.record_custom(user["id"], metric_key, value)
        except Exception:
            log.exception("featureflags: track failed")

    def add_listener(self, fn: Callable[[str], None]) -> None:
        """fn(flag_key) is called on the update thread whenever a flag changes."""
        self._listeners.append(fn)

    def flush(self) -> None:
        try:
            if self._events:
                self._events.flush()
        except Exception:
            log.exception("featureflags: flush failed")

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        _shutdown_socket(self._response)
        try:
            if self._events:
                self._events.close()
        except Exception:
            pass

    def __enter__(self) -> FlagClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------ evaluation

    def _typed(
        self, key: str, user: dict, default: Any, check: Callable[[Any], bool]
    ) -> EvaluationDetail:
        try:
            if not self._store.initialized:
                return EvaluationDetail(default, None, _err("CLIENT_NOT_READY"))
            flag = self._store.get(key)
            if flag is None:
                return EvaluationDetail(default, None, _err("FLAG_NOT_FOUND"))
            result = evaluation.evaluate(flag, user)
            if result.variation_index is None:
                return EvaluationDetail(default, None, result.reason)
            if not check(result.value):
                return EvaluationDetail(default, None, _err("WRONG_TYPE"))
            if result.reason.get("in_experiment") and self._events:
                self._events.record_exposure(user["id"], key, result.variation_index)
            return EvaluationDetail(result.value, result.variation_index, result.reason)
        except Exception:
            log.exception("featureflags: evaluation of %r failed", key)
            return EvaluationDetail(default, None, _err("EXCEPTION"))

    # --------------------------------------------------------------- updates

    @property
    def _auth(self) -> dict:
        return {"Authorization": self._sdk_key}

    def _fetch_snapshot(self) -> None:
        data = request_json("GET", f"{self._base}/sdk/v1/flags", self._auth)
        self._replace(data["env_version"], data["flags"])

    def _replace(self, env_version: int, flags: dict) -> None:
        changed = self._store.replace(env_version, flags)
        self._ready.set()
        self._notify(changed)

    def _notify(self, keys) -> None:
        for key in keys:
            for fn in list(self._listeners):
                try:
                    fn(key)
                except Exception:
                    log.exception("featureflags: listener raised")

    def _handle(self, event: str, data: str) -> None:
        if event == "put":
            payload = json.loads(data)
            self._replace(payload["env_version"], payload["flags"])
        elif event == "patch":
            payload = json.loads(data)
            outcome = self._store.apply_patch(
                payload["env_version"], payload["key"], payload["flag"]
            )
            if outcome == APPLIED:
                self._notify([payload["key"]])
            elif outcome == GAP:
                log.info("featureflags: missed an update, re-syncing")
                self._fetch_snapshot()

    def _stream_loop(self) -> None:
        backoff = Backoff()
        while not self._closed.is_set():
            started = time.monotonic()
            try:
                self._response = open_stream(
                    f"{self._base}/sdk/v1/stream", self._auth, READ_TIMEOUT
                )
                for event, data in parse_sse(iter(self._response.readline, b"")):
                    if self._closed.is_set():
                        return
                    if event:
                        self._handle(event, data)
                    if time.monotonic() - started > HEALTHY_AFTER:
                        backoff.reset()
            except Exception as e:
                if self._closed.is_set():
                    return
                log.warning("featureflags: stream error (%s); keeping last known flags", e)
            finally:
                try:
                    if self._response is not None:
                        self._response.close()
                except Exception:
                    pass
            self._closed.wait(backoff.next())

    def _poll_loop(self) -> None:
        while not self._closed.is_set():
            try:
                self._fetch_snapshot()
            except Exception as e:
                log.warning("featureflags: poll failed (%s); keeping last known flags", e)
            self._closed.wait(self._poll_interval)

    def _post_events(self, batch: list[dict]) -> None:
        request_json("POST", f"{self._base}/sdk/v1/events", self._auth, {"events": batch})


def _shutdown_socket(response: Any) -> None:
    """Unblock a thread sitting in response.readline().

    HTTPResponse.close() from another thread would wait on the reader's lock until
    the read timed out, so shut the socket down underneath it instead.
    """
    try:
        sock = response.fp.raw._sock  # type: ignore[union-attr]
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass


def _err(kind: str) -> dict:
    return {"kind": "ERROR", "error_kind": kind}
