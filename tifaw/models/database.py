from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER,
    file_hash TEXT,
    watch_folder TEXT,
    status TEXT DEFAULT 'pending',
    description TEXT,
    tags TEXT,
    category TEXT,
    content_preview TEXT,
    suggested_name TEXT,
    rename_status TEXT,
    original_name TEXT,
    thumbnail_path TEXT,
    metadata TEXT,
    created_at TEXT,
    modified_at TEXT,
    indexed_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, description, tags, category, content_preview,
    content='files', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, filename, description, tags, category, content_preview)
    VALUES (new.id, new.filename, new.description, new.tags, new.category, new.content_preview);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename,
        description, tags, category, content_preview)
    VALUES ('delete', old.id, old.filename,
        old.description, old.tags, old.category,
        old.content_preview);
    INSERT INTO files_fts(rowid, filename, description,
        tags, category, content_preview)
    VALUES (new.id, new.filename, new.description,
        new.tags, new.category, new.content_preview);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, filename,
        description, tags, category, content_preview)
    VALUES ('delete', old.id, old.filename,
        old.description, old.tags, old.category,
        old.content_preview);
END;

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smart_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rule TEXT NOT NULL,
    icon TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id_a INTEGER REFERENCES files(id),
    file_id_b INTEGER REFERENCES files(id),
    similarity_type TEXT,
    status TEXT DEFAULT 'pending',
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    stack TEXT,
    package_manager TEXT,
    git_remote TEXT,
    git_branch TEXT,
    last_commit_date TEXT,
    last_commit_message TEXT,
    status TEXT,
    scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    label TEXT,
    x REAL NOT NULL,
    y REAL NOT NULL,
    w REAL NOT NULL,
    h REAL NOT NULL,
    confidence REAL,
    thumbnail_path TEXT,
    descriptor TEXT,
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_faces_file_id ON faces(file_id);
CREATE INDEX IF NOT EXISTS idx_faces_label ON faces(label);

CREATE TABLE IF NOT EXISTS known_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    face_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_watch_folder ON files(watch_folder);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_rename_status ON files(rename_status);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Add columns that may be missing from older schemas."""
        migrations = [
            ("faces", "descriptor", "ALTER TABLE faces ADD COLUMN descriptor TEXT"),
            ("files", "metadata", "ALTER TABLE files ADD COLUMN metadata TEXT"),
        ]
        for table, column, sql in migrations:
            try:
                cursor = await self._db.execute(f"PRAGMA table_info({table})")
                cols = [row[1] for row in await cursor.fetchall()]
                if column not in cols:
                    await self._db.execute(sql)
                    await self._db.commit()
            except Exception:
                pass

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not connected"
        return self._db

    # --- Files ---

    async def upsert_file(
        self,
        path: str,
        filename: str,
        extension: str | None,
        size_bytes: int | None,
        file_hash: str | None,
        watch_folder: str | None,
        created_at: str | None = None,
        modified_at: str | None = None,
        metadata: str | None = None,
    ) -> int:
        await self.db.execute(
            """INSERT INTO files (path, filename, extension, size_bytes, file_hash, watch_folder,
                created_at, modified_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename, size_bytes=excluded.size_bytes,
                file_hash=excluded.file_hash, modified_at=excluded.modified_at,
                metadata=excluded.metadata
            """,
            (path, filename, extension, size_bytes, file_hash, watch_folder,
             created_at, modified_at, metadata),
        )
        await self.db.commit()
        cursor = await self.db.execute("SELECT id FROM files WHERE path = ?", (path,))
        row = await cursor.fetchone()
        return row["id"]

    async def update_file_analysis(
        self,
        file_id: int,
        description: str,
        tags: list[str],
        category: str,
        content_preview: str | None,
        suggested_name: str | None,
        indexed_at: str,
    ) -> None:
        rename_status = "pending" if suggested_name else None
        await self.db.execute(
            """UPDATE files SET
                status='indexed', description=?, tags=?, category=?,
                content_preview=?, suggested_name=?, rename_status=?, indexed_at=?
            WHERE id=?""",
            (
                description,
                json.dumps(tags),
                category,
                content_preview,
                suggested_name,
                rename_status,
                indexed_at,
                file_id,
            ),
        )
        await self.db.commit()

    async def update_file_status(self, file_id: int, status: str) -> None:
        await self.db.execute("UPDATE files SET status=? WHERE id=?", (status, file_id))
        await self.db.commit()

    async def get_file(self, file_id: int) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM files WHERE id=?", (file_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_file_by_path(self, path: str) -> dict | None:
        cursor = await self.db.execute("SELECT * FROM files WHERE path=?", (path,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_files(
        self,
        watch_folder: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        conditions = []
        params: list = []
        if watch_folder:
            conditions.append("watch_folder = ?")
            params.append(watch_folder)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cursor = await self.db.execute(
            f"SELECT * FROM files {where} ORDER BY modified_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_files_grouped_by_category(self, watch_folder: str) -> dict[str, list[dict]]:
        files = await self.get_files(watch_folder=watch_folder, limit=1000)
        groups: dict[str, list[dict]] = {}
        for f in files:
            cat = f.get("category") or "Uncategorized"
            groups.setdefault(cat, []).append(f)
        return groups

    async def get_pending_renames(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM files WHERE rename_status='pending' ORDER BY indexed_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def approve_rename(self, file_id: int) -> dict | None:
        file = await self.get_file(file_id)
        if not file or file["rename_status"] != "pending":
            return None
        await self.db.execute(
            "UPDATE files SET rename_status='approved' WHERE id=?", (file_id,)
        )
        await self.db.commit()
        return file

    async def dismiss_rename(self, file_id: int) -> None:
        await self.db.execute(
            "UPDATE files SET rename_status='dismissed', suggested_name=NULL WHERE id=?",
            (file_id,),
        )
        await self.db.commit()

    async def update_file_path(self, file_id: int, new_path: str, new_filename: str) -> None:
        await self.db.execute(
            "UPDATE files SET path=?, filename=? WHERE id=?",
            (new_path, new_filename, file_id),
        )
        await self.db.commit()

    # --- Search ---

    async def search_files(self, query: str, limit: int = 20) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT f.*, files_fts.rank
            FROM files_fts
            JOIN files f ON f.id = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY files_fts.rank
            LIMIT ?""",
            (query, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # --- Stats ---

    async def get_file_by_hash_missing(
        self, file_hash: str, exclude_path: str,
    ) -> dict | None:
        """Find a file with matching hash whose path no longer exists
        on disk (candidate for a move detection)."""
        from pathlib import Path

        cursor = await self.db.execute(
            "SELECT * FROM files WHERE file_hash=? AND path!=?",
            (file_hash, exclude_path),
        )
        rows = await cursor.fetchall()
        for row in rows:
            if not Path(row["path"]).exists():
                return dict(row)
        return None

    async def prune_stale_renames(self) -> int:
        """Clear pending renames for files whose paths no longer exist."""
        from pathlib import Path

        cursor = await self.db.execute(
            "SELECT id, path FROM files "
            "WHERE rename_status='pending'"
        )
        rows = await cursor.fetchall()
        stale_ids = [
            r["id"] for r in rows if not Path(r["path"]).exists()
        ]
        if not stale_ids:
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        await self.db.execute(
            f"UPDATE files SET rename_status=NULL "
            f"WHERE id IN ({placeholders})",
            stale_ids,
        )
        await self.db.commit()
        return len(stale_ids)

    async def get_stats(self) -> dict:
        total = await self.db.execute(
            "SELECT COUNT(*) as c FROM files"
        )
        total_row = await total.fetchone()

        indexed = await self.db.execute(
            "SELECT COUNT(*) as c FROM files "
            "WHERE status='indexed'"
        )
        indexed_row = await indexed.fetchone()

        tier1 = await self.db.execute(
            "SELECT COUNT(*) as c FROM files "
            "WHERE status='tier1'"
        )
        tier1_row = await tier1.fetchone()

        pending = await self.db.execute(
            "SELECT COUNT(*) as c FROM files "
            "WHERE status='pending'"
        )
        pending_row = await pending.fetchone()

        renames = await self.db.execute(
            "SELECT COUNT(*) as c FROM files "
            "WHERE rename_status='pending'"
        )
        renames_row = await renames.fetchone()

        return {
            "total_files": total_row["c"],
            "indexed_files": indexed_row["c"],
            "tier1_files": tier1_row["c"],
            "pending_files": pending_row["c"],
            "pending_renames": renames_row["c"],
        }
