from __future__ import annotations

import logging
from pathlib import Path

from watchdog.observers import Observer

from tifaw.config import Settings
from tifaw.indexer.queue import IndexQueue
from tifaw.models.database import Database
from tifaw.watcher.handler import FileEventHandler

logger = logging.getLogger(__name__)


class FileWatcher:
    def __init__(self, settings: Settings, db: Database, queue: IndexQueue) -> None:
        self.settings = settings
        self.db = db
        self.queue = queue
        self._observer = Observer()

    def start(self) -> None:
        for folder in self.settings.resolve_watch_folders():
            if not folder.exists():
                logger.warning("Watch folder does not exist, skipping: %s", folder)
                continue

            handler = FileEventHandler(
                db=self.db,
                queue=self.queue,
                watch_folder=str(folder),
                supported_extensions=set(self.settings.supported_extensions),
                max_file_size=self.settings.max_file_size_mb * 1024 * 1024,
            )
            self._observer.schedule(handler, str(folder), recursive=False)
            logger.info("Watching: %s", folder)

        self._observer.start()

        # Queue initial scan of existing files
        import asyncio

        for folder in self.settings.resolve_watch_folders():
            if folder.exists():
                asyncio.get_event_loop().create_task(self._initial_scan(folder))

    async def _initial_scan(self, folder: Path) -> None:
        logger.info("Starting initial scan of %s", folder)
        count = 0
        try:
            for item in folder.iterdir():
                if item.is_file() and not item.name.startswith("."):
                    existing = await self.db.get_file_by_path(str(item))
                    if not existing:
                        await self.queue.enqueue(str(item), priority=3)
                        count += 1
        except PermissionError:
            logger.warning("Permission denied scanning %s — grant Full Disk Access in System Settings", folder)
        logger.info("Queued %d files from initial scan of %s", count, folder)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
