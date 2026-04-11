# API Reference

Tifaw (ⵜⵉⴼⴰⵡ) exposes a JSON REST API at `http://127.0.0.1:8321/api`. All endpoints accept and return `application/json`.

Interactive documentation is available at [http://127.0.0.1:8321/docs](http://127.0.0.1:8321/docs) (Swagger UI) when the server is running.

---

## Status

### GET /api/status

Returns system health and summary statistics.

**Response**

```json
{
  "ollama_connected": true,
  "model_available": true,
  "total_files": 247,
  "indexed_files": 231,
  "pending_files": 16,
  "pending_renames": 5,
  "queue_size": 3,
  "watched_folders": [
    "/Users/you/Downloads",
    "/Users/you/Desktop",
    "/Users/you/Documents"
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `ollama_connected` | bool | Whether Ollama is reachable at the configured URL |
| `model_available` | bool | Whether gemma4:e4b is pulled and ready |
| `total_files` | int | Total files tracked in the database |
| `indexed_files` | int | Files that have been analyzed by the LLM |
| `pending_files` | int | Files waiting for analysis |
| `pending_renames` | int | Files with unapproved rename suggestions |
| `queue_size` | int | Current indexing queue depth |
| `watched_folders` | string[] | Absolute paths of monitored directories |

---

## Files

### GET /api/files

List tracked files with optional filtering and grouping.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `watch_folder` | string | -- | Filter by watch folder path |
| `category` | string | -- | Filter by AI category (e.g., "Documents", "Images") |
| `status` | string | -- | Filter by indexing status: `pending`, `indexing`, `indexed`, `error` |
| `grouped` | bool | false | Group results by category (requires `watch_folder`) |
| `limit` | int | 100 | Max results (max 1000) |
| `offset` | int | 0 | Pagination offset |

**Response (flat)**

```json
{
  "files": [
    {
      "id": 42,
      "path": "/Users/you/Downloads/quarterly-report.pdf",
      "filename": "quarterly-report.pdf",
      "extension": ".pdf",
      "size_bytes": 1048576,
      "file_hash": "a1b2c3d4...",
      "watch_folder": "/Users/you/Downloads",
      "status": "indexed",
      "description": "Q3 2025 financial report with revenue charts and expense breakdown.",
      "tags": ["finance", "quarterly", "report", "2025"],
      "category": "Documents",
      "content_preview": "Quarterly Financial Report Q3 2025...",
      "suggested_name": null,
      "rename_status": null,
      "original_name": null,
      "thumbnail_path": null,
      "created_at": "2025-10-01T09:00:00+00:00",
      "modified_at": "2025-10-01T09:00:00+00:00",
      "indexed_at": "2025-10-01T09:01:23+00:00"
    }
  ]
}
```

**Response (grouped)**

```json
{
  "grouped": true,
  "watch_folder": "/Users/you/Downloads",
  "categories": {
    "Documents": [ ... ],
    "Images": [ ... ],
    "Code": [ ... ]
  }
}
```

### GET /api/files/{file_id}

Get full details for a single file.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | int | File record ID |

**Response** -- same shape as a single item in the `files` array above.

**Errors**

| Status | Body |
|---|---|
| 404 | `{"detail": "File not found"}` |

### POST /api/files/{file_id}/reindex

Re-queue a file for AI analysis. Resets its status to `pending` and adds it to the index queue with highest priority.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | int | File record ID |

**Response**

```json
{
  "status": "queued",
  "file_id": 42
}
```

**Errors**

| Status | Body |
|---|---|
| 404 | `{"detail": "File not found"}` |

---

## Search

### GET /api/search

Full-text search across all indexed files.

**Query Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | (required) | Search query (min 1 character). Supports FTS5 syntax. |
| `limit` | int | 20 | Max results (max 100) |

**Response**

```json
{
  "query": "invoice tax 2025",
  "results": [
    {
      "id": 17,
      "path": "/Users/you/Documents/tax-invoice-2025.pdf",
      "filename": "tax-invoice-2025.pdf",
      "description": "Tax invoice from AccountingCo dated March 2025.",
      "tags": ["tax", "invoice", "2025", "accounting"],
      "category": "Invoices",
      "rank": -4.231,
      ...
    }
  ],
  "count": 1
}
```

The `rank` field is the FTS5 BM25 relevance score (lower/more negative = more relevant).

**Notes**

- Queries use the Porter stemmer: "invoices" matches "invoice", "running" matches "run".
- FTS5 syntax is supported: `"exact phrase"`, `invoice OR receipt`, `tax NOT personal`.

---

## Chat

### POST /api/chat

Send a message to the AI assistant. The server automatically searches the file index for relevant context.

**Request Body**

```json
{
  "message": "Where are my tax documents from 2025?"
}
```

**Response**

```json
{
  "response": "I found several tax-related documents in your files:\n\n1. **tax-invoice-2025.pdf** in ~/Documents — Tax invoice from AccountingCo dated March 2025.\n2. **w2-form-2025.pdf** in ~/Documents — W-2 wage and tax statement for 2025.\n\nWould you like me to help organize these into a dedicated folder?"
}
```

**Error Response**

```json
{
  "response": "Error communicating with Ollama: Connection refused"
}
```

---

## Renames

### GET /api/renames/pending

List all files with pending rename suggestions.

**Response**

```json
{
  "proposals": [
    {
      "file_id": 12,
      "current_name": "IMG_4521.png",
      "suggested_name": "sunset-beach-photo.png",
      "path": "/Users/you/Downloads/IMG_4521.png",
      "description": "Photograph of a sunset over a beach with palm trees.",
      "thumbnail_path": null
    }
  ],
  "count": 1
}
```

### POST /api/renames/{file_id}/approve

Approve a rename suggestion. The file is physically renamed on disk. The original name is stored for undo.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | int | File record ID |

**Response**

```json
{
  "status": "renamed",
  "old_name": "IMG_4521.png",
  "new_name": "sunset-beach-photo.png"
}
```

If the suggested name already exists, a numeric suffix is appended automatically (e.g., `sunset-beach-photo-1.png`).

**Errors**

| Status | Body |
|---|---|
| 404 | `{"detail": "No pending rename for this file"}` |
| 500 | `{"detail": "Rename failed: [OS error]"}` |

### POST /api/renames/{file_id}/dismiss

Dismiss a rename suggestion. Clears the suggested name so it will not reappear.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | int | File record ID |

**Response**

```json
{
  "status": "dismissed",
  "file_id": 12
}
```

### POST /api/renames/{file_id}/undo

Undo a previously approved rename. Restores the original filename on disk.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_id` | int | File record ID |

**Response**

```json
{
  "status": "undone",
  "restored_name": "IMG_4521.png"
}
```

**Errors**

| Status | Body |
|---|---|
| 404 | `{"detail": "No rename to undo"}` |
| 409 | `{"detail": "Original filename already taken"}` |
| 500 | `{"detail": "Undo failed: [OS error]"}` |
