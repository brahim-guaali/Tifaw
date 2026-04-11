from __future__ import annotations

import logging
import os
from pathlib import Path

from tifaw.models.database import Database

logger = logging.getLogger(__name__)


async def detect_duplicates(db: Database) -> dict[str, int]:
    """Scan the files table for duplicates and store results in the duplicates table.

    Phase 1: exact file_hash match (different paths, same content).
    Phase 2: same filename in different watch_folders.
    """

    found_hash = 0
    found_name = 0

    # --- Phase 1: exact hash duplicates ---
    cursor = await db.db.execute(
        """
        SELECT a.id AS id_a, b.id AS id_b
        FROM files a
        JOIN files b ON a.file_hash = b.file_hash AND a.id < b.id
        WHERE a.file_hash IS NOT NULL AND a.file_hash != ''
          AND a.path != b.path
        """
    )
    hash_pairs = await cursor.fetchall()
    for pair in hash_pairs:
        # Skip if this pair already exists
        existing = await db.db.execute(
            """SELECT 1 FROM duplicates
               WHERE (file_id_a = ? AND file_id_b = ?)
                  OR (file_id_a = ? AND file_id_b = ?)""",
            (pair["id_a"], pair["id_b"], pair["id_b"], pair["id_a"]),
        )
        if await existing.fetchone():
            continue
        await db.db.execute(
            "INSERT INTO duplicates (file_id_a, file_id_b, similarity_type) VALUES (?, ?, ?)",
            (pair["id_a"], pair["id_b"], "exact_hash"),
        )
        found_hash += 1

    # --- Phase 2: same filename in different watch_folders ---
    cursor = await db.db.execute(
        """
        SELECT a.id AS id_a, b.id AS id_b
        FROM files a
        JOIN files b ON a.filename = b.filename AND a.id < b.id
        WHERE a.watch_folder != b.watch_folder
          AND a.path != b.path
        """
    )
    name_pairs = await cursor.fetchall()
    for pair in name_pairs:
        existing = await db.db.execute(
            """SELECT 1 FROM duplicates
               WHERE (file_id_a = ? AND file_id_b = ?)
                  OR (file_id_a = ? AND file_id_b = ?)""",
            (pair["id_a"], pair["id_b"], pair["id_b"], pair["id_a"]),
        )
        if await existing.fetchone():
            continue
        await db.db.execute(
            "INSERT INTO duplicates (file_id_a, file_id_b, similarity_type) VALUES (?, ?, ?)",
            (pair["id_a"], pair["id_b"], "same_filename"),
        )
        found_name += 1

    await db.db.commit()
    logger.info("Duplicate scan complete: %d hash matches, %d filename matches", found_hash, found_name)
    return {"hash_duplicates": found_hash, "name_duplicates": found_name}


async def get_pending_duplicates(db: Database) -> list[dict]:
    """Return all unresolved duplicate pairs with file details."""
    cursor = await db.db.execute(
        """
        SELECT d.id, d.similarity_type, d.status, d.detected_at,
               a.id AS file_a_id, a.path AS file_a_path, a.filename AS file_a_name,
               a.size_bytes AS file_a_size, a.file_hash AS file_a_hash,
               b.id AS file_b_id, b.path AS file_b_path, b.filename AS file_b_name,
               b.size_bytes AS file_b_size, b.file_hash AS file_b_hash
        FROM duplicates d
        JOIN files a ON d.file_id_a = a.id
        JOIN files b ON d.file_id_b = b.id
        WHERE d.status = 'pending'
        ORDER BY d.detected_at DESC
        """
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        r = dict(row)
        results.append({
            "id": r["id"],
            "similarity_type": r["similarity_type"],
            "status": r["status"],
            "detected_at": r["detected_at"],
            "file_a": {
                "id": r["file_a_id"],
                "path": r["file_a_path"],
                "filename": r["file_a_name"],
                "size_bytes": r["file_a_size"],
                "file_hash": r["file_a_hash"],
            },
            "file_b": {
                "id": r["file_b_id"],
                "path": r["file_b_path"],
                "filename": r["file_b_name"],
                "size_bytes": r["file_b_size"],
                "file_hash": r["file_b_hash"],
            },
        })
    return results


async def resolve_duplicate(
    duplicate_id: int,
    keep_file_id: int,
    db: Database,
) -> dict[str, str]:
    """Resolve a duplicate pair: keep one file, delete the other from disk and DB."""

    cursor = await db.db.execute(
        "SELECT * FROM duplicates WHERE id = ? AND status = 'pending'",
        (duplicate_id,),
    )
    dup = await cursor.fetchone()
    if not dup:
        return {"error": "Duplicate not found or already resolved"}

    dup = dict(dup)
    file_id_a = dup["file_id_a"]
    file_id_b = dup["file_id_b"]

    if keep_file_id == file_id_a:
        remove_file_id = file_id_b
    elif keep_file_id == file_id_b:
        remove_file_id = file_id_a
    else:
        return {"error": "keep_file_id must be one of the two files in this duplicate pair"}

    # Get the file to remove
    remove_file = await db.get_file(remove_file_id)
    if not remove_file:
        return {"error": "File to remove not found in database"}

    # Delete from disk
    file_path = Path(remove_file["path"])
    if file_path.exists():
        try:
            os.remove(str(file_path))
            logger.info("Deleted file from disk: %s", file_path)
        except OSError as exc:
            logger.error("Failed to delete %s: %s", file_path, exc)
            return {"error": f"Failed to delete file: {exc}"}

    # Remove from DB
    await db.db.execute("DELETE FROM files WHERE id = ?", (remove_file_id,))

    # Mark duplicate as resolved
    await db.db.execute(
        "UPDATE duplicates SET status = 'resolved' WHERE id = ?",
        (duplicate_id,),
    )
    await db.db.commit()

    logger.info(
        "Resolved duplicate #%d: kept file #%d, removed file #%d",
        duplicate_id, keep_file_id, remove_file_id,
    )
    return {"status": "resolved", "kept": keep_file_id, "removed": remove_file_id}
