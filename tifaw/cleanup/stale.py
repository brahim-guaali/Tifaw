from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from tifaw.models.database import Database

logger = logging.getLogger(__name__)


async def find_stale_files(db: Database, threshold_days: int = 90) -> list[dict]:
    """Find files whose OS last-access time is older than threshold_days."""
    cutoff = datetime.now() - timedelta(days=threshold_days)
    cursor = await db.db.execute("SELECT * FROM files ORDER BY modified_at DESC")
    rows = await cursor.fetchall()

    stale: list[dict] = []
    for row in rows:
        file_dict = dict(row)
        file_path = Path(file_dict["path"])
        if not file_path.exists():
            continue
        try:
            stat = file_path.stat()
            last_access = datetime.fromtimestamp(stat.st_atime)
            if last_access < cutoff:
                days_since = (datetime.now() - last_access).days
                file_dict["days_since_access"] = days_since
                file_dict["size_bytes"] = stat.st_size
                stale.append(file_dict)
        except OSError as exc:
            logger.debug("Cannot stat %s: %s", file_path, exc)
    return stale


async def calculate_cleanup_savings(stale_files: list[dict]) -> int:
    """Return total bytes that could be freed by deleting all stale files."""
    return sum(f.get("size_bytes", 0) for f in stale_files)


async def delete_files(file_ids: list[int], db: Database) -> dict:
    """Delete files from disk and remove from the database.

    Returns a summary with counts of deleted, missing, and failed files.
    """
    deleted = 0
    missing = 0
    failed = 0

    for fid in file_ids:
        file = await db.get_file(fid)
        if not file:
            missing += 1
            continue

        file_path = Path(file["path"])
        try:
            if file_path.exists():
                file_path.unlink()
            await db.db.execute("DELETE FROM files WHERE id = ?", (fid,))
            deleted += 1
        except OSError as exc:
            logger.error("Failed to delete %s: %s", file_path, exc)
            failed += 1

    await db.db.commit()
    return {"deleted": deleted, "missing": missing, "failed": failed}
