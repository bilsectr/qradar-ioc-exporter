"""Thread-safe in-memory store for feed data and sync statistics."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

FEED_TYPES: tuple[str, ...] = ("ip", "hash", "domain", "url")


class FeedStore:
    """Holds the latest feed entries plus sync metadata.

    All mutating access is guarded by an :class:`asyncio.Lock` so concurrent
    sync jobs and request handlers see a consistent snapshot.
    """

    def __init__(self) -> None:
        self._data: dict[str, list[str]] = {ft: [] for ft in FEED_TYPES}
        self._lock = asyncio.Lock()
        self._last_sync: datetime | None = None
        self._sync_count: int = 0
        self._error_count: int = 0
        self._last_sync_duration_ms: float = 0.0

    async def update(self, feed_type: str, entries: list[str]) -> None:
        """Replace the entries for ``feed_type``."""
        if feed_type not in self._data:
            raise KeyError(f"Unknown feed type: {feed_type!r}")
        async with self._lock:
            # Store a defensive copy so callers cannot mutate our state.
            self._data[feed_type] = list(entries)

    async def get(self, feed_type: str) -> list[str]:
        """Return a copy of the entries for ``feed_type``."""
        if feed_type not in self._data:
            raise KeyError(f"Unknown feed type: {feed_type!r}")
        async with self._lock:
            return list(self._data[feed_type])

    async def mark_sync_complete(self, duration_ms: float) -> None:
        """Record a successful sync run."""
        async with self._lock:
            self._last_sync = datetime.now(UTC)
            self._sync_count += 1
            self._last_sync_duration_ms = duration_ms

    async def record_error(self) -> None:
        """Increment the error counter."""
        async with self._lock:
            self._error_count += 1

    async def get_counts(self) -> dict[str, int]:
        async with self._lock:
            return {ft: len(values) for ft, values in self._data.items()}

    async def get_stats(self) -> dict[str, object]:
        """Return a snapshot of sync statistics and per-feed counts."""
        async with self._lock:
            return {
                "last_sync": self._last_sync.isoformat() if self._last_sync else None,
                "last_sync_duration_ms": round(self._last_sync_duration_ms, 2),
                "sync_count": self._sync_count,
                "error_count": self._error_count,
                "counts": {ft: len(v) for ft, v in self._data.items()},
            }

    @property
    def last_sync(self) -> datetime | None:
        return self._last_sync
