"""A rolling-window counter per key, kept in memory only.

The app uses it to cap extraction attempts per network (the key is an IP address), so keys are
never persisted and never logged. A restart clears every count, which is fine for a soft limit.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

# How often (in clock seconds) to drop keys whose hits have all expired, so memory stays bounded.
_SWEEP_INTERVAL_SECONDS = 600.0


class SlidingWindowLimiter:
    """Allow at most ``limit`` hits per key within any rolling ``window_seconds``."""

    def __init__(self, limit: int, window_seconds: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if limit < 0:
            raise ValueError("limit must be zero or more")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._next_sweep: float | None = None

    def hit(self, key: str) -> int | None:
        """Count one attempt for ``key``.

        Allowed: records it and returns None. Over the limit: records nothing and returns how many
        whole seconds until the oldest counted attempt leaves the window (always at least 1).
        """
        with self._lock:
            now = self._clock()
            cutoff = now - self.window_seconds
            self._sweep_if_due(now, cutoff)
            hits = self._hits.get(key)
            if hits is not None:
                while hits and hits[0] <= cutoff:
                    hits.popleft()
            count = len(hits) if hits is not None else 0
            if count >= self.limit:
                oldest = hits[0] if hits else now  # no hits at all only happens when limit is 0
                return max(1, math.ceil(oldest + self.window_seconds - now))
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            hits.append(now)
            return None

    def _sweep_if_due(self, now: float, cutoff: float) -> None:
        """Forget keys with no hits left in the window. Caller holds the lock."""
        if self._next_sweep is not None and now < self._next_sweep:
            return
        self._next_sweep = now + min(float(self.window_seconds), _SWEEP_INTERVAL_SECONDS)
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
