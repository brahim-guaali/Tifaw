# Implementation Roadmap

Tifaw (ⵜⵉⴼⴰⵡ) is being built in 14 incremental phases. Each phase delivers a working feature on top of the previous ones.

---

## Phase Overview

| # | Phase | Status |
|---|---|---|
| 1 | Foundation | DONE |
| 2 | File Watcher | DONE |
| 3 | AI Indexer & Smart Rename | DONE |
| 4 | Search Engine | DONE |
| 5 | Frontend | DONE |
| 6 | Chat Agent | TODO |
| 7 | Auto-Organize | TODO |
| 8 | Smart Folders | TODO |
| 9 | Duplicate Detection | TODO |
| 10 | Stale File Cleanup | TODO |
| 11 | Screenshot Intelligence | TODO |
| 12 | Dev Project Manager | TODO |
| 13 | Daily Digest | TODO |
| 14 | Polish & Packaging | TODO |

---

## Completed Phases

### Phase 1: Foundation -- DONE

- Project structure with `pyproject.toml`, Makefile, config.yaml
- Pydantic `Settings` model loaded from YAML + environment variables
- `OllamaClient` with health check, model availability, `generate()`, `generate_json()`, `chat_stream()`
- SQLite database with full schema: files, files_fts, chat_history, smart_folders, duplicates, projects, settings
- Database class with async connection, upsert, query, and stats methods
- FastAPI application with lifespan management, CORS, static file serving
- Data directory at `~/.tifaw/`

### Phase 2: File Watcher -- DONE

- Watchdog-based `FileWatcher` with per-folder observers
- `FileEventHandler` handling created, modified, and moved events
- 2-second debounce timer to absorb write bursts
- Ignore rules for hidden files, temp files, system files, unsupported extensions, size limits
- `IndexQueue` using `asyncio.PriorityQueue` with deduplication
- Background worker task consuming from the queue

### Phase 3: AI Indexer & Smart Rename -- DONE

- Content extraction pipeline: text, images, PDFs (text + page render), DOCX, XLSX
- Image resize (max 1024px) before LLM analysis
- SHA-256 hash-based change detection to skip unchanged files
- LLM analysis prompt producing JSON: description, tags, category, suggested_name
- Generic filename detection via regex patterns (Screenshot, IMG_, UUID, hash, timestamp, etc.)
- Suggested name sanitization: lowercase, kebab-case, 50-char limit, original extension preserved
- FTS5 auto-sync via INSERT/UPDATE/DELETE triggers
- API routes: `GET /api/files`, `GET /api/files/{id}`, `POST /api/files/{id}/reindex`
- API routes: `GET /api/renames/pending`, `POST /api/renames/{id}/approve`, `POST /api/renames/{id}/dismiss`, `POST /api/renames/{id}/undo`
- Physical file rename on approve with conflict handling and undo support

### Phase 4: Search Engine -- DONE

- FTS5 virtual table with Porter stemming and Unicode tokenizer
- `GET /api/search?q=...` endpoint with BM25 ranking
- Configurable result limit (max 100)

### Phase 5: Frontend -- DONE

- Single-page application with Alpine.js (CDN, no build step)
- Sidebar navigation: Dashboard, Search, Folders, Chat, Renames, Projects
- Dashboard: stat cards (total, indexed, pending, renames), watched folder grid, recent files list
- Search: real-time search with 300ms debounce, result cards with tags and category
- Folder browser: tab per watched folder, files grouped by AI category with collapsible sections
- Chat: message bubbles, Markdown rendering (marked.js), typing indicator
- Renames: proposal cards with approve/dismiss/undo/approve-all actions
- File detail modal: description, category, tags, path, status, re-index button
- Ollama connection status indicator in sidebar footer
- Clean CSS with custom properties, responsive layout

---

## Upcoming Phases

### Phase 6: Chat Agent -- TODO

Upgrade the chat from simple prompt-response to a ReAct agent with tool use:

- Tool: `search_files(query)` -- search the FTS5 index
- Tool: `get_file(id)` -- retrieve full file details
- Tool: `list_files(folder, category)` -- browse files with filters
- Tool: `rename_file(id, name)` -- propose a rename
- Streaming responses via SSE or WebSocket
- Conversation history persistence in `chat_history` table
- Multi-turn context window management

### Phase 7: Auto-Organize -- TODO

- Analyze folder contents and propose a subfolder structure
- `OrganizePlan` model: list of `OrganizeGroup` (folder_name + file list)
- Preview UI showing proposed moves as a tree
- Approve/cancel workflow; batch file move with rollback on error
- API: `POST /api/organize/propose`, `POST /api/organize/apply`

### Phase 8: Smart Folders -- TODO

- CRUD API for smart folder rules (`/api/smart-folders`)
- Rule engine: filter by category, tags (contains/excludes), extension, date range, size range
- Virtual listing endpoint that queries `files` table dynamically
- Sidebar section showing saved smart folders with live file counts

### Phase 9: Duplicate Detection -- TODO

- Background scan comparing `file_hash` values across all files
- Semantic similarity pass using LLM comparison of descriptions
- Store pairs in `duplicates` table with similarity type and status
- UI: grouped duplicate sets with file previews, size, and keep/delete actions
- API: `GET /api/duplicates`, `POST /api/duplicates/{id}/resolve`

### Phase 10: Stale File Cleanup -- TODO

- Query files with `modified_at` older than threshold (configurable, default 90 days)
- Group stale files by folder and category with total size
- UI: list with age, size, and bulk actions (archive, delete, dismiss)
- API: `GET /api/cleanup/stale`, `POST /api/cleanup/{id}/action`

### Phase 11: Screenshot Intelligence -- TODO

- Detect screenshot files by name pattern and category
- Second-pass LLM analysis with specialized prompts:
  - Error screenshots: extract error text, suggest fix
  - Receipts/invoices: extract merchant, date, total, items
  - UI screenshots: describe interface, extract visible text
- Enriched metadata stored as additional fields or in description
- Detail view shows structured extracted data

### Phase 12: Dev Project Manager -- TODO

- Walk configured project directories looking for markers (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `.git`, etc.)
- Detect tech stack, package manager, git remote, branch, last commit
- Store in `projects` table
- Projects view in frontend: list with stack badges, branch, last activity
- API: `GET /api/projects`, `POST /api/projects/scan`

### Phase 13: Daily Digest -- TODO

- Scheduled or on-demand task that summarizes recent activity
- Input: files indexed today, pending renames, stale files, duplicates found
- LLM generates a natural-language digest paragraph
- Dashboard card or notification
- API: `GET /api/digest/today`

### Phase 14: Polish & Packaging -- TODO

- Error handling improvements across all modules
- Loading states and error feedback in the frontend
- Configuration validation with helpful error messages
- Keyboard shortcuts for common actions
- Dark/light theme support
- `pip install tifaw` packaging with entry point
- Homebrew formula or standalone installer for macOS
- Comprehensive test suite (unit + integration)
- Performance profiling and optimization
- Documentation site
