from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


class RenameStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISMISSED = "dismissed"


class FileRecord(BaseModel):
    id: int
    path: str
    filename: str
    extension: str | None = None
    size_bytes: int | None = None
    file_hash: str | None = None
    watch_folder: str | None = None
    status: FileStatus = FileStatus.PENDING
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    content_preview: str | None = None
    suggested_name: str | None = None
    rename_status: RenameStatus | None = None
    original_name: str | None = None
    thumbnail_path: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    indexed_at: str | None = None


class SearchResult(BaseModel):
    file: FileRecord
    rank: float = 0.0
    snippet: str | None = None


class AnalysisResult(BaseModel):
    description: str
    tags: list[str]
    category: str
    suggested_name: str | None = None


class RenameProposal(BaseModel):
    file_id: int
    current_name: str
    suggested_name: str
    path: str
    thumbnail_path: str | None = None


class OrganizePlan(BaseModel):
    folder: str
    groups: list[OrganizeGroup]


class OrganizeGroup(BaseModel):
    folder_name: str
    files: list[str]


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str | None = None


class ProjectInfo(BaseModel):
    id: int
    path: str
    name: str
    description: str | None = None
    stack: list[str] = Field(default_factory=list)
    package_manager: str | None = None
    git_remote: str | None = None
    git_branch: str | None = None
    last_commit_date: str | None = None
    last_commit_message: str | None = None
    status: str | None = None
    scanned_at: str | None = None


class StatusResponse(BaseModel):
    ollama_connected: bool = False
    model_available: bool = False
    total_files: int = 0
    indexed_files: int = 0
    pending_files: int = 0
    pending_renames: int = 0
    queue_size: int = 0
    watched_folders: list[str] = Field(default_factory=list)
