from __future__ import annotations

from datetime import datetime, timedelta

from tifaw.models.database import Database


async def generate_digest(db: Database, days: int = 1) -> dict:
    """Generate a daily digest of indexing activity over the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # Files indexed in the period
    cursor = await db.db.execute(
        "SELECT * FROM files WHERE indexed_at >= ?", (cutoff,)
    )
    recent = [dict(r) for r in await cursor.fetchall()]

    # Group by category
    by_category: dict[str, int] = {}
    for f in recent:
        cat = f.get("category") or "Uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1

    # Renames completed in period
    renames_cursor = await db.db.execute(
        """SELECT COUNT(*) as c FROM files
           WHERE rename_status = 'approved' AND indexed_at >= ?""",
        (cutoff,),
    )
    renames_row = await renames_cursor.fetchone()
    renames_completed = renames_row["c"] if renames_row else 0

    # Pending renames
    pending_cursor = await db.db.execute(
        "SELECT COUNT(*) as c FROM files WHERE rename_status = 'pending'"
    )
    pending_row = await pending_cursor.fetchone()
    pending_renames = pending_row["c"] if pending_row else 0

    # Total indexed ever
    total_cursor = await db.db.execute(
        "SELECT COUNT(*) as c FROM files WHERE status = 'indexed'"
    )
    total_row = await total_cursor.fetchone()
    total_indexed = total_row["c"] if total_row else 0

    period = "today" if days == 1 else f"last {days} days"

    return {
        "period": period,
        "new_files": len(recent),
        "by_category": by_category,
        "renames_completed": renames_completed,
        "pending_renames": pending_renames,
        "total_indexed": total_indexed,
    }
