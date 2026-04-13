from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3

SYSTEM_PROMPT = """\
You are **Tifaw**, a local AI file assistant running on the user's Mac.

You help users find, understand, and organize their files — including photos, \
documents, code, screenshots, and all other file types. Real data from the database \
is provided below your question.

Guidelines:
- Use the provided database data to answer — do NOT guess or make up files.
- If no results are found, say so honestly.
- Be friendly, concise, and helpful.
- ALWAYS use the HTML widget formats below when listing files — never use plain text lists.
- NEVER delete files without explicit user confirmation. List the files first and ask. \
Only when the user confirms, respond with DELETE_CONFIRMED:[id1,id2,id3].

FILE DISPLAY FORMATS (use these EXACTLY):

For photos/images, use the photo grid:
<div class="chat-photo-grid"><div class="chat-photo"><img src="/api/files/ID/preview"></div></div>

For documents, PDFs, code, and other non-image files, use file cards:
<div class="chat-file-list">\
<div class="chat-file-card" onclick="window.dispatchEvent(new CustomEvent('chat-open-file',{detail:ID}))">\
<div class="chat-file-icon">EMOJI</div>\
<div class="chat-file-info"><div class="chat-file-name">FILENAME</div>\
<div class="chat-file-desc">SHORT_DESCRIPTION</div></div></div></div>

Replace ID with the file's database id, EMOJI with a file type emoji \
(📄 for PDF, 📝 for text, 🐍 for Python, 📊 for spreadsheet, etc), \
FILENAME with the actual filename, and SHORT_DESCRIPTION with a brief description.

You can mix photo grids and file cards in the same response. \
Group photos together in one grid block, and files together in one file list block.
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
                "Run a read-only SELECT query. Tables: files(id,filename,category,description,tags,metadata,created_at), "
                "faces(file_id,label), known_people(name,face_count), projects(name,stack). "
                "metadata is JSON: use json_extract(metadata,'$.key')."
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
    {
        "type": "function",
        "function": {
            "name": "delete_files",
            "description": (
                "Delete files by their database IDs. Files are moved to Trash by default. "
                "IMPORTANT: Only call this AFTER you have listed the files and the user "
                "has explicitly confirmed they want to delete them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of file database IDs to delete.",
                    },
                },
                "required": ["file_ids"],
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

        elif name == "delete_files":
            return await _delete_files(arguments, db)

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


async def _delete_files(arguments: dict[str, Any], db: Database) -> str:
    """Delete files by ID, moving them to Trash."""
    file_ids = arguments.get("file_ids", [])
    if not file_ids:
        return json.dumps({"error": "No file IDs provided"})

    from tifaw.cleanup.stale import delete_files
    result = await delete_files(file_ids, db)
    return json.dumps(result)


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


async def _gather_context(user_message: str, db: Database) -> str:
    """Pre-fetch relevant data based on the user's question to include in the prompt."""
    context_parts = []
    msg_lower = user_message.lower().strip()

    # Skip context gathering for simple greetings/conversational messages
    greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yes", "no",
                 "sure", "bye", "good", "great", "nice", "cool", "wow"}
    if msg_lower in greetings or len(msg_lower) < 4:
        return ""

    # Include basic stats
    stats = await db.get_stats()
    context_parts.append(f"System: {stats['total_files']} files, {stats['indexed_files']} indexed.")

    # Search for relevant files
    stop_words = {
        "the", "and", "for", "from", "with", "that", "this", "all", "are",
        "can", "you", "want", "delete", "show", "find", "get", "have", "help",
        "please", "what", "where", "when", "how", "who", "which", "my", "me",
        "our", "your", "their", "some", "any", "about", "like", "just", "also",
    }
    keywords = [w for w in msg_lower.split() if len(w) > 2 and w not in stop_words]
    if keywords:
        query = " ".join(keywords[:3])
        results = await db.search_files(query, limit=10)
        if results:
            files_info = []
            for r in results:
                files_info.append(
                    f"  - [id={r['id']}] {r['filename']} (category: {r.get('category')}, "
                    f"desc: {(r.get('description') or '')[:80]})"
                )
            context_parts.append(f"Search results for '{query}':\n" + "\n".join(files_info))

    # If asking about people
    if any(w in msg_lower for w in ["people", "person", "who", "face", "photo"]):
        d = db.db
        rows = await (await d.execute(
            "SELECT label, COUNT(DISTINCT file_id) as count FROM faces "
            "WHERE label IS NOT NULL AND label NOT LIKE 'Person %' "
            "GROUP BY label ORDER BY count DESC LIMIT 10"
        )).fetchall()
        if rows:
            people = [f"  - {r['label']} ({r['count']} photos)" for r in rows]
            context_parts.append("Known people:\n" + "\n".join(people))

    # If asking about categories/types
    if any(w in msg_lower for w in ["category", "type", "kind", "screenshot", "document", "image"]):
        d = db.db
        cats = await (await d.execute(
            "SELECT category, COUNT(*) as count FROM files WHERE status='indexed' "
            "AND category IS NOT NULL GROUP BY category ORDER BY count DESC"
        )).fetchall()
        cat_info = [f"  - {r['category']}: {r['count']} files" for r in cats]
        context_parts.append("Categories:\n" + "\n".join(cat_info))

    # If asking about screenshots specifically
    if "screenshot" in msg_lower:
        d = db.db
        rows = await (await d.execute(
            "SELECT id, filename, description, created_at FROM files "
            "WHERE category='Screenshots' AND status='indexed' "
            "ORDER BY created_at DESC LIMIT 20"
        )).fetchall()
        if rows:
            ss = [f"  - [id={r['id']}] {r['filename']} ({(r['created_at'] or '')[:10]})" for r in rows]
            context_parts.append(f"Screenshots ({len(rows)} shown of total):\n" + "\n".join(ss))

    # If asking to delete — include a reminder
    if any(w in msg_lower for w in ["delete", "remove", "clean", "trash"]):
        context_parts.append(
            "DELETE CAPABILITY: You can delete files. List the files first, "
            "then ask the user to confirm. If they confirm, respond with exactly: "
            "DELETE_CONFIRMED:[id1,id2,id3] and the system will handle the deletion."
        )

    return "\n\n".join(context_parts)


async def run_agent(
    user_message: str,
    db: Database,
    llm: OllamaClient,
) -> str:
    """Run the chat agent with pre-fetched context (no tool calling for speed)."""
    # Get user identity
    system = SYSTEM_PROMPT
    try:
        cursor = await db.db.execute("SELECT value FROM settings WHERE key='user_identity'")
        row = await cursor.fetchone()
        if row and row["value"]:
            system += f"\n\nThe user's name is {row['value']}. Address them by name when appropriate."
    except Exception:
        pass

    # Pre-fetch relevant context
    context = await _gather_context(user_message, db)

    prompt = user_message
    if context:
        prompt = f"{user_message}\n\n--- DATA FROM YOUR DATABASE ---\n{context}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    logger.info("Chat request: %s (context: %d chars)", user_message[:100], len(context))

    assistant_msg = await llm.chat(messages, temperature=0.4)
    response = assistant_msg.get("content", "")

    # Check for delete confirmation pattern
    if "DELETE_CONFIRMED:" in response:
        try:
            import re
            match = re.search(r'DELETE_CONFIRMED:\[([^\]]+)\]', response)
            if match:
                ids = [int(x.strip()) for x in match.group(1).split(",")]
                result = await _delete_files({"file_ids": ids}, db)
                result_data = json.loads(result)
                deleted = result_data.get("deleted", 0)
                # Remove the delete command from response and add result
                response = re.sub(r'DELETE_CONFIRMED:\[[^\]]+\]', '', response).strip()
                response += f"\n\nDone! Moved {deleted} file(s) to Trash."
        except Exception as e:
            logger.error("Delete from chat failed: %s", e)

    return response


async def run_agent_stream(
    user_message: str,
    db: Database,
    llm: OllamaClient,
) -> AsyncGenerator[str, None]:
    """Stream chat agent response token by token, yielding status updates and content chunks."""
    # Get user identity
    system = SYSTEM_PROMPT
    try:
        cursor = await db.db.execute("SELECT value FROM settings WHERE key='user_identity'")
        row = await cursor.fetchone()
        if row and row["value"]:
            system += f"\n\nThe user's name is {row['value']}. Address them by name when appropriate."
    except Exception:
        pass

    yield json.dumps({"type": "status", "text": "Searching your files..."}) + "\n"

    # Pre-fetch relevant context
    context = await _gather_context(user_message, db)

    prompt = user_message
    if context:
        prompt = f"{user_message}\n\n--- DATA FROM YOUR DATABASE ---\n{context}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    logger.info("Chat stream: %s (context: %d chars)", user_message[:100], len(context))

    yield json.dumps({"type": "status", "text": "Generating response..."}) + "\n"

    full_response = ""
    async for chunk in llm.chat_stream(messages):
        content = chunk.get("message", {}).get("content", "")
        if content:
            full_response += content
            yield json.dumps({"type": "token", "text": content}) + "\n"

    # Check for delete confirmation pattern
    if "DELETE_CONFIRMED:" in full_response:
        try:
            import re
            match = re.search(r'DELETE_CONFIRMED:\[([^\]]+)\]', full_response)
            if match:
                ids = [int(x.strip()) for x in match.group(1).split(",")]
                result = await _delete_files({"file_ids": ids}, db)
                result_data = json.loads(result)
                deleted = result_data.get("deleted", 0)
                yield json.dumps({"type": "token", "text": f"\n\nDone! Moved {deleted} file(s) to Trash."}) + "\n"
        except Exception as e:
            logger.error("Delete from chat failed: %s", e)

    yield json.dumps({"type": "done"}) + "\n"
