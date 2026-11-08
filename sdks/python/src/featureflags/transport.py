"""Minimal HTTP + Server-Sent Events over the standard library (no dependencies)."""

from __future__ import annotations

import json
import random
import urllib.request
from typing import Any, Iterator, Optional

USER_AGENT = "featureflags-python/0.1.0"


def request_json(
    method: str, url: str, headers: dict, body: Any = None, timeout: float = 10.0
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def open_stream(url: str, headers: dict, read_timeout: float):
    req = urllib.request.Request(url)
    for k, v in {"User-Agent": USER_AGENT, "Accept": "text/event-stream", **headers}.items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=read_timeout)


def parse_sse(lines: Iterator[bytes]) -> Iterator[tuple[str, str]]:
    """Yield (event, data) pairs. Comment lines (heartbeats) yield ("", "")."""
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            yield "", ""
        else:
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                event = value
            elif name == "data":
                data.append(value)


class Backoff:
    """Exponential backoff with +/-50% jitter (spec/streaming.md rule 4)."""

    def __init__(self, base: float = 1.0, cap: float = 30.0, rng: Optional[random.Random] = None):
        self.base, self.cap, self.attempt = base, cap, 0
        self._rng = rng or random.Random()

    def next(self) -> float:
        delay = min(self.cap, self.base * (2**self.attempt))
        self.attempt += 1
        return delay * (0.5 + self._rng.random())

    def reset(self) -> None:
        self.attempt = 0
