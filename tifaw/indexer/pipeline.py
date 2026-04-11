from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from tifaw.config import Settings
from tifaw.indexer.analyzer import analyze_file
from tifaw.indexer.extractors import extract_content
from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database
from tifaw.renamer.smart_rename import is_generic_name

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _file_times(path: Path) -> tuple[str, str]:
    stat = path.stat()
    created = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc).isoformat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return created, modified


async def process_file(
    file_path: str, db: Database, llm: OllamaClient, settings: Settings
) -> None:
    path = Path(file_path)

    if not path.exists():
        logger.warning("File no longer exists: %s", file_path)
        return

    # Check if already indexed with same hash
    existing = await db.get_file_by_path(file_path)
    current_hash = _file_hash(path)
    if existing and existing.get("file_hash") == current_hash and existing.get("status") == "indexed":
        logger.debug("Skipping unchanged file: %s", path.name)
        return

    # Determine watch folder
    watch_folder = None
    for folder in settings.resolve_watch_folders():
        if str(path).startswith(str(folder)):
            watch_folder = str(folder)
            break

    created_at, modified_at = _file_times(path)

    # Upsert file record
    file_id = await db.upsert_file(
        path=file_path,
        filename=path.name,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        file_hash=current_hash,
        watch_folder=watch_folder,
        created_at=created_at,
        modified_at=modified_at,
    )

    await db.update_file_status(file_id, "indexing")

    # Extract content
    extraction = extract_content(path)

    # Analyze with LLM
    analysis = await analyze_file(
        filename=path.name,
        file_type=extraction.file_type,
        size_bytes=path.stat().st_size,
        extraction=extraction,
        llm=llm,
    )

    # Only suggest rename if name is generic AND the analyzer suggested one
    suggested_name = None
    if settings.rename_enabled and is_generic_name(path.name) and analysis.suggested_name:
        suggested_name = analysis.suggested_name

    # Store analysis results
    now = datetime.now(tz=timezone.utc).isoformat()
    await db.update_file_analysis(
        file_id=file_id,
        description=analysis.description,
        tags=analysis.tags,
        category=analysis.category,
        content_preview=extraction.text_content[:500] if extraction.text_content else None,
        suggested_name=suggested_name,
        indexed_at=now,
    )

    logger.info(
        "Indexed: %s → category=%s, tags=%s%s",
        path.name,
        analysis.category,
        analysis.tags,
        f", rename→{suggested_name}" if suggested_name else "",
    )
