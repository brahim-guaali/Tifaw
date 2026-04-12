# Tifaw

**Your laptop's story, powered by local AI.**

Tifaw (ⵜⵉⴼⴰⵡ) - meaning "clarity" or "radiance" in Tamazight (Amazigh/Berber) - is a local AI desktop assistant that helps you understand everything on your machine. It automatically analyzes, categorizes, and organizes your files using Google's Gemma 4 model running entirely on your laptop through Ollama. No cloud, no telemetry, no subscriptions.

Tifaw doesn't just list files -- it tells the story of your digital life. It knows your photos, recognizes faces, groups documents by purpose, tracks your code projects, and lets you ask questions about everything in plain English.

---

## Features

### Your Laptop's Story
- **Overview dashboard** -- animated stats, timeline of activity, storage breakdown, and story cards that summarize your digital life
- **Context over location** -- files grouped by meaning (Finance, Education, Work) not by folder

### Photos & People
- **Face detection** -- automatic face detection using macOS Vision framework during indexing
- **Face recognition** -- 128-dimensional Apple Vision embeddings match the same person across photos
- **People management** -- auto-assigned placeholder names, rename once to apply everywhere, merge duplicates
- **Photo gallery** -- masonry grid with people filter bar, category filter, infinite scroll
- **Image/video previews** -- inline previews in search results and file details

### Smart File Management
- **AI file understanding** -- multimodal analysis of images, PDFs, code, documents, and spreadsheets via Gemma 4 E4B
- **Smart renaming** -- detects generic filenames (IMG_2847.png, Screenshot 2026-...) and suggests descriptive names with thumbnail previews
- **Natural language search** -- full-text search powered by SQLite FTS5 with card-based results
- **Ask Tifaw** -- chat with an AI that knows your file system, with suggested prompts
- **File actions** -- open in Finder, re-index, move to Trash directly from the UI

### Organization
- **Multi-folder watching** -- monitors Downloads, Desktop, Documents (configurable from UI)
- **Documents by purpose** -- Finance, Legal, Education, Work, Personal groupings
- **Dev project scanner** -- detect code projects, tech stacks, git status
- **Spotlight fallback** -- uses macOS Spotlight index when Full Disk Access isn't available
- **Self-healing queue** -- pending files automatically re-queued after crashes or restarts

### Settings
- **Live configuration** -- change watch folders, project directories from the UI with folder picker
- **Hot reload** -- settings apply immediately without server restart

## Tech Stack

| Layer | Technology |
|---|---|
| AI model | [Gemma 4 E4B](https://ai.google.dev/gemma) via [Ollama](https://ollama.com) |
| Face detection | macOS Vision framework via [PyObjC](https://pyobjc.readthedocs.io) |
| Backend | Python 3.11+, [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org) |
| Database | SQLite with FTS5 (via [aiosqlite](https://github.com/omnilib/aiosqlite)) |
| File watching | [Watchdog](https://github.com/gorakhargosh/watchdog) |
| PDF extraction | [PyMuPDF](https://pymupdf.readthedocs.io) |
| Image processing | [Pillow](https://pillow.readthedocs.io) |
| Frontend | [Tailwind CSS](https://tailwindcss.com) (CDN), [Alpine.js](https://alpinejs.dev), [marked.js](https://marked.js.org) |

## Quick Start

### Prerequisites

- macOS (face detection uses Apple Vision framework)
- Python 3.11 or later
- [Ollama](https://ollama.com) installed and running
- ~5 GB disk space for the Gemma 4 E4B model

### Setup

```bash
git clone https://github.com/brahim-guaali/Tifaw.git
cd Tifaw
python3 -m venv .venv
make setup    # installs deps, pulls gemma4:e4b, creates ~/.tifaw
```

### Run

```bash
make dev      # starts the server at http://127.0.0.1:8321
```

Open [http://127.0.0.1:8321](http://127.0.0.1:8321) in your browser.

### Configuration

Settings can be changed directly from the UI (Settings page), or by editing `config.yaml`:

```yaml
watch_folders:
  - ~/Downloads
  - ~/Desktop
  - ~/Documents

project_directories:
  - ~/Projects

rename:
  enabled: true
  auto_approve: false

cleanup:
  threshold_days: 90
```

## Project Structure

```
Tifaw/
  tifaw/                 # Python package
    api/                 # FastAPI route handlers
      routes_overview.py # Story dashboard API
      routes_photos.py   # Photo gallery with filters
      routes_faces.py    # Face detection & people management
      routes_documents.py# Documents grouped by purpose
      routes_config.py   # Live settings API with folder browser
      routes_files.py    # File CRUD, preview, reveal, delete
      routes_rename.py   # Smart rename proposals
      routes_search.py   # Full-text search
      routes_chat.py     # AI chat
      routes_projects.py # Code project scanner
    faces/               # Face detection & recognition (Vision framework)
    indexer/             # Content extraction, LLM analysis, self-healing queue
    llm/                 # Ollama client wrapper
    models/              # Database layer + Pydantic schemas
    renamer/             # Generic name detection + smart rename
    watcher/             # Watchdog file system observer + Spotlight fallback
    config.py            # Settings loader (YAML + env)
    main.py              # FastAPI app + lifespan
  frontend/              # Static frontend
    index.html           # Alpine.js SPA with Tailwind CSS
    app.js               # Application logic
    styles.css           # Custom animations & components
  config.yaml            # User configuration
  Makefile               # Dev commands
  pyproject.toml         # Package metadata + dependencies
```

## Development

```bash
make lint      # run ruff checks
make format    # auto-fix formatting
make test      # run pytest
make clean     # remove caches and build artifacts
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
