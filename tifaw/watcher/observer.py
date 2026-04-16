from __future__ import annotations

import json
import logging
from pathlib import Path

from watchdog.observers import Observer

from tifaw.config import Settings
from tifaw.indexer.extractors import (
    EXTENSION_CATEGORIES,
    extract_metadata,
)
from tifaw.indexer.queue import IndexQueue
from tifaw.models.database import Database
from tifaw.watcher.handler import FileEventHandler

logger = logging.getLogger(__name__)

# Files that indicate a directory is a code project root.
_PROJECT_MARKERS = {
    "package.json", "pyproject.toml", "requirements.txt",
    "setup.py", "Cargo.toml", "go.mod", "Makefile",
    "CMakeLists.txt", ".git", "Gemfile", "build.gradle",
    "pom.xml", ".xcodeproj",
}

# Directory suffixes that are treated as opaque bundles
# (don't descend into them)
_BUNDLE_SUFFIXES = (
    ".app", ".framework", ".bundle", ".xcodeproj",
    ".playground", ".photoslibrary", ".musiclibrary",
    ".imovielibrary", ".tvlibrary", ".aplibrary",
)

# Batch DB commits every N files for performance
_COMMIT_BATCH = 50


def _is_project_dir(path: Path) -> bool:
    """Return True if *path* looks like a code project root."""
    try:
        names = {e.name for e in path.iterdir()}
    except (PermissionError, OSError):
        return False
    return bool(names & _PROJECT_MARKERS)


class FileWatcher:
    def __init__(
        self, settings: Settings, db: Database, queue: IndexQueue,
    ) -> None:
        self.settings = settings
        self.db = db
        self.queue = queue
        self._observer = Observer()

    def start(self) -> None:
        for folder in self.settings.resolve_watch_folders():
            if not folder.exists():
                logger.warning(
                    "Watch folder does not exist, skipping: %s",
                    folder,
                )
                continue

            handler = FileEventHandler(
                db=self.db,
                queue=self.queue,
                watch_folder=str(folder),
                supported_extensions=set(
                    self.settings.supported_extensions,
                ),
                max_file_size=(
                    self.settings.max_file_size_mb * 1024 * 1024
                ),
            )
            self._observer.schedule(
                handler, str(folder),
                recursive=self.settings.recursive,
            )
            logger.info("Watching: %s", folder)

        self._observer.start()

        import asyncio

        for folder in self.settings.resolve_watch_folders():
            if folder.exists():
                asyncio.get_event_loop().create_task(
                    self._initial_scan(folder),
                )

    async def _initial_scan(self, folder: Path) -> None:
        """Walk *folder*, insert tier-1 metadata, and queue for LLM."""
        logger.info("Starting initial scan of %s", folder)
        count = 0
        try:
            count = await self._walk(
                folder, watch_folder=str(folder), is_root=True,
            )
            await self.db.db.commit()
        except PermissionError:
            logger.info(
                "Permission denied for %s — falling back to Spotlight",
                folder,
            )
            try:
                from tifaw.indexer.spotlight import import_and_queue

                count = await import_and_queue(
                    str(folder),
                    self.db,
                    self.queue,
                    supported_extensions=set(
                        self.settings.supported_extensions,
                    ),
                    max_file_size=(
                        self.settings.max_file_size_mb * 1024 * 1024
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Spotlight fallback failed for %s: %s",
                    folder, e,
                )
        logger.info(
            "Discovered %d files from initial scan of %s",
            count, folder,
        )

    def _should_scan(self, path: Path) -> bool:
        """Return True if *path* matches supported extensions."""
        exts = self.settings.supported_extensions
        if exts and path.suffix.lower() not in set(exts):
            return False
        try:
            size = path.stat().st_size
            max_size = self.settings.max_file_size_mb * 1024 * 1024
            if size < 100 or size > max_size:
                return False
        except OSError:
            return False
        return True

    async def _ingest_file(
        self, item: Path, watch_folder: str,
    ) -> bool:
        """Tier-1: extract metadata, insert into DB, queue for LLM.

        Returns True if the file was newly ingested.
        """
        existing = await self.db.get_file_by_path(str(item))
        if existing:
            return False

        try:
            meta = extract_metadata(item)
        except (PermissionError, OSError):
            return False

        ext = item.suffix.lower()
        category = EXTENSION_CATEGORIES.get(ext, "Other")
        metadata_json = (
            json.dumps(meta["metadata"])
            if meta.get("metadata") else None
        )

        file_id = await self.db.upsert_file(
            path=str(item),
            filename=item.name,
            extension=ext,
            size_bytes=meta["size_bytes"],
            file_hash=None,
            watch_folder=watch_folder,
            created_at=meta.get("created_at"),
            modified_at=meta.get("modified_at"),
            metadata=metadata_json,
        )
        # Set category and tier1 status
        await self.db.db.execute(
            "UPDATE files SET category=?, status='tier1' WHERE id=?",
            (category, file_id),
        )
        await self.queue.enqueue(str(item), priority=3)
        return True

    async def _walk(
        self, folder: Path, *, watch_folder: str, is_root: bool,
    ) -> int:
        """Recursively walk *folder*, skipping project sub-trees."""
        count = 0
        try:
            entries = sorted(folder.iterdir())
        except (PermissionError, OSError):
            return 0

        for item in entries:
            if item.name.startswith("."):
                continue

            if item.is_file() and self._should_scan(item):
                if await self._ingest_file(item, watch_folder):
                    count += 1
                    if count % _COMMIT_BATCH == 0:
                        await self.db.db.commit()
            elif item.is_dir() and self.settings.recursive:
                if item.name.endswith(_BUNDLE_SUFFIXES):
                    # App/framework bundle — don't descend
                    logger.debug("Skipped bundle: %s", item)
                    continue
                if _is_project_dir(item) and not is_root:
                    count += await self._walk_flat(
                        item, watch_folder=watch_folder,
                    )
                    logger.debug(
                        "Skipped project sub-tree: %s", item,
                    )
                else:
                    count += await self._walk(
                        item,
                        watch_folder=watch_folder,
                        is_root=False,
                    )

        return count

    async def _walk_flat(
        self, folder: Path, *, watch_folder: str,
    ) -> int:
        """Index only top-level files in *folder*."""
        count = 0
        try:
            for item in folder.iterdir():
                if (
                    item.is_file()
                    and not item.name.startswith(".")
                    and self._should_scan(item)
                ):
                    if await self._ingest_file(item, watch_folder):
                        count += 1
                        if count % _COMMIT_BATCH == 0:
                            await self.db.db.commit()
        except (PermissionError, OSError):
            pass
        return count

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
