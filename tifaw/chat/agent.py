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
- When listing files, include the filename, category, and a short description.
- Be friendly, concise, and helpful.
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
            "name": "list_files",
            "description": (
                "List files in a specific watched folder, optionally filtered by "
                "category (e.g. 'Image', 'Document', 'Code', etc.)."
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
                        "description": "Optional category filter (e.g. 'Image', 'Document').",
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
                "description, tags, category, path, size, and more."
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
                "Get system statistics: total files tracked, how many are indexed, "
                "how many are pending analysis, and pending renames."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
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
                }
                for r in results
            ]
            return json.dumps({"count": len(items), "files": items})

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
            # Return a useful subset
            return json.dumps(
                {
                    "id": file["id"],
                    "filename": file["filename"],
                    "path": file["path"],
                    "extension": file.get("extension"),
                    "size_bytes": file.get("size_bytes"),
                    "category": file.get("category"),
                    "description": file.get("description"),
                    "tags": file.get("tags"),
                    "content_preview": (file.get("content_preview") or "")[:300],
                    "status": file.get("status"),
                    "suggested_name": file.get("suggested_name"),
                    "created_at": file.get("created_at"),
                    "modified_at": file.get("modified_at"),
                }
            )

        elif name == "get_stats":
            stats = await db.get_stats()
            return json.dumps(stats)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})


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
