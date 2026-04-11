# Architecture & Design

Tifaw (ⵜⵉⴼⴰⵡ) is a local-first, single-machine application. Every component runs on the user's computer -- there are no external API calls, no cloud storage, and no telemetry.

---

## System Overview

```
                          ┌──────────────────────────┐
                          │   Browser (Alpine.js)    │
                          │   http://127.0.0.1:8321  │
                          └────────────┬─────────────┘
                                       │ HTTP / JSON
                          ┌────────────▼─────────────┐
                          │       FastAPI Server      │
                          │   routes: status, files,  │
                          │   search, rename, chat    │
                          └──┬──────┬──────────┬──────┘
                             │      │          │
                ┌────────────▼┐  ┌──▼────┐  ┌──▼──────────────┐
                │   Ollama    │  │SQLite │  │  File Watcher   │
                │ gemma4:e4b  │  │ + FTS5│  │  (Watchdog)     │
                │  (local)    │  │       │  │                 │
                └─────────────┘  └───────┘  └──┬──────────────┘
                                               │ file events
                                    ┌──────────▼──────────┐
                                    │    Index Queue       │
                                    │  (asyncio Priority)  │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │   Index Pipeline     │
                                    │  extract → analyze   │
                                    │  → store → FTS5      │
                                    └─────────────────────┘
```

### Component Responsibilities

| Component | Role |
|---|---|
| **FastAPI Server** | HTTP API, serves frontend static files, coordinates all modules |
| **Ollama (Gemma 4 E4B)** | Multimodal LLM for file analysis, chat, rename suggestions, organization proposals |
| **SQLite + FTS5** | Persistent storage for file metadata, analysis results, chat history; full-text search index |
| **File Watcher** | Watchdog observers on configured folders; emits file events with debouncing |
| **Index Queue** | Async priority queue; deduplicates and orders indexing work |
| **Index Pipeline** | Extracts content (text/image/PDF), calls LLM for analysis, writes results to DB |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM runtime | Ollama | Cross-platform, simple HTTP API, manages model lifecycle, supports multimodal Gemma 4 |
| Model | Gemma 4 E4B | Small enough for laptops (~5 GB), multimodal (text + images), strong reasoning for its size |
| Database | SQLite | Zero-config, single-file, ships with Python; more than sufficient for tens of thousands of files |
| Full-text search | FTS5 | Built into SQLite, Porter stemming, ranked results; no need for a separate search engine or embedding vectors |
| File watching | Watchdog | Mature, cross-platform, uses native OS file events (FSEvents on macOS, inotify on Linux) |
| Frontend framework | Alpine.js (CDN) | No build step, progressive enhancement, ~15 KB; avoids Node/npm/bundler complexity |
| API framework | FastAPI | Async-native, automatic OpenAPI docs, Pydantic validation, excellent performance |
| Image processing | Pillow | Resize large images before sending to LLM to reduce memory and latency |
| PDF extraction | PyMuPDF (fitz) | Extracts both text and page renders; fast C-based library |
| Change detection | SHA-256 hash | Skip re-indexing unchanged files; hash is stored per file record |
| Queue architecture | asyncio.PriorityQueue | New files get priority 1 (higher), modifications get priority 2; single worker avoids LLM contention |

---

## Data Flow

### File Indexing Pipeline

```
File appears/changes in watched folder
        │
        ▼
  Watchdog event (on_created / on_modified / on_moved)
        │
        ▼
  Debounce (2 seconds) ── prevents re-processing during writes
        │
        ▼
  Filter ── ignore hidden files, temp files, unsupported extensions, size limits
        │
        ▼
  Enqueue to IndexQueue (priority 1=new, 2=modified, 0=manual reindex)
        │
        ▼
  Index Worker picks job from queue
        │
        ▼
  SHA-256 hash check ── skip if file unchanged since last index
        │
        ▼
  Content extraction
     ├── Text files: read first 2000 chars
     ├── Images: read raw bytes
     ├── PDFs: extract text (all pages) + render page 1 as PNG
     ├── DOCX: extract paragraph text
     └── XLSX: extract first 50 rows from first 3 sheets
        │
        ▼
  LLM analysis (Gemma 4 E4B via Ollama)
     ├── Input: filename, file type, size, extracted text and/or image
     ├── Output JSON: description, tags[], category, suggested_name?
     └── Image resize: cap at 1024px before sending to LLM
        │
        ▼
  Store results in SQLite (files table)
        │
        ▼
  FTS5 triggers auto-update search index
        │
        ▼
  If filename is generic AND LLM suggested a name → mark rename_status='pending'
```

### Search

```
User types query in search bar
        │
        ▼
  Frontend debounces 300ms, then GET /api/search?q=...
        │
        ▼
  FTS5 MATCH query with Porter stemming + Unicode tokenizer
        │
        ▼
  Results ranked by BM25 relevance, joined with files table
        │
        ▼
  JSON response with file metadata + tags + description
```

### Chat

```
User sends message via POST /api/chat
        │
        ▼
  Server searches FTS5 for relevant files (top 5)
        │
        ▼
  Constructs prompt: user message + file context + system prompt
        │
        ▼
  Sends to Ollama (non-streaming for v1, streaming planned)
        │
        ▼
  Returns AI response as JSON
```

---

## Database Schema

### Core Tables

- **files** -- one row per tracked file; stores path, hash, analysis results (description, tags, category), rename state, timestamps
- **files_fts** -- FTS5 virtual table indexing filename, description, tags, category, content_preview; auto-synced via triggers
- **chat_history** -- conversation log (role, content, timestamp)
- **smart_folders** -- saved virtual folder rules (name, rule JSON, icon)
- **duplicates** -- detected duplicate pairs (file_id_a, file_id_b, similarity_type, status)
- **projects** -- scanned dev projects (path, stack, git info, last commit)
- **settings** -- key-value store for app preferences

### Indexes

- `idx_files_status` -- fast filtering by indexing status
- `idx_files_watch_folder` -- fast per-folder queries
- `idx_files_category` -- fast category grouping
- `idx_files_rename_status` -- fast pending rename lookup
- `idx_files_hash` -- fast duplicate detection by hash

---

## Performance Strategy

| Concern | Approach |
|---|---|
| LLM throughput | Single worker processes one file at a time; avoids GPU/CPU contention and OOM |
| Redundant indexing | SHA-256 hash stored per file; skip re-analysis if hash unchanged |
| Large images | Resize to max 1024px before encoding to base64 for LLM |
| File event storms | 2-second debounce in Watchdog handler; deduplication in IndexQueue |
| Database writes | Upsert pattern (INSERT ... ON CONFLICT UPDATE) avoids duplicate rows |
| Search speed | FTS5 with pre-built triggers; no post-processing needed |
| Frontend | Static files served by FastAPI; Alpine.js loaded from CDN; no build step |
| Startup | Ollama health check is non-blocking; watcher and indexer start in background |

---

## Security & Privacy

- All data stays on the local machine. No network calls except to `localhost:11434` (Ollama).
- The database is stored in `~/.tifaw/tifaw.db` (configurable).
- The API binds to `127.0.0.1` only -- not accessible from the network.
- No authentication is implemented (single-user local tool).
- File operations (rename, move) require explicit user approval by default.
