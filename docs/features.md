# Feature Specifications

This document describes each feature of Tifaw (ⵜⵉⴼⴰⵡ), covering what it does, how it works technically, and the user experience.

---

## 1. Multi-Folder Watching

**What it does.** Continuously monitors configured directories (default: ~/Downloads, ~/Desktop, ~/Documents) for new, modified, or moved files and automatically queues them for AI analysis.

**How it works.** A Watchdog `Observer` is started for each folder at application launch. A `FileEventHandler` listens for `on_created`, `on_modified`, and `on_moved` events. Each event is debounced for 2 seconds (to handle partial writes and multi-event bursts), then filtered against ignore rules:

- Hidden files (prefix `.`, `~`, `_`)
- System files (`.DS_Store`, `Thumbs.db`, `desktop.ini`)
- Temporary/partial downloads (`.tmp`, `.crdownload`, `.part`)
- Files outside the supported extension list
- Files smaller than 100 bytes or larger than the configured max (default 100 MB)

Surviving events are enqueued to an async `PriorityQueue` with deduplication (same path is not queued twice).

**User experience.** Completely invisible. Users simply drop files into their normal folders. The dashboard shows watched folders and live counts of total, indexed, and pending files.

---

## 2. AI File Understanding

**What it does.** Analyzes each file using Gemma 4 E4B to produce a human-readable description, relevant tags, a category, and optionally a better filename.

**How it works.** The indexing pipeline:

1. **Extract content** -- text files get their first 2000 characters; images are read as raw bytes; PDFs yield both extracted text (all pages) and a rendered PNG of page 1; DOCX and XLSX are parsed into plain text.
2. **Build prompt** -- the filename, file type, size, and extracted content/image are formatted into a structured prompt.
3. **LLM call** -- Gemma 4 E4B receives the prompt (with image if applicable) and returns a JSON object: `{ description, tags[], category, suggested_name? }`.
4. **Store results** -- the analysis is saved to the `files` table; FTS5 triggers auto-update the search index.

Images are resized to a maximum of 1024px before being base64-encoded to keep LLM inference fast and memory-bounded.

Categories are constrained to a fixed set: Documents, Images, Screenshots, Code, Spreadsheets, Presentations, Invoices, Receipts, Legal, Medical, Personal, Work, Education, Media, Archives, Other.

**User experience.** After a file is indexed, users see its AI-generated description, colored tags, and category badge everywhere in the UI -- dashboard, search results, folder browser, and file detail modal.

---

## 3. Smart Renaming

**What it does.** Detects files with generic or auto-generated names and suggests descriptive alternatives based on file content.

**How it works.** The `smart_rename` module checks filenames against a list of regex patterns that match common generic names:

- `Screenshot 2026-...`, `Screen Shot ...`
- `IMG_2847.png`, `DSC_0032.jpg`, `DCIM...`
- `image.png`, `document.pdf`, `Untitled`, `download (3).zip`
- UUID-based names (`a1b2c3d4-...`)
- Hash-based names (`ab12cd34ef56...`)
- Timestamp-based names (`1714000000.png`)
- `CleanShot`, `Capture`, `Pasted` prefixes

When a generic name is detected AND the LLM analysis included a `suggested_name`, the file is flagged with `rename_status='pending'`. Suggested names are sanitized: lowercased, kebab-cased, limited to 50 characters, with the original extension preserved.

**User experience.** The sidebar shows a badge count of pending renames. The Renames view lists each proposal with the current name, suggested name, and file description. Users can:

- **Approve** -- the file is physically renamed on disk; the original name is stored for undo.
- **Dismiss** -- the suggestion is discarded and will not reappear.
- **Undo** -- after approval, reverting restores the original filename.
- **Approve All** -- batch-approve every pending rename.

File name conflicts are handled automatically by appending `-1`, `-2`, etc.

---

## 4. Natural Language Search

**What it does.** Lets users search across all indexed files using plain language queries.

**How it works.** The `files_fts` virtual table uses SQLite FTS5 with the `porter unicode61` tokenizer. It indexes five columns: `filename`, `description`, `tags`, `category`, and `content_preview`. Queries are matched using FTS5's `MATCH` operator and ranked by BM25 relevance. Results are joined back to the `files` table for full metadata.

The FTS5 index is kept in sync automatically via SQLite triggers that fire on INSERT, UPDATE, and DELETE operations on the `files` table.

**User experience.** The Search view has a full-width input field. Results appear as the user types (debounced 300ms). Each result shows the filename, AI description, tags, and category. Clicking a result opens the file detail modal. Example queries:

- "invoices from march"
- "python machine learning"
- "screenshot error message"
- "tax documents 2025"

---

## 5. Chat Interface

**What it does.** Provides a conversational AI assistant that can answer questions about the user's files.

**How it works.** When the user sends a message via `POST /api/chat`, the server:

1. Searches the FTS5 index for files relevant to the message (top 5 results).
2. Builds a context block listing each matching file's name, description, category, and path.
3. Sends the augmented prompt to Gemma 4 E4B with a system prompt identifying the assistant as a local file helper.
4. Returns the LLM response.

The frontend renders responses as Markdown (via marked.js) in a chat bubble UI.

**User experience.** A clean chat interface with message bubbles. The user types natural language questions ("Where is that receipt from the Apple Store?", "Show me all Python projects I worked on last week") and gets contextual answers grounded in the actual file index. A loading indicator (pulsing dots) shows while the LLM is generating.

---

## 6. Auto-Organize

**Status: planned.**

**What it does.** Analyzes a folder's contents and proposes a folder structure to organize files by category, project, or topic.

**How it works.** The organizer module will:

1. Load all indexed files for a given watch folder.
2. Group them by AI-assigned categories and tags.
3. Send the grouping to Gemma 4 E4B with a prompt asking it to propose a clean folder structure.
4. Return an `OrganizePlan` with named subfolders and assigned files.

**User experience.** Users click "Organize" on a folder. Tifaw shows a preview tree of proposed moves. Users can approve the entire plan, exclude specific files, or cancel. Files are only moved after explicit approval.

---

## 7. Smart Folders

**Status: planned.**

**What it does.** Creates virtual collections that group files by AI-assigned tags, categories, or custom rules -- without moving any files on disk.

**How it works.** The `smart_folders` table stores named rules (e.g., `{"category": "Invoices", "tags_contain": "tax"}`). When a smart folder is opened, Tifaw queries the `files` table with the matching criteria and returns a virtual listing. The database schema is already in place.

**User experience.** Users create smart folders from the sidebar (e.g., "Tax Documents", "Design Assets"). These act like saved searches that always show up-to-date results.

---

## 8. Duplicate Detection

**Status: planned.**

**What it does.** Identifies duplicate files by exact content match (SHA-256 hash) and near-duplicate files by semantic similarity.

**How it works.** The `duplicates` table tracks pairs of files with a `similarity_type` field ("hash" for exact matches, "semantic" for content-similar). Hash duplicates are detected by querying for files sharing the same `file_hash` value (index: `idx_files_hash`). Semantic duplicates will use LLM comparison of descriptions and content previews.

**User experience.** A Duplicates view lists groups of duplicate files with their sizes and locations. Users choose which copy to keep; the others can be deleted or moved to a "reviewed" state.

---

## 9. Daily Digest

**Status: planned.**

**What it does.** Generates a daily summary of file activity: new files indexed, pending renames, suggested cleanups, and notable findings.

**How it works.** A background task (or on-demand trigger) queries recent activity from the database, assembles a summary prompt, and sends it to Gemma 4 E4B for a natural-language digest.

**User experience.** A notification or digest card on the dashboard summarizes the day's activity in a few paragraphs.

---

## 10. Screenshot Intelligence

**Status: planned.**

**What it does.** Applies specialized analysis to screenshots: detects error messages and suggests fixes, extracts receipt/invoice details, reads text from UI screenshots.

**How it works.** Screenshots are already analyzed as images in the standard pipeline. The screenshot module will add a second-pass prompt tuned for specific tasks:

- Error screenshots: "Extract the error message and suggest a fix."
- Receipts: "Extract merchant, date, total, and line items."
- UI screenshots: "Describe what this interface shows and extract any visible text."

**User experience.** Screenshot files get enriched metadata. An error screenshot might show a "Suggested Fix" section in its detail view. A receipt screenshot would display extracted fields (merchant, amount, date) as structured data.

---

## 11. Dev Project Manager

**Status: planned.**

**What it does.** Scans configured project directories to detect software projects, identify their tech stacks, and show git status.

**How it works.** The `projects` table stores detected projects. The scanner walks configured directories (default: ~/Projects) looking for markers: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `.git`, etc. For each project it records the name, detected stack, package manager, git remote, current branch, last commit date and message.

**User experience.** The Projects view (sidebar) lists all detected projects with their stack icons, branch name, and last activity. Users can see at a glance which projects have uncommitted changes or are stale.

---

## 12. Stale File Cleanup

**Status: planned.**

**What it does.** Surfaces files that have not been accessed or modified for a configurable period (default: 90 days) and suggests cleanup actions.

**How it works.** Queries the `files` table for records where `modified_at` is older than the threshold. The cleanup module presents these files grouped by folder and category, with total size calculations.

**User experience.** A Cleanup view shows stale files sorted by age and size. Users can archive, delete, or dismiss items. No files are removed without explicit action.

---

## 13. Grouped Folder Views

**What it does.** Displays files within a watched folder organized by AI-assigned category instead of a flat chronological list.

**How it works.** The `GET /api/files?grouped=true&watch_folder=...` endpoint calls `get_files_grouped_by_category()`, which fetches all files for the folder and groups them by their `category` field into a dictionary.

**User experience.** The Folder Browser view shows tabs for each watched folder. Within a folder, files are grouped under collapsible category headings (Documents, Images, Code, etc.) with file counts. Each group can be expanded or collapsed independently.
