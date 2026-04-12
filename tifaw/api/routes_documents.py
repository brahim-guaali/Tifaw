"""Documents API — files grouped by purpose/meaning, not location."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

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

# Colors for dynamically discovered groups
_DYNAMIC_COLORS = ["indigo", "teal", "orange", "cyan", "violet", "lime", "fuchsia", "sky"]


async def _load_discovered_groups(d) -> list[dict]:
    """Load discovered groups from smart_folders table."""
    rows = await (await d.execute(
        "SELECT id, name, rule, icon FROM smart_folders ORDER BY created_at DESC"
    )).fetchall()
    groups = []
    for r in rows:
        try:
            rule = json.loads(r["rule"])
            groups.append({
                "id": r["id"],
                "name": r["name"],
                "tag": rule.get("tag", ""),
                "all_tags": rule.get("tags", []),
                "icon": r["icon"] or "",
                "color": _DYNAMIC_COLORS[r["id"] % len(_DYNAMIC_COLORS)],
            })
        except Exception:
            continue
    return groups


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

    # Add discovered dynamic groups from database
    discovered = await _load_discovered_groups(d)
    for dg in discovered:
        tag = dg["tag"]
        if not tag:
            continue
        row = await (await d.execute(
            "SELECT COUNT(*) as count FROM files WHERE status='indexed' AND tags LIKE ?",
            (f'%"{tag}"%',),
        )).fetchone()
        if row["count"] < 5:
            continue

        recent_rows = await (await d.execute(
            """SELECT id, filename, extension, description, created_at FROM files
            WHERE status='indexed' AND tags LIKE ?
            ORDER BY modified_at DESC LIMIT 3""",
            (f'%"{tag}"%',),
        )).fetchall()

        groups.append({
            "name": dg["name"],
            "count": row["count"],
            "icon": dg.get("icon", ""),
            "color": dg.get("color", "gray"),
            "recent": [dict(r) for r in recent_rows],
            "dynamic": True,
            "tag": tag,
        })

    groups.sort(key=lambda g: g["count"], reverse=True)
    return {"groups": groups}


@router.get("/documents/{group_name}")
async def get_document_group_files(
    group_name: str,
    tag: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    from tifaw.main import db

    d = db.db

    # Check if it's a hardcoded group
    config = _PURPOSE_GROUPS.get(group_name)
    if config:
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
    elif tag:
        # Dynamic group — query by tag
        total_row = await (await d.execute(
            "SELECT COUNT(*) as c FROM files WHERE status='indexed' AND tags LIKE ?",
            (f'%"{tag}"%',),
        )).fetchone()

        rows = await (await d.execute(
            """SELECT * FROM files WHERE status='indexed' AND tags LIKE ?
            ORDER BY modified_at DESC LIMIT ? OFFSET ?""",
            (f'%"{tag}"%', limit, offset),
        )).fetchall()
    else:
        return {"group": group_name, "files": [], "total": 0}

    files = []
    for r in rows:
        f = dict(r)
        tags_val = f.get("tags")
        if isinstance(tags_val, str):
            try:
                f["tags"] = json.loads(tags_val)
            except Exception:
                f["tags"] = []
        files.append(f)

    return {"group": group_name, "files": files, "total": total_row["c"]}


@router.post("/documents/discover")
async def discover_document_groups():
    """Use LLM to discover new document groups from tag patterns and save to DB."""
    from tifaw.main import db, llm

    d = db.db

    # Find tags that appear in 10+ files
    rows = await (await d.execute(
        "SELECT tags FROM files WHERE status='indexed' AND tags IS NOT NULL AND tags != '[]'"
    )).fetchall()

    # Count tag occurrences
    tag_counts: dict[str, int] = {}
    for row in rows:
        try:
            tags = json.loads(row["tags"])
            for tag in tags:
                tag = tag.strip().lower()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except Exception:
            continue

    # Filter to tags with 10+ files, exclude generic ones
    generic = {
        "document", "file", "image", "photo", "text", "personal", "work",
        "other", "screenshot", "code", "pdf", "data", "download", "scan",
    }
    frequent_tags = {
        tag: count for tag, count in tag_counts.items()
        if count >= 10 and tag not in generic and len(tag) > 2
    }

    if not frequent_tags:
        return {"discovered": 0, "groups": []}

    # Load existing discovered groups to avoid duplicates
    existing = await _load_discovered_groups(d)
    existing_tags = {dg["tag"] for dg in existing}

    # Ask LLM to name and group these tags
    tag_list = "\n".join(f"- {tag} ({count} files)" for tag, count in
                         sorted(frequent_tags.items(), key=lambda x: -x[1])[:30])

    prompt = f"""Here are tags found across many files on a user's laptop:

{tag_list}

Group related tags together and give each group a short, clear name (2-3 words max).
Only create groups for tags that represent a meaningful document category like "Travel Bookings", "Plane Tickets", "Hotel Reservations", "Tax Documents", "ID Documents", "Insurance", "Contracts", "CVs & Resumes", etc.

Skip generic tags that don't form a useful group.

Respond with ONLY a JSON array of objects:
[{{"name": "Group Name", "tags": ["tag1", "tag2"], "icon": "emoji"}}]

Use a single relevant emoji for the icon field."""

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system="You are a file organization assistant. Respond with ONLY valid JSON.",
        )

        if isinstance(result, dict) and "groups" in result:
            result = result["groups"]
        if not isinstance(result, list):
            result = []

        new_count = 0
        for group in result:
            if not isinstance(group, dict):
                continue
            name = group.get("name", "").strip()
            tags = group.get("tags", [])
            icon = group.get("icon", "")
            if not name or not tags:
                continue

            # Pick the most frequent tag as the primary query tag
            primary_tag = max(tags, key=lambda t: frequent_tags.get(t, 0))

            # Skip if this tag is already saved
            if primary_tag in existing_tags:
                continue

            # Save to smart_folders table
            rule = json.dumps({"tag": primary_tag, "tags": tags})
            await d.execute(
                "INSERT INTO smart_folders (name, rule, icon) VALUES (?, ?, ?)",
                (name, rule, icon),
            )
            existing_tags.add(primary_tag)
            new_count += 1

        await d.commit()
        logger.info("Discovered and saved %d new document groups", new_count)

        # Return all groups (existing + new)
        all_groups = await _load_discovered_groups(d)
        return {"discovered": new_count, "groups": all_groups}

    except Exception as e:
        logger.error("Failed to discover document groups: %s", e)
        return {"discovered": 0, "groups": [], "error": str(e)}


@router.delete("/documents/groups/{group_id}")
async def delete_discovered_group(group_id: int):
    """Delete a discovered document group."""
    from tifaw.main import db

    await db.db.execute("DELETE FROM smart_folders WHERE id=?", (group_id,))
    await db.db.commit()
    return {"status": "deleted", "id": group_id}
