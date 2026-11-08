"""In-memory flag store.

Reads are lock-free: the whole dict is replaced on every write (copy-on-write),
and CPython reference assignment is atomic, so an evaluation always sees a
consistent snapshot.
"""

from __future__ import annotations

import threading
from typing import Optional

APPLIED, STALE, GAP = "applied", "stale", "gap"


class FlagStore:
    def __init__(self) -> None:
        self._flags: dict[str, dict] = {}
        self._env_version = 0
        self._initialized = False
        self._write_lock = threading.Lock()

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def env_version(self) -> int:
        return self._env_version

    def get(self, key: str) -> Optional[dict]:
        return self._flags.get(key)

    def all(self) -> dict[str, dict]:
        return self._flags

    def replace(self, env_version: int, flags: dict[str, dict]) -> set[str]:
        """Replace everything. Returns the keys whose config changed."""
        with self._write_lock:
            old = self._flags
            new = dict(flags)
            changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
            self._flags = new
            self._env_version = env_version
            self._initialized = True
            return changed

    def apply_patch(self, env_version: int, key: str, flag: Optional[dict]) -> str:
        """Apply one versioned change (spec/streaming.md rule 2)."""
        with self._write_lock:
            if not self._initialized:
                return GAP
            if env_version <= self._env_version:
                return STALE
            if env_version != self._env_version + 1:
                return GAP
            new = dict(self._flags)
            if flag is None:
                new.pop(key, None)
            else:
                new[key] = flag
            self._flags = new
            self._env_version = env_version
            return APPLIED
