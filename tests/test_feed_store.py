"""Tests for the thread-safe in-memory feed store."""

from __future__ import annotations

import asyncio

import pytest

from app.feed_store import FEED_TYPES, FeedStore


async def test_update_and_get_roundtrip() -> None:
    store = FeedStore()
    await store.update("ip", ["1.1.1.1", "2.2.2.2"])
    assert await store.get("ip") == ["1.1.1.1", "2.2.2.2"]


async def test_get_returns_copy_not_internal_reference() -> None:
    store = FeedStore()
    await store.update("ip", ["1.1.1.1"])
    snapshot = await store.get("ip")
    snapshot.append("3.3.3.3")
    # Mutating the returned list must not affect stored state.
    assert await store.get("ip") == ["1.1.1.1"]


async def test_unknown_feed_type_raises() -> None:
    store = FeedStore()
    with pytest.raises(KeyError):
        await store.get("nope")
    with pytest.raises(KeyError):
        await store.update("nope", [])


async def test_concurrent_updates_are_consistent() -> None:
    store = FeedStore()

    async def writer(feed_type: str, n: int) -> None:
        for i in range(50):
            await store.update(feed_type, [f"{feed_type}-{i}-{n}"])

    await asyncio.gather(
        writer("ip", 1),
        writer("hash", 2),
        writer("domain", 3),
        writer("url", 4),
    )

    # Each feed must hold exactly one entry from its own writer.
    for ft in FEED_TYPES:
        values = await store.get(ft)
        assert len(values) == 1
        assert values[0].startswith(ft)


async def test_stats_track_sync_and_errors() -> None:
    store = FeedStore()
    await store.update("ip", ["1.1.1.1", "2.2.2.2"])
    await store.update("hash", ["abc"])
    await store.mark_sync_complete(123.45)
    await store.record_error()

    stats = await store.get_stats()
    assert stats["sync_count"] == 1
    assert stats["error_count"] == 1
    assert stats["last_sync_duration_ms"] == 123.45
    assert stats["last_sync"] is not None
    assert stats["counts"] == {"ip": 2, "hash": 1, "domain": 0, "url": 0}


async def test_last_sync_none_before_first_sync() -> None:
    store = FeedStore()
    stats = await store.get_stats()
    assert stats["last_sync"] is None
    assert store.last_sync is None
