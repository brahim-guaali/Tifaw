from __future__ import annotations

import json
import logging
from typing import Any

from tifaw.models.database import Database

logger = logging.getLogger(__name__)


async def get_smart_folders(db: Database) -> list[dict[str, Any]]:
    """Return all smart folder definitions."""
    cursor = await db.db.execute(
        "SELECT * FROM smart_folders ORDER BY created_at DESC"
    )
    rows = await cursor.fetchall()
    folders = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("rule"), str):
            try:
                d["rule"] = json.loads(d["rule"])
            except json.JSONDecodeError:
                d["rule"] = {}
        folders.append(d)
    return folders


async def get_smart_folder_files(folder_id: int, db: Database) -> list[dict]:
    """Query files matching a smart folder's rules (by tags/categories)."""
    cursor = await db.db.execute(
        "SELECT * FROM smart_folders WHERE id = ?", (folder_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return []

    rule_str = row["rule"]
    if isinstance(rule_str, str):
        try:
            rule = json.loads(rule_str)
        except json.JSONDecodeError:
            rule = {}
    else:
        rule = rule_str

    categories: list[str] = rule.get("categories", [])
    tags: list[str] = rule.get("tags", [])

    if not categories and not tags:
        return []

    # Build query: category IN (...) OR any tag matches via LIKE on the JSON array
    conditions: list[str] = []
    params: list[str] = []

    if categories:
        placeholders = ",".join("?" for _ in categories)
        conditions.append(f"category IN ({placeholders})")
        params.extend(categories)

    for tag in tags:
        # tags column stores a JSON array string, e.g. '["invoice", "receipt"]'
        conditions.append("tags LIKE ?")
        params.append(f"%{tag}%")

    where = " OR ".join(conditions)
    query = f"SELECT * FROM files WHERE status = 'indexed' AND ({where}) ORDER BY modified_at DESC"

    file_cursor = await db.db.execute(query, params)
    rows = await file_cursor.fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        results.append(d)
    return results


async def create_smart_folder(
    name: str,
    rule: dict[str, Any],
    icon: str | None,
    db: Database,
) -> dict[str, Any]:
    """Create a new smart folder definition."""
    rule_json = json.dumps(rule)
    await db.db.execute(
        "INSERT INTO smart_folders (name, rule, icon) VALUES (?, ?, ?)",
        (name, rule_json, icon),
    )
    await db.db.commit()

    cursor = await db.db.execute(
        "SELECT * FROM smart_folders WHERE id = last_insert_rowid()"
    )
    row = await cursor.fetchone()
    d = dict(row)
    d["rule"] = rule
    return d


async def delete_smart_folder(folder_id: int, db: Database) -> bool:
    """Delete a smart folder. Returns True if a row was deleted."""
    cursor = await db.db.execute(
        "DELETE FROM smart_folders WHERE id = ?", (folder_id,)
    )
    await db.db.commit()
    return cursor.rowcount > 0
