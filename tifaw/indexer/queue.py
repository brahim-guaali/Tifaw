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
        self._queue: asyncio.PriorityQueue[IndexJob] = (
            asyncio.PriorityQueue()
        )
        self._seen: set[str] = set()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially

    def pause(self) -> None:
        """Pause workers (lets current jobs finish, then waits)."""
        self._pause_event.clear()

    def resume(self) -> None:
        """Resume workers."""
        self._pause_event.set()

    async def enqueue(
        self, file_path: str, priority: int = 1,
    ) -> None:
        if file_path in self._seen:
            return
        self._seen.add(file_path)
        await self._queue.put(
            IndexJob(priority=priority, file_path=file_path),
        )

    async def recover_pending(self, db: Database) -> int:
        """Re-queue files stuck in pending/tier1 status."""
        cursor = await db.db.execute(
            "SELECT path FROM files "
            "WHERE status IN ('pending', 'tier1') LIMIT ?",
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
            logger.info(
                "Recovered %d pending files into queue", count,
            )
        return count

    def size(self) -> int:
        return self._queue.qsize()

    def start_workers(
        self,
        db: Database,
        llm: OllamaClient,
        settings: Settings,
    ) -> list[asyncio.Task]:
        """Spawn N concurrent index workers + a recovery loop."""
        n = settings.resolved_index_workers()
        tasks = []
        for i in range(n):
            task = asyncio.create_task(
                self._worker(db, llm, settings, worker_id=i),
            )
            tasks.append(task)
        tasks.append(
            asyncio.create_task(self._recovery_loop(db, llm)),
        )
        logger.info("Started %d index workers", n)
        return tasks

    async def _recovery_loop(
        self, db: Database, llm: OllamaClient | None = None,
    ) -> None:
        """Periodically re-queue stuck files and wake on Ollama recovery."""
        ollama_was_down = False
        while True:
            try:
                await asyncio.sleep(_RECOVERY_INTERVAL)

                # Refill when queue is getting empty (not just zero),
                # so workers always have work in flight
                if self._queue.qsize() < 10:
                    await self.recover_pending(db)

                # If Ollama went down and came back, requeue pendings
                if llm is not None:
                    ok = await llm.health_check()
                    if ok and ollama_was_down:
                        logger.info(
                            "Ollama recovered — re-queueing pending files",
                        )
                        await self.recover_pending(db)
                    ollama_was_down = not ok
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Recovery loop error")

    async def _worker(
        self,
        db: Database,
        llm: OllamaClient,
        settings: Settings,
        worker_id: int = 0,
    ) -> None:
        from tifaw.indexer.pipeline import process_file

        tag = f"worker-{worker_id}"
        logger.info("[%s] Index worker running", tag)
        while True:
            try:
                await self._pause_event.wait()
                job = await self._queue.get()
                self._seen.discard(job.file_path)

                # Worker deduplication: skip if another worker
                # already indexed this file
                existing = await db.get_file_by_path(job.file_path)
                if (
                    existing
                    and existing.get("status") == "indexed"
                ):
                    self._queue.task_done()
                    continue

                logger.info(
                    "[%s] Processing: %s (priority=%d)",
                    tag, job.file_path, job.priority,
                )
                await process_file(
                    job.file_path, db, llm, settings,
                )
                self._queue.task_done()
            except asyncio.CancelledError:
                logger.info("[%s] Index worker cancelled", tag)
                break
            except Exception:
                path = (
                    job.file_path
                    if "job" in dir() else "unknown"
                )
                logger.exception(
                    "[%s] Error processing %s", tag, path,
                )
                await asyncio.sleep(1)
