"""Overview / Story dashboard API — aggregates the user's digital life into a narrative."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

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
        "SELECT MIN(created_at) as earliest, "
        "MAX(created_at) as latest "
        "FROM files WHERE created_at IS NOT NULL"
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
    categories = [
        {"name": r["category"], "count": r["count"],
         "size": r["size"] or 0}
        for r in cats
    ]

    # Photos with people
    photos_with_faces = (await (await d.execute(
        "SELECT COUNT(DISTINCT file_id) as c FROM faces"
    )).fetchone())["c"]
    total_people = (await (await d.execute(
        "SELECT COUNT(DISTINCT label) as c FROM faces WHERE label IS NOT NULL"
    )).fetchone())["c"]

    # Total images
    total_images = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files "
        "WHERE extension IN "
        "('.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg') "
        "AND status='indexed'"
    )).fetchone())["c"]

    # Documents count
    total_docs = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files "
        "WHERE extension IN "
        "('.pdf','.docx','.xlsx','.txt','.md','.csv') "
        "AND status='indexed'"
    )).fetchone())["c"]

    # Projects
    total_projects = (await (await d.execute(
        "SELECT COUNT(*) as c FROM projects"
    )).fetchone())["c"]

    # Education/certificates
    edu_count = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files "
        "WHERE status='indexed' AND "
        "(category='Education' OR tags LIKE '%certificate%' "
        "OR tags LIKE '%diploma%')"
    )).fetchone())["c"]

    # Screenshots
    screenshots = (await (await d.execute(
        "SELECT COUNT(*) as c FROM files WHERE category='Screenshots' AND status='indexed'"
    )).fetchone())["c"]

    # Story cards
    story_cards = []
    if total_images > 0:
        label = "photos"
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
    folders = [
        {"path": r["watch_folder"], "count": r["count"],
         "size": r["size"] or 0}
        for r in folder_rows
    ]

    # Photo locations (GPS from metadata)
    loc_rows = await (await d.execute(
        """SELECT id, filename,
           json_extract(metadata, '$.gps_latitude') as lat,
           json_extract(metadata, '$.gps_longitude') as lng
        FROM files WHERE metadata IS NOT NULL
          AND json_extract(metadata, '$.gps_latitude') IS NOT NULL
          AND status='indexed'
        LIMIT 500"""
    )).fetchall()
    photo_locations = [{"id": r["id"], "filename": r["filename"],
                        "lat": r["lat"], "lng": r["lng"]} for r in loc_rows]

    # Years that have indexed activity — let the frontend
    # decide which year to load lazily via /overview/heatmap.
    year_rows = await (await d.execute(
        """SELECT DISTINCT CAST(SUBSTR(created_at, 1, 4) AS INT) as y
        FROM files
        WHERE status='indexed' AND created_at IS NOT NULL
        ORDER BY y DESC"""
    )).fetchall()
    available_years = [r["y"] for r in year_rows if r["y"]]
    calendar_heatmap = {}  # populated lazily by the client

    # People co-occurrence
    cooc_rows = await (await d.execute(
        """SELECT f1.label as person_a, f2.label as person_b,
           COUNT(DISTINCT f1.file_id) as together
        FROM faces f1 JOIN faces f2
          ON f1.file_id = f2.file_id AND f1.label < f2.label
        WHERE f1.label IS NOT NULL AND f2.label IS NOT NULL
        GROUP BY f1.label, f2.label ORDER BY together DESC LIMIT 10"""
    )).fetchall()
    people_cooccurrence = [{"person_a": r["person_a"], "person_b": r["person_b"],
                            "together": r["together"]} for r in cooc_rows]

    # Top stats
    top_stats = {}

    # Largest file
    largest = await (await d.execute(
        "SELECT filename, size_bytes FROM files "
        "WHERE status='indexed' "
        "ORDER BY size_bytes DESC LIMIT 1"
    )).fetchone()
    if largest:
        top_stats["largest_file"] = {
            "name": largest["filename"],
            "size": largest["size_bytes"] or 0,
        }

    # Most photographed person
    top_person = await (await d.execute(
        """SELECT label, COUNT(DISTINCT file_id) as count FROM faces
        WHERE label IS NOT NULL GROUP BY label ORDER BY count DESC LIMIT 1"""
    )).fetchone()
    if top_person:
        top_stats["most_seen_person"] = {"name": top_person["label"], "count": top_person["count"]}

    # Oldest file
    oldest = await (await d.execute(
        "SELECT filename, created_at FROM files "
        "WHERE created_at IS NOT NULL "
        "ORDER BY created_at ASC LIMIT 1"
    )).fetchone()
    if oldest:
        top_stats["oldest_file"] = {
            "name": oldest["filename"],
            "date": (oldest["created_at"] or "")[:10],
        }

    # Most active month (from timeline)
    if timeline:
        best = max(timeline, key=lambda t: t["count"])
        top_stats["busiest_month"] = {"month": best["month"], "count": best["count"]}

    # Most used camera
    camera_row = await (await d.execute(
        """SELECT json_extract(metadata, '$.camera_model') as camera, COUNT(*) as count
        FROM files WHERE metadata IS NOT NULL
          AND json_extract(metadata, '$.camera_model') IS NOT NULL
        GROUP BY camera ORDER BY count DESC LIMIT 1"""
    )).fetchone()
    if camera_row and camera_row["camera"]:
        top_stats["top_camera"] = {"name": camera_row["camera"], "count": camera_row["count"]}

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
        "photo_locations": photo_locations,
        "calendar_heatmap": calendar_heatmap,
        "heatmap_years": available_years,
        "people_cooccurrence": people_cooccurrence,
        "top_stats": top_stats,
    }


@router.get("/overview/heatmap")
async def get_heatmap(year: int | None = None):
    """Return per-day file counts for *year* (default: current year)."""
    from tifaw.main import db

    d = db.db
    from datetime import datetime

    if not year:
        year = datetime.now().year

    rows = await (await d.execute(
        """SELECT DATE(created_at) as day, COUNT(*) as count
        FROM files
        WHERE status='indexed' AND created_at IS NOT NULL
          AND CAST(SUBSTR(created_at, 1, 4) AS INT) = ?
        GROUP BY day ORDER BY day""",
        (year,),
    )).fetchall()
    days = {r["day"]: r["count"] for r in rows if r["day"]}

    year_rows = await (await d.execute(
        """SELECT DISTINCT CAST(SUBSTR(created_at, 1, 4) AS INT) as y
        FROM files
        WHERE status='indexed' AND created_at IS NOT NULL
        ORDER BY y DESC"""
    )).fetchall()
    available = [r["y"] for r in year_rows if r["y"]]

    return {
        "year": year,
        "days": days,
        "total": sum(days.values()),
        "available_years": available,
    }


@router.get("/overview/narrative")
async def get_narrative():
    """Generate an AI narrative about the user's digital life."""
    from tifaw.main import db, llm

    d = db.db

    # Fetch current indexed file count
    row = await (await d.execute(
        "SELECT COUNT(*) as total, SUM(size_bytes) as size "
        "FROM files WHERE status='indexed'"
    )).fetchone()
    current_total = row["total"]

    # Check cache — invalidate if file count drifted > 10% from cached
    cached = await (await d.execute(
        "SELECT value FROM settings WHERE key='ai_narrative'"
    )).fetchone()
    if cached:
        data = json.loads(cached["value"])
        cached_total = (data.get("stats") or {}).get("total_files", 0)
        drift = abs(current_total - cached_total)
        threshold = max(100, cached_total * 0.1)
        if drift < threshold:
            return data
        # otherwise fall through to regenerate

    # Get user identity early (needed for filtering)
    user_row = await (await d.execute(
        "SELECT value FROM settings "
        "WHERE key='user_identity'"
    )).fetchone()
    user_name = user_row["value"] if user_row else None

    # Gather stats for the LLM
    stats = {}
    stats["total_files"] = current_total

    span = await (await d.execute(
        "SELECT MIN(created_at) as earliest, "
        "MAX(created_at) as latest "
        "FROM files WHERE created_at IS NOT NULL"
    )).fetchone()
    stats["earliest_year"] = (span["earliest"] or "")[:4]
    stats["latest_year"] = (span["latest"] or "")[:4]

    cats = await (await d.execute(
        "SELECT category, COUNT(*) as count FROM files "
        "WHERE status='indexed' AND category IS NOT NULL "
        "GROUP BY category ORDER BY count DESC LIMIT 5"
    )).fetchall()
    stats["top_categories"] = {r["category"]: r["count"] for r in cats}

    top_person = await (await d.execute(
        "SELECT label, COUNT(DISTINCT file_id) as count "
        "FROM faces WHERE label IS NOT NULL "
        "AND label NOT LIKE 'Person %' "
        "GROUP BY label ORDER BY count DESC LIMIT 5"
    )).fetchall()
    # Exclude the user themselves from "top people" so the LLM talks about others
    stats["top_people"] = {r["label"]: r["count"] for r in top_person if r["label"] != user_name}
    # Limit to 3 after filtering
    if len(stats["top_people"]) > 3:
        stats["top_people"] = dict(list(stats["top_people"].items())[:3])

    locations = await (await d.execute(
        """SELECT json_extract(metadata, '$.location_city')
           as city, COUNT(*) as count
        FROM files WHERE metadata IS NOT NULL
          AND json_extract(metadata, '$.location_city')
              IS NOT NULL
        GROUP BY city ORDER BY count DESC LIMIT 5"""
    )).fetchall()
    stats["top_locations"] = {r["city"]: r["count"] for r in locations}

    camera = await (await d.execute(
        "SELECT json_extract(metadata, '$.camera_model') as cam, "
        "COUNT(*) as count FROM files "
        "WHERE json_extract(metadata, '$.camera_model') "
        "IS NOT NULL "
        "GROUP BY cam ORDER BY count DESC LIMIT 1"
    )).fetchone()
    if camera and camera["cam"]:
        stats["top_camera"] = camera["cam"]

    if user_name:
        stats["user_name"] = user_name

    try:
        if user_name:
            address = (
                f"The user's name is {user_name}. "
                "Address them as 'you'. "
                f"If {user_name} appears in the top_people "
                "list, that IS the user — don't mention them "
                "as a third person. Focus on OTHER people "
                "they share photos with."
            )
        else:
            address = "Address the user in second person ('you')."
        text = await llm.generate(
            prompt=(
                "Here are statistics about a user's "
                "digital life:\n"
                f"{json.dumps(stats, indent=2)}\n\n"
                "Write a warm, personalized 2-3 sentence "
                "narrative summarizing their digital life. "
                "Be specific — mention other people's names,"
                " places, and numbers. Don't start with "
                "'Your digital world' — be creative. "
                f"{address}"
            ),
            system=(
                "You are Tifaw, a personal AI assistant. "
                "Write a brief, warm narrative. "
                "No markdown formatting."
            ),
            temperature=0.6,
        )
        result = {"narrative": text.strip(), "stats": stats}
        await d.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("ai_narrative", json.dumps(result)),
        )
        await d.commit()
        return result
    except Exception as e:
        logger.error("Narrative generation failed: %s", e)
        return {"narrative": None, "error": str(e)}


@router.post("/overview/narrative/refresh")
async def refresh_narrative():
    """Force refresh the AI narrative."""
    from tifaw.main import db
    await db.db.execute("DELETE FROM settings WHERE key='ai_narrative'")
    await db.db.commit()
    return await get_narrative()


@router.get("/overview/photo-stories")
async def get_photo_stories():
    """Generate AI story cards from photo clusters (by month + location)."""
    from tifaw.main import db, llm

    d = db.db

    # Check cache
    cached = await (await d.execute(
        "SELECT value FROM settings WHERE key='ai_photo_stories'"
    )).fetchone()
    if cached:
        return json.loads(cached["value"])

    # Group photos by month + location
    clusters = await (await d.execute(
        """SELECT SUBSTR(f.created_at, 1, 7) as month,
           json_extract(f.metadata, '$.location_city') as city,
           json_extract(f.metadata, '$.location_country') as country,
           COUNT(*) as count,
           MIN(f.id) as sample_id
        FROM files f
        WHERE f.status='indexed'
          AND f.extension IN ('.png','.jpg','.jpeg','.gif','.webp','.bmp')
          AND f.created_at IS NOT NULL
        GROUP BY month, city
        HAVING count >= 5
        ORDER BY count DESC
        LIMIT 8"""
    )).fetchall()

    if not clusters:
        return {"stories": []}

    # For each cluster, get people
    stories_input = []
    for c in clusters:
        people_rows = await (await d.execute(
            """SELECT DISTINCT fa.label FROM faces fa
            JOIN files f ON f.id = fa.file_id
            WHERE SUBSTR(f.created_at, 1, 7) = ?
            AND fa.label IS NOT NULL
            AND fa.label NOT LIKE 'Person %'""",
            (c["month"],),
        )).fetchall()
        people = [r["label"] for r in people_rows]

        stories_input.append({
            "month": c["month"],
            "city": c["city"],
            "country": c["country"],
            "count": c["count"],
            "people": people[:5],
            "sample_id": c["sample_id"],
        })

    # Ask LLM to generate story titles
    try:
        prompt = f"""Generate a short, evocative title (5-8 words) for each of these photo clusters:

{json.dumps(stories_input, indent=2)}

Respond with ONLY a JSON array of objects: [{{"index": 0, "title": "..."}}]"""

        titles = await llm.generate_json(
            prompt=prompt,
            system=(
                "You are a creative photo storyteller. "
                "Generate short, warm titles for photo "
                "collections. Respond with ONLY valid JSON."
            ),
        )

        if isinstance(titles, dict) and "titles" in titles:
            titles = titles["titles"]
        if not isinstance(titles, list):
            titles = []

        title_map = {t.get("index", i): t.get("title", "") for i, t in enumerate(titles)}

        stories = []
        for i, s in enumerate(stories_input):
            stories.append({
                "title": title_map.get(i, f"{s['month']} in {s.get('city') or 'Unknown'}"),
                "month": s["month"],
                "city": s.get("city"),
                "country": s.get("country"),
                "count": s["count"],
                "people": s["people"],
                "sample_id": s["sample_id"],
            })

        result = {"stories": stories}
        await d.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("ai_photo_stories", json.dumps(result)),
        )
        await d.commit()
        return result
    except Exception as e:
        logger.error("Photo stories failed: %s", e)
        return {"stories": [], "error": str(e)}


@router.get("/overview/digest")
async def get_weekly_digest():
    """Generate an AI weekly digest of recent file activity."""
    from tifaw.main import db, llm

    d = db.db

    # Check cache (refresh if older than 24h)
    cached = await (await d.execute(
        "SELECT value FROM settings WHERE key='ai_digest'"
    )).fetchone()
    if cached:
        data = json.loads(cached["value"])
        # Check if fresh enough (within 24h)
        from datetime import datetime, timezone
        cached_at = data.get("generated_at", "")
        if cached_at:
            try:
                age = (
                    datetime.now(tz=timezone.utc)
                    - datetime.fromisoformat(cached_at)
                ).total_seconds()
                if age < 86400:  # 24 hours
                    return data
            except Exception:
                pass

    # Gather last 7 days of activity
    rows = await (await d.execute(
        """SELECT category, COUNT(*) as count FROM files
        WHERE status='indexed' AND indexed_at >= date('now', '-7 days')
        GROUP BY category ORDER BY count DESC"""
    )).fetchall()
    weekly_cats = {r["category"]: r["count"] for r in rows}

    total_new = sum(weekly_cats.values())
    if total_new == 0:
        return {"digest": "No new files this week.", "total_new": 0}

    # New people detected
    new_people = await (await d.execute(
        """SELECT COUNT(DISTINCT label) as c FROM faces
        WHERE detected_at >= date('now', '-7 days') AND label IS NOT NULL"""
    )).fetchone()

    stats = {
        "total_new_files": total_new,
        "categories": weekly_cats,
        "new_people_detected": new_people["c"],
    }

    try:
        text = await llm.generate(
            prompt=(
                "Summarize this week's file activity "
                "in 2-3 sentences:\n"
                f"{json.dumps(stats, indent=2)}"
            ),
            system=(
                "You are Tifaw, a friendly AI file "
                "assistant. Write a brief, informative "
                "weekly summary. No markdown."
            ),
            temperature=0.5,
        )

        from datetime import datetime, timezone
        result = {
            "digest": text.strip(),
            "total_new": total_new,
            "categories": weekly_cats,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        await d.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("ai_digest", json.dumps(result)),
        )
        await d.commit()
        return result
    except Exception as e:
        logger.error("Digest generation failed: %s", e)
        return {"digest": None, "error": str(e)}
