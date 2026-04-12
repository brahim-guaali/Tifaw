"""Documents API — files grouped by purpose/meaning, not location."""
from __future__ import annotations

import json

from fastapi import APIRouter, Query

router = APIRouter(tags=["documents"])

# Map categories to purpose groups
_PURPOSE_GROUPS = {
    "Finance": {"categories": ["Finance", "Invoices", "Receipts"], "icon": "banknotes", "color": "emerald"},
    "Legal": {"categories": ["Legal"], "icon": "scale", "color": "red"},
    "Education": {"categories": ["Education"], "icon": "academic-cap", "color": "amber"},
    "Work": {"categories": ["Work"], "icon": "briefcase", "color": "blue"},
    "Personal": {"categories": ["Personal"], "icon": "heart", "color": "pink"},
    "Medical": {"categories": ["Medical"], "icon": "heart-pulse", "color": "rose"},
    "Other": {"categories": ["Documents", "Other", "Archives"], "icon": "folder", "color": "gray"},
}


@router.get("/documents")
async def get_document_groups():
    from tifaw.main import db

    d = db.db
    groups = []

    for name, config in _PURPOSE_GROUPS.items():
        placeholders = ",".join("?" for _ in config["categories"])
        row = await (await d.execute(
            f"SELECT COUNT(*) as count FROM files WHERE category IN ({placeholders}) AND status='indexed'",
            config["categories"],
        )).fetchone()

        if row["count"] == 0:
            continue

        # Get 3 recent files for preview
        recent_rows = await (await d.execute(
            f"""SELECT id, filename, extension, description, created_at FROM files
            WHERE category IN ({placeholders}) AND status='indexed'
            ORDER BY modified_at DESC LIMIT 3""",
            config["categories"],
        )).fetchall()

        groups.append({
            "name": name,
            "count": row["count"],
            "icon": config["icon"],
            "color": config["color"],
            "recent": [dict(r) for r in recent_rows],
        })

    groups.sort(key=lambda g: g["count"], reverse=True)
    return {"groups": groups}


@router.get("/documents/{group_name}")
async def get_document_group_files(
    group_name: str,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    from tifaw.main import db

    config = _PURPOSE_GROUPS.get(group_name)
    if not config:
        return {"files": [], "total": 0}

    d = db.db
    placeholders = ",".join("?" for _ in config["categories"])

    total_row = await (await d.execute(
        f"SELECT COUNT(*) as c FROM files WHERE category IN ({placeholders}) AND status='indexed'",
        config["categories"],
    )).fetchone()

    rows = await (await d.execute(
        f"""SELECT * FROM files WHERE category IN ({placeholders}) AND status='indexed'
        ORDER BY modified_at DESC LIMIT ? OFFSET ?""",
        config["categories"] + [limit, offset],
    )).fetchall()

    files = []
    for r in rows:
        f = dict(r)
        tags = f.get("tags")
        if isinstance(tags, str):
            try:
                f["tags"] = json.loads(tags)
            except Exception:
                f["tags"] = []
        files.append(f)

    return {"group": group_name, "files": files, "total": total_row["c"]}
