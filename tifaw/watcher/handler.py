from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler

from tifaw.indexer.queue import IndexQueue
from tifaw.models.database import Database

logger = logging.getLogger(__name__)

# Patterns to always ignore
IGNORE_PATTERNS = {
    ".DS_Store",
    ".localized",
    "Thumbs.db",
    "desktop.ini",
}

IGNORE_PREFIXES = (".", "~", "_")
IGNORE_SUFFIXES = (".tmp", ".crdownload", ".part", ".download", ".partial")

DEBOUNCE_SECONDS = 2.0


class FileEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        db: Database,
        queue: IndexQueue,
        watch_folder: str,
        supported_extensions: set[str],
        max_file_size: int,
    ) -> None:
        super().__init__()
        self.db = db
        self.queue = queue
        self.watch_folder = watch_folder
        self.supported_extensions = supported_extensions
        self.max_file_size = max_file_size
        self._debounce_timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._loop = asyncio.get_event_loop()

    def _should_ignore(self, path: Path) -> bool:
        name = path.name
        if name in IGNORE_PATTERNS:
            return True
        if any(name.startswith(p) for p in IGNORE_PREFIXES):
            return True
        if any(name.endswith(s) for s in IGNORE_SUFFIXES):
            return True
        if self.supported_extensions and path.suffix.lower() not in self.supported_extensions:
            return True
        try:
            size = path.stat().st_size
            if size < 100 or size > self.max_file_size:
                return True
        except OSError:
            return True
        return False

    def _schedule_enqueue(self, file_path: str, priority: int = 1) -> None:
        with self._lock:
            existing = self._debounce_timers.get(file_path)
            if existing:
                existing.cancel()

            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                self._enqueue_from_thread,
                args=(file_path, priority),
            )
            self._debounce_timers[file_path] = timer
            timer.start()

    def _enqueue_from_thread(self, file_path: str, priority: int) -> None:
        with self._lock:
            self._debounce_timers.pop(file_path, None)

        path = Path(file_path)
        if not path.exists() or self._should_ignore(path):
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.queue.enqueue(file_path, priority=priority), self._loop
            )
            logger.info("Enqueued: %s (priority=%d)", path.name, priority)
        except RuntimeError:
            logger.warning("No event loop available to enqueue %s", file_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_enqueue(event.src_path, priority=1)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_enqueue(event.src_path, priority=2)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # Treat the destination as a new file
        if hasattr(event, "dest_path"):
            self._schedule_enqueue(event.dest_path, priority=1)
