from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from tifaw.config import Settings
from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logger = logging.getLogger(__name__)


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

    def size(self) -> int:
        return self._queue.qsize()

    def start_worker(
        self, db: Database, llm: OllamaClient, settings: Settings
    ) -> asyncio.Task:
        return asyncio.create_task(self._worker(db, llm, settings))

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
