from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from tifaw.config import Settings
from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logger = logging.getLogger(__name__)

# How often (seconds) the worker checks for pending files stuck in the DB
_RECOVERY_INTERVAL = 60
_RECOVERY_BATCH = 500


@dataclass(order=True)
class IndexJob:
    priority: int
    file_path: str = field(compare=False)


class IndexQueue:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[IndexJob] = asyncio.PriorityQueue()
        self._seen: set[str] = set()

    async def enqueue(self, file_path: str, priority: int = 1) -> None:
        if file_path in self._seen:
            return
        self._seen.add(file_path)
        await self._queue.put(IndexJob(priority=priority, file_path=file_path))

    async def recover_pending(self, db: Database) -> int:
        """Re-queue files that are 'pending' in the DB but not in the queue.

        This handles: server restarts, crashed jobs, Spotlight imports
        that added rows without queueing them, etc.
        """
        cursor = await db.db.execute(
            "SELECT path FROM files WHERE status='pending' LIMIT ?",
            (_RECOVERY_BATCH,),
        )
        rows = await cursor.fetchall()
        count = 0
        for row in rows:
            path = row["path"]
            if path not in self._seen:
                await self.enqueue(path, priority=5)
                count += 1
        if count:
            logger.info("Recovered %d pending files into queue", count)
        return count

    def size(self) -> int:
        return self._queue.qsize()

    def start_worker(
        self, db: Database, llm: OllamaClient, settings: Settings
    ) -> asyncio.Task:
        task = asyncio.create_task(self._worker(db, llm, settings))
        asyncio.create_task(self._recovery_loop(db))
        return task

    async def _recovery_loop(self, db: Database) -> None:
        """Periodically check for pending files that fell out of the queue."""
        while True:
            try:
                await asyncio.sleep(_RECOVERY_INTERVAL)
                if self._queue.qsize() == 0:
                    await self.recover_pending(db)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Recovery loop error")

    async def _worker(self, db: Database, llm: OllamaClient, settings: Settings) -> None:
        from tifaw.indexer.pipeline import process_file

        logger.info("Index worker running")
        while True:
            try:
                job = await self._queue.get()
                self._seen.discard(job.file_path)
                logger.info("Processing: %s (priority=%d)", job.file_path, job.priority)
                await process_file(job.file_path, db, llm, settings)
                self._queue.task_done()
            except asyncio.CancelledError:
                logger.info("Index worker cancelled")
                break
            except Exception:
                logger.exception("Error processing %s", job.file_path if 'job' in dir() else "unknown")
                await asyncio.sleep(1)
