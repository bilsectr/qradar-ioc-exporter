"""APScheduler-based periodic sync of QRadar reference sets into the store."""

from __future__ import annotations

import asyncio
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .feed_store import FeedStore
from .qradar_client import QRadarClient, QRadarError

logger = logging.getLogger("qradar.scheduler")


class SyncService:
    """Coordinates scheduled and on-demand reference-set synchronisation."""

    def __init__(
        self,
        settings: Settings,
        store: FeedStore,
        client: QRadarClient,
    ) -> None:
        self._settings = settings
        self._store = store
        self._client = client
        self._scheduler = AsyncIOScheduler()
        # Serialise sync runs so a manual trigger can't overlap the timer.
        self._sync_lock = asyncio.Lock()

    async def _sync_one(self, feed_type: str, refset_name: str) -> int:
        """Fetch a single reference set and update the store.

        Returns the entry count on success. On failure logs the error,
        records it in the store, and returns ``-1`` without raising so a
        single bad set never aborts the whole sync.
        """
        try:
            entries = await self._client.fetch_reference_set(refset_name)
        except QRadarError as exc:
            await self._store.record_error()
            logger.error(
                "Reference set sync failed",
                extra={
                    "feed_type": feed_type,
                    "refset": refset_name,
                    "error": str(exc),
                },
            )
            return -1
        except Exception:  # noqa: BLE001 - never let one set crash the job
            await self._store.record_error()
            logger.exception(
                "Unexpected error syncing reference set",
                extra={"feed_type": feed_type, "refset": refset_name},
            )
            return -1

        await self._store.update(feed_type, entries)
        logger.info(
            "Reference set synced",
            extra={
                "feed_type": feed_type,
                "refset": refset_name,
                "entry_count": len(entries),
            },
        )
        return len(entries)

    async def sync_all_feeds(self) -> dict[str, int]:
        """Fetch all four reference sets concurrently and update the store."""
        async with self._sync_lock:
            start = time.perf_counter()
            logger.info("Sync started")

            ref_sets = self._settings.reference_sets
            results = await asyncio.gather(
                *(self._sync_one(ft, name) for ft, name in ref_sets.items())
            )
            counts = dict(zip(ref_sets.keys(), results, strict=True))

            duration_ms = (time.perf_counter() - start) * 1000.0
            await self._store.mark_sync_complete(duration_ms)

            logger.info(
                "Sync finished",
                extra={"duration_ms": round(duration_ms, 2), "counts": counts},
            )
            return counts

    def start(self) -> None:
        """Register the recurring job and start the scheduler."""
        self._scheduler.add_job(
            self.sync_all_feeds,
            trigger="interval",
            seconds=self._settings.sync_interval_seconds,
            id="sync_all_feeds",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started",
            extra={"interval_seconds": self._settings.sync_interval_seconds},
        )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def trigger_now(self) -> None:
        """Fire a sync as soon as the event loop is free (non-blocking)."""
        asyncio.create_task(self.sync_all_feeds())
