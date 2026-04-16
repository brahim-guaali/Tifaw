from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tifaw.models.database import Database

logger = logging.getLogger(__name__)

# Map Spotlight content types to our supported extensions
CONTENT_TYPE_MAP = {
    "com.adobe.pdf": ".pdf",
    "public.png": ".png",
    "public.jpeg": ".jpg",
    "com.compuserve.gif": ".gif",
    "org.webmproject.webp": ".webp",
    "public.svg-image": ".svg",
    "public.plain-text": ".txt",
    "net.daringfireball.markdown": ".md",
    "public.comma-separated-values-text": ".csv",
    "public.json": ".json",
    "public.python-script": ".py",
    "com.netscape.javascript-source": ".js",
    "public.html": ".html",
    "public.css": ".css",
    "org.openxmlformats.wordprocessingml.document": ".docx",
    "org.openxmlformats.spreadsheetml.sheet": ".xlsx",
}


def _run_mdfind(folder: str, max_results: int = 5000) -> list[str]:
    """Use Spotlight to discover files in a folder."""
    try:
        result = subprocess.run(
            ["mdfind", "-onlyin", folder, "kMDItemContentType == '*'"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        paths = [p for p in result.stdout.strip().split("\n") if p]
        return paths[:max_results]
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("mdfind failed for %s: %s", folder, e)
        return []


def _get_metadata(file_path: str) -> dict:
    """Get Spotlight metadata for a file using mdls."""
    try:
        result = subprocess.run(
            ["mdls", "-plist", "-", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {}

        # Parse plist output
        import plistlib
        data = plistlib.loads(result.stdout.encode())
        return data
    except Exception:
        # Fallback: parse mdls text output
        return _get_metadata_text(file_path)


def _get_metadata_text(file_path: str) -> dict:
    """Fallback metadata extraction from mdls text output."""
    try:
        result = subprocess.run(
            ["mdls", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        metadata = {}
        for line in result.stdout.split("\n"):
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"')
                if value != "(null)":
                    metadata[key] = value
        return metadata
    except Exception as e:
        logger.debug("mdls fallback failed for %s: %s", file_path, e)
        return {}


async def import_from_spotlight(
    folder: str,
    db: Database,
    supported_extensions: set[str],
    max_file_size: int = 100 * 1024 * 1024,
) -> int:
    """Import files from a folder using Spotlight index instead of directory listing.

    Returns the number of new files queued for indexing.
    """
    logger.info("Importing from Spotlight index: %s", folder)

    # Run mdfind in a thread to avoid blocking
    loop = asyncio.get_event_loop()
    paths = await loop.run_in_executor(None, _run_mdfind, folder)
    logger.info("Spotlight found %d files in %s", len(paths), folder)

    queued = 0
    skipped = 0

    for file_path in paths:
        path = Path(file_path)

        # Filter by extension
        if supported_extensions and path.suffix.lower() not in supported_extensions:
            skipped += 1
            continue

        # Skip hidden files
        if path.name.startswith("."):
            continue

        # Skip files that are too large or too small
        try:
            size = path.stat().st_size
            if size < 100 or size > max_file_size:
                continue
        except OSError:
            continue

        # Skip if already in DB
        existing = await db.get_file_by_path(file_path)
        if existing:
            continue

        # Get basic file info and insert into DB as pending
        try:
            stat = path.stat()
            created = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc).isoformat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

            await db.upsert_file(
                path=file_path,
                filename=path.name,
                extension=path.suffix.lower(),
                size_bytes=size,
                file_hash=None,  # Will be computed during indexing
                watch_folder=folder,
                created_at=created,
                modified_at=modified,
            )
            queued += 1
        except Exception as e:
            logger.debug("Failed to import %s: %s", file_path, e)

    logger.info(
        "Spotlight import complete: %d new files queued, %d skipped (unsupported type) from %s",
        queued, skipped, folder,
    )
    return queued


async def import_and_queue(
    folder: str,
    db: Database,
    queue,
    supported_extensions: set[str],
    max_file_size: int = 100 * 1024 * 1024,
) -> int:
    """Import files via Spotlight and add them to the indexing queue."""
    count = await import_from_spotlight(folder, db, supported_extensions, max_file_size)

    # Queue all pending files for AI analysis
    pending = await db.get_files(watch_folder=folder, status="pending", limit=5000)
    for f in pending:
        await queue.enqueue(f["path"], priority=3)

    return count
