"""Overview / Story dashboard API — aggregates the user's digital life into a narrative."""
from __future__ import annotations

import json

from fastapi import APIRouter

router = APIRouter(tags=["overview"])


@router.get("/overview")
async def get_overview():
    from tifaw.main import db

    d = db.db

    # Core stats
    row = (await (await d.execute(
        "SELECT COUNT(*) as total, SUM(size_bytes) as size FROM files WHERE status='indexed'"
    )).fetchone())
    total_files = row["total"]
    total_size = row["size"] or 0

    # Date span
    span = (await (await d.execute(
        "SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM files WHERE created_at IS NOT NULL"
    )).fetchone())
    earliest = (span["earliest"] or "")[:4]
    latest = (span["latest"] or "")[:4]
    year_span = int(latest) - int(earliest) + 1 if earliest and latest else 0

    # Categories breakdown
    cats = await (await d.execute(
        """SELECT category, COUNT(*) as count, SUM(size_bytes) as size
        FROM files WHERE status='indexed' AND category IS NOT NULL
        GROUP BY category ORDER BY count DESC"""
    )).fetchall()
    categories = [{"name": r["category"], "count": r["count"], "size": r["size"] or 0} for r in cats]

    # Photos with people
    photos_with_faces = (await (await d.execute(
        "SELECT COUNT(DISTINCT file_id) as c FROM faces"
    )).fetchone())["c"]
    unique_people = (await (await d.execute(
        "SELECT COUNT(DISTINCT label) as c FROM faces WHERE label IS NOT NULL AND label NOT LIKE 'Person %'"
    )).fetchone())["c"]
    total_people = (await (await d.execute(
        "SELECT COUNT(DISTINCT label) as c FROM faces WHERE label IS NOT NULL"
    )).fetchone())["c"]

    # Total images
    total_images = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files WHERE extension IN ('.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg') AND status='indexed'"
    )).fetchone())["c"]

    # Documents count
    total_docs = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files WHERE extension IN ('.pdf','.docx','.xlsx','.txt','.md','.csv') AND status='indexed'"
    )).fetchone())["c"]

    # Projects
    total_projects = (await (await d.execute(
        "SELECT COUNT(*) as c FROM projects"
    )).fetchone())["c"]

    # Education/certificates
    edu_count = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files WHERE status='indexed' AND (category='Education' OR tags LIKE '%certificate%' OR tags LIKE '%diploma%')"
    )).fetchone())["c"]

    # Screenshots
    screenshots = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files WHERE category='Screenshots' AND status='indexed'"
    )).fetchone())["c"]

    # Story cards
    story_cards = []
    if total_images > 0:
        label = f"photos"
        if total_people > 0:
            label += f" with {total_people} people identified"
        story_cards.append({
            "type": "photos", "count": total_images,
            "label": label, "icon": "camera", "link": "photos",
            "color": "blue",
        })
    if total_docs > 0:
        story_cards.append({
            "type": "documents", "count": total_docs,
            "label": "documents to explore",
            "icon": "file-text", "link": "documents", "color": "emerald",
        })
    if total_projects > 0:
        story_cards.append({
            "type": "projects", "count": total_projects,
            "label": "code projects",
            "icon": "code", "link": "projects", "color": "violet",
        })
    if edu_count > 0:
        story_cards.append({
            "type": "education", "count": edu_count,
            "label": "certificates & education files",
            "icon": "award", "link": "documents", "color": "amber",
        })
    if screenshots > 0:
        story_cards.append({
            "type": "screenshots", "count": screenshots,
            "label": "screenshots captured",
            "icon": "monitor", "link": "photos", "color": "slate",
        })

    # Timeline (monthly file counts)
    timeline_rows = await (await d.execute(
        """SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count
        FROM files WHERE status='indexed' AND created_at IS NOT NULL
        GROUP BY month ORDER BY month"""
    )).fetchall()
    timeline = [{"month": r["month"], "count": r["count"]} for r in timeline_rows if r["month"]]

    # Recent highlights
    recent_rows = await (await d.execute(
        "SELECT * FROM files WHERE status='indexed' ORDER BY indexed_at DESC LIMIT 8"
    )).fetchall()
    recent = []
    for r in recent_rows:
        f = dict(r)
        tags = f.get("tags")
        if isinstance(tags, str):
            try:
                f["tags"] = json.loads(tags)
            except Exception:
                f["tags"] = []
        recent.append(f)

    # Storage by folder
    folder_rows = await (await d.execute(
        """SELECT watch_folder, COUNT(*) as count, SUM(size_bytes) as size
        FROM files WHERE watch_folder IS NOT NULL
        GROUP BY watch_folder ORDER BY count DESC"""
    )).fetchall()
    folders = [{"path": r["watch_folder"], "count": r["count"], "size": r["size"] or 0} for r in folder_rows]

    return {
        "total_files": total_files,
        "total_size": total_size,
        "year_span": {"earliest": earliest, "latest": latest, "years": year_span},
        "story_cards": story_cards,
        "categories": categories,
        "timeline": timeline,
        "recent": recent,
        "folders": folders,
        "people_count": total_people,
        "photos_with_faces": photos_with_faces,
    }
