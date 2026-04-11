# Tifaw

**Local AI that brings clarity to your files.**

Tifaw (ⵜⵉⴼⴰⵡ) - meaning "clarity" or "radiance" in Tamazight (Amazigh/Berber) -- is a local AI desktop assistant and smart file organizer powered by Google's Gemma 4 E4B model running entirely on your machine through Ollama. No cloud, no telemetry, no subscriptions.

Drop files into your watched folders and Tifaw will automatically understand, describe, tag, categorize, and organize them using multimodal AI. Search your files with natural language, get smart rename suggestions for generic filenames, and chat with an AI that knows your file system.

---

## Features

- **Multi-folder watching** -- monitors Downloads, Desktop, Documents (configurable) for new and changed files
- **AI file understanding** -- multimodal analysis of images, PDFs, code, documents, and spreadsheets via Gemma 4 E4B
- **Smart renaming** -- detects generic filenames (IMG_2847.png, Screenshot 2026-...) and suggests descriptive names
- **Natural language search** -- full-text search powered by SQLite FTS5 with Porter stemming
- **Chat interface** -- ask questions about your files in plain English
- **Grouped folder views** -- browse files organized by AI-assigned category instead of flat lists
- **Auto-organize** -- AI proposes folder structures, you preview and approve before anything moves
- **Smart folders** -- virtual collections based on AI tags and categories
- **Duplicate detection** -- find duplicates by content hash and semantic similarity
- **Screenshot intelligence** -- extract error messages, receipt details, and more from screenshots
- **Dev project manager** -- scan project directories, detect tech stacks, show git status
- **Stale file cleanup** -- surface files untouched for 90+ days
- **Daily digest** -- summary of new files, pending renames, and suggested actions

## Tech Stack

| Layer | Technology |
|---|---|
| AI model | [Gemma 4 E4B](https://ai.google.dev/gemma) via [Ollama](https://ollama.com) |
| Backend | Python 3.11+, [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org) |
| Database | SQLite with FTS5 (via [aiosqlite](https://github.com/omnilib/aiosqlite)) |
| File watching | [Watchdog](https://github.com/gorakhargosh/watchdog) |
| PDF extraction | [PyMuPDF](https://pymupdf.readthedocs.io) |
| Image processing | [Pillow](https://pillow.readthedocs.io) |
| Frontend | Vanilla HTML/CSS, [Alpine.js](https://alpinejs.dev), [marked.js](https://marked.js.org) |

## Quick Start

### Prerequisites

- Python 3.11 or later
- [Ollama](https://ollama.com) installed and running
- ~5 GB disk space for the Gemma 4 E4B model

### Setup

```bash
git clone https://github.com/your-username/tifaw.git
cd tifaw
make setup    # installs deps, pulls gemma4:e4b, creates ~/.tifaw
```

### Run

```bash
make dev      # starts the server at http://127.0.0.1:8321
```

Open [http://127.0.0.1:8321](http://127.0.0.1:8321) in your browser.

### Configuration

Edit `config.yaml` in the project root to customize watched folders, rename behavior, cleanup thresholds, and supported file types.

```yaml
watch_folders:
  - ~/Downloads
  - ~/Desktop
  - ~/Documents

rename:
  enabled: true
  auto_approve: false

cleanup:
  threshold_days: 90
```

## Screenshots

> _Dashboard view -- coming soon_

> _Search results -- coming soon_

> _Smart rename review -- coming soon_

> _Chat interface -- coming soon_

## Project Structure

```
tifaw/
  tifaw/               # Python package
    api/               # FastAPI route handlers
    chat/              # Chat agent (ReAct + tools)
    cleanup/           # Stale file detection
    digest/            # Daily digest generation
    duplicates/        # Hash + similarity duplicate finder
    indexer/           # Content extraction, LLM analysis, queue
    llm/               # Ollama client wrapper
    models/            # Database layer + Pydantic schemas
    organizer/         # AI folder structure proposals
    projects/          # Dev project scanner
    renamer/           # Generic name detection + smart rename
    screenshots/       # Screenshot intelligence
    search/            # FTS5 search helpers
    smartfolders/      # Virtual folder engine
    watcher/           # Watchdog file system observer
    config.py          # Settings loader (YAML + env)
    main.py            # FastAPI app + lifespan
  frontend/            # Static HTML/CSS/JS (Alpine.js)
  tests/               # Pytest test suite
  config.yaml          # User configuration
  Makefile             # Dev commands
  pyproject.toml       # Package metadata + dependencies
```

## Development

```bash
make lint      # run ruff checks
make format    # auto-fix formatting
make test      # run pytest
make clean     # remove caches and build artifacts
```

## License

Apache License 2.0. See [LICENSE](../LICENSE).
