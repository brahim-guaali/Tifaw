from __future__ import annotations

import json
import logging
from typing import Any

from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5

SYSTEM_PROMPT = """\
You are **Tifaw**, a local AI file assistant running on the user's Mac.

You help users find, understand, and organize their files that have been indexed \
by the Tifaw system.  You have access to a set of tools that let you query the \
local file database.

Guidelines:
- When a user asks about files, USE the tools to look up real data — do NOT guess.
- You can chain multiple tool calls in a single turn if needed.
- After gathering information, synthesize a clear, concise answer.
- If no results are found, say so honestly.
- When the user asks about photos with specific people, first call `list_people` \
to find the correct label/name, then call `find_photos` with that name.
- For location queries, the location is searched in file descriptions, tags, and filenames.
- For date queries, you can use `year`, `date_from`, or `date_to` in `find_photos`.

IMPORTANT — Rich responses:
- When showing photos, include an image grid using this HTML format for EACH photo:
  <div class="chat-photo" data-id="FILE_ID"><img src="/api/files/FILE_ID/preview"></div>
  Wrap multiple photos in: <div class="chat-photo-grid">...</div>
- When showing file lists, use markdown tables or bullet lists.
- When showing stats or counts, use bold text.
- Always be friendly, concise, and helpful.
"""

# ---------------------------------------------------------------------------
# OpenAI-compatible tool schemas for Ollama
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Full-text search over indexed files. Use this when the user wants "
                "to find files by keyword, topic, or description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (keywords or phrase).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_photos",
            "description": (
                "Find photos by person, date range, location, or keyword. "
                "Use this when the user asks about photos with specific people, "
                "from specific times, or taken in specific places."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "person": {
                        "type": "string",
                        "description": "Name of a person to find in photos (must match a face label exactly).",
                    },
                    "year": {
                        "type": "integer",
                        "description": "Year the photo was taken (e.g. 2015).",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Place name to search for in descriptions, tags, and filenames.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Additional keyword to search (e.g. 'beach', 'wedding').",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_people",
            "description": (
                "List all recognized people in photos with their photo counts. "
                "Use this to find the correct name/label for a person before searching."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in a specific watched folder, optionally filtered by "
                "category (e.g. 'Images', 'Documents', 'Code', 'Personal', 'Work', etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "The watched folder path to list files from.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                    },
                },
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_file",
            "description": (
                "Get full details of a specific file by its database ID, including "
                "description, tags, category, metadata, path, size, and more."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "The database ID of the file.",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": (
                "Get system statistics: total files, indexed count, pending count, "
                "category breakdown, people count, and storage info."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Run a read-only SQL query against the database for advanced questions. "
                "Tables: files (id, path, filename, extension, size_bytes, category, "
                "description, tags, metadata, created_at, modified_at, status), "
                "faces (id, file_id, label, confidence), "
                "known_people (name, face_count), "
                "projects (path, name, description, stack). "
                "The metadata column is JSON with keys like: date_taken, gps_latitude, "
                "gps_longitude, camera_make, camera_model, image_width, image_height, "
                "iso, aperture, focal_length, author, title, page_count. "
                "Use json_extract(metadata, '$.key') to access metadata fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A SELECT SQL query. Only SELECT is allowed.",
                    },
                },
                "required": ["sql"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


async def _execute_tool(name: str, arguments: dict[str, Any], db: Database) -> str:
    """Run a tool and return a JSON-encoded result string."""
    try:
        if name == "search_files":
            query = arguments.get("query", "")
            results = await db.search_files(query, limit=10)
            items = [
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "path": r["path"],
                    "category": r.get("category"),
                    "description": r.get("description", ""),
                    "extension": r.get("extension"),
                    "created_at": r.get("created_at"),
                }
                for r in results
            ]
            return json.dumps({"count": len(items), "files": items})

        elif name == "find_photos":
            return await _find_photos(arguments, db)

        elif name == "list_people":
            return await _list_people(db)

        elif name == "list_files":
            folder = arguments.get("folder", "")
            category = arguments.get("category")
            results = await db.get_files(
                watch_folder=folder, category=category, limit=50
            )
            items = [
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "category": r.get("category"),
                    "description": (r.get("description") or "")[:120],
                    "extension": r.get("extension"),
                    "created_at": r.get("created_at"),
                    "status": r.get("status"),
                }
                for r in results
            ]
            return json.dumps({"count": len(items), "files": items})

        elif name == "describe_file":
            file_id = int(arguments.get("file_id", 0))
            file = await db.get_file(file_id)
            if file is None:
                return json.dumps({"error": f"No file found with id {file_id}"})
            metadata = file.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = None
            tags = file.get("tags")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []
            return json.dumps(
                {
                    "id": file["id"],
                    "filename": file["filename"],
                    "path": file["path"],
                    "extension": file.get("extension"),
                    "size_bytes": file.get("size_bytes"),
                    "category": file.get("category"),
                    "description": file.get("description"),
                    "tags": tags,
                    "content_preview": (file.get("content_preview") or "")[:300],
                    "metadata": metadata,
                    "status": file.get("status"),
                    "suggested_name": file.get("suggested_name"),
                    "created_at": file.get("created_at"),
                    "modified_at": file.get("modified_at"),
                }
            )

        elif name == "get_stats":
            stats = await db.get_stats()
            # Add more context
            d = db.db
            cats = await (await d.execute(
                """SELECT category, COUNT(*) as count FROM files
                WHERE status='indexed' AND category IS NOT NULL
                GROUP BY category ORDER BY count DESC"""
            )).fetchall()
            stats["categories"] = {r["category"]: r["count"] for r in cats}

            people = await (await d.execute(
                "SELECT COUNT(DISTINCT label) as c FROM faces WHERE label IS NOT NULL"
            )).fetchone()
            stats["people_count"] = people["c"]

            size = await (await d.execute(
                "SELECT SUM(size_bytes) as s FROM files WHERE status='indexed'"
            )).fetchone()
            stats["total_size_bytes"] = size["s"] or 0

            return json.dumps(stats)

        elif name == "query_database":
            return await _query_database(arguments, db)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})


async def _find_photos(arguments: dict[str, Any], db: Database) -> str:
    """Find photos with flexible filters: person, date, location, keyword."""
    d = db.db

    conditions = [
        "f.status = 'indexed'",
        "f.extension IN ('.png','.jpg','.jpeg','.gif','.webp','.bmp')",
    ]
    params: list[Any] = []
    join_faces = False

    person = arguments.get("person")
    if person:
        join_faces = True
        conditions.append("fa.label = ?")
        params.append(person)

    year = arguments.get("year")
    if year:
        conditions.append("f.created_at LIKE ?")
        params.append(f"{year}%")

    date_from = arguments.get("date_from")
    if date_from:
        conditions.append("f.created_at >= ?")
        params.append(date_from)

    date_to = arguments.get("date_to")
    if date_to:
        conditions.append("f.created_at <= ?")
        params.append(date_to + "T23:59:59")

    location = arguments.get("location")
    if location:
        loc_lower = f"%{location.lower()}%"
        conditions.append(
            "(LOWER(f.description) LIKE ? OR LOWER(f.tags) LIKE ? OR LOWER(f.filename) LIKE ?)"
        )
        params.extend([loc_lower, loc_lower, loc_lower])

    query = arguments.get("query")
    if query:
        q_lower = f"%{query.lower()}%"
        conditions.append(
            "(LOWER(f.description) LIKE ? OR LOWER(f.tags) LIKE ? OR LOWER(f.filename) LIKE ?)"
        )
        params.extend([q_lower, q_lower, q_lower])

    join_clause = "JOIN faces fa ON fa.file_id = f.id" if join_faces else ""
    where = " AND ".join(conditions)

    sql = f"""SELECT DISTINCT f.id, f.filename, f.path, f.description,
              f.created_at, f.category, f.tags
              FROM files f {join_clause}
              WHERE {where}
              ORDER BY f.created_at DESC LIMIT 20"""

    rows = await (await d.execute(sql, params)).fetchall()

    results = []
    for r in rows:
        # Get people in this photo
        people_rows = await (await d.execute(
            "SELECT DISTINCT label FROM faces WHERE file_id = ? AND label IS NOT NULL",
            (r["id"],),
        )).fetchall()
        people = [p["label"] for p in people_rows]

        tags = r["tags"]
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        results.append({
            "id": r["id"],
            "filename": r["filename"],
            "description": r["description"],
            "created_at": (r["created_at"] or "")[:10],
            "category": r["category"],
            "tags": tags,
            "people": people,
        })

    return json.dumps({"count": len(results), "photos": results})


async def _list_people(db: Database) -> str:
    """List all recognized people."""
    d = db.db
    rows = await (await d.execute(
        """SELECT label as name, COUNT(DISTINCT file_id) as photo_count
        FROM faces WHERE label IS NOT NULL
        GROUP BY label ORDER BY photo_count DESC"""
    )).fetchall()
    people = [{"name": r["name"], "photo_count": r["photo_count"]} for r in rows]
    return json.dumps({"count": len(people), "people": people})


async def _query_database(arguments: dict[str, Any], db: Database) -> str:
    """Run a read-only SQL query."""
    sql = arguments.get("sql", "").strip()
    if not sql:
        return json.dumps({"error": "No SQL provided"})

    # Safety: only allow SELECT
    if not sql.upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed"})

    # Block dangerous keywords
    upper = sql.upper()
    for kw in ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "ATTACH"):
        if kw in upper:
            return json.dumps({"error": f"Query contains forbidden keyword: {kw}"})

    try:
        d = db.db
        cursor = await d.execute(sql)
        rows = await cursor.fetchall()
        results = [dict(r) for r in rows[:50]]
        return json.dumps({"count": len(results), "rows": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def run_agent(
    user_message: str,
    db: Database,
    llm: OllamaClient,
) -> str:
    """Run the ReAct agent loop and return the final text response."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for iteration in range(MAX_ITERATIONS):
        logger.info("Agent iteration %d", iteration + 1)

        assistant_msg = await llm.chat(messages, tools=TOOLS, temperature=0.4)

        # Append the full assistant message to history
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls")
        if not tool_calls:
            # No tool calls — the model produced a final answer
            return assistant_msg.get("content", "")

        # Execute each tool call and append results
        for tc in tool_calls:
            fn = tc["function"]
            fn_name = fn["name"]
            fn_args = fn.get("arguments", {})
            if isinstance(fn_args, str):
                fn_args = json.loads(fn_args)

            logger.info("Tool call: %s(%s)", fn_name, fn_args)
            result = await _execute_tool(fn_name, fn_args, db)
            logger.info("Tool result preview: %s", result[:200])

            messages.append(
                {
                    "role": "tool",
                    "content": result,
                }
            )

    # If we exhausted iterations, return whatever the last assistant content was
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]

    return "I was unable to complete the request within the allowed number of steps."
