"""Photos gallery API with people/category/date filters."""
from __future__ import annotations

import json

from fastapi import APIRouter, Query

router = APIRouter(tags=["photos"])


@router.get("/photos")
async def get_photos(
    person: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_location: bool | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    from tifaw.main import db

    d = db.db
    image_exts = "('.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg')"

    conditions = [f"f.extension IN {image_exts}", "f.status = 'indexed'"]
    params: list = []

    if person:
        conditions.append("f.id IN (SELECT file_id FROM faces WHERE label = ?)")
        params.append(person)

    if category:
        conditions.append("f.category = ?")
        params.append(category)

    if date_from:
        conditions.append("f.created_at >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("f.created_at <= ?")
        params.append(date_to)

    if has_location is True:
        conditions.append("f.metadata IS NOT NULL AND json_extract(f.metadata, '$.gps_latitude') IS NOT NULL")

    where = " AND ".join(conditions)

    # Get total count
    total_row = await (await d.execute(
        f"SELECT COUNT(*) as c FROM files f WHERE {where}", params
    )).fetchone()

    # Get photos
    rows = await (await d.execute(
        f"""SELECT f.* FROM files f WHERE {where}
        ORDER BY f.created_at DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )).fetchall()

    photos = []
    for r in rows:
        f = dict(r)
        tags = f.get("tags")
        if isinstance(tags, str):
            try:
                f["tags"] = json.loads(tags)
            except Exception:
                f["tags"] = []
        metadata = f.get("metadata")
        if isinstance(metadata, str):
            try:
                f["metadata"] = json.loads(metadata)
            except Exception:
                f["metadata"] = None
        photos.append(f)

    # Get available filters (only on first page)
    filters = {}
    if offset == 0:
        # People who appear in photos
        people_rows = await (await d.execute(
            """SELECT label as name, MIN(id) as face_id, COUNT(DISTINCT file_id) as count
            FROM faces WHERE label IS NOT NULL
            GROUP BY label ORDER BY count DESC LIMIT 50"""
        )).fetchall()
        filters["people"] = [dict(r) for r in people_rows]

        # Categories present in photos
        cat_rows = await (await d.execute(
            f"""SELECT category, COUNT(*) as count FROM files
            WHERE extension IN {image_exts} AND status='indexed' AND category IS NOT NULL
            GROUP BY category ORDER BY count DESC"""
        )).fetchall()
        filters["categories"] = [{"name": r["category"], "count": r["count"]} for r in cat_rows]

    return {
        "photos": photos,
        "total": total_row["c"],
        "limit": limit,
        "offset": offset,
        "filters": filters,
    }
