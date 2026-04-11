from __future__ import annotations

import re
from pathlib import Path

# Patterns that indicate a generic/auto-generated filename
GENERIC_PATTERNS = [
    re.compile(r"^Screenshot[\s_]", re.IGNORECASE),
    re.compile(r"^Screen\s?Shot[\s_]", re.IGNORECASE),
    re.compile(r"^IMG[_-]\d{3,}", re.IGNORECASE),
    re.compile(r"^DSC[_-]?\d{3,}", re.IGNORECASE),
    re.compile(r"^DCIM", re.IGNORECASE),
    re.compile(r"^photo[_-]?\d", re.IGNORECASE),
    re.compile(r"^image\s*(\(\d+\))?\.", re.IGNORECASE),
    re.compile(r"^document\s*(\(\d+\))?\.", re.IGNORECASE),
    re.compile(r"^Untitled", re.IGNORECASE),
    re.compile(r"^New Document", re.IGNORECASE),
    re.compile(r"^download\s*(\(\d+\))?\.", re.IGNORECASE),
    re.compile(r"^file\s*(\(\d+\))?\.", re.IGNORECASE),
    re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-", re.IGNORECASE),  # UUID
    re.compile(r"^[a-f0-9]{32,}\.", re.IGNORECASE),  # MD5/SHA hash
    re.compile(r"^\d{10,}\."),  # Timestamp-based names
    re.compile(r"^Capture[\s_]", re.IGNORECASE),
    re.compile(r"^CleanShot[\s_]", re.IGNORECASE),
    re.compile(r"^Pasted[\s_]", re.IGNORECASE),
]


def is_generic_name(filename: str) -> bool:
    return any(pattern.search(filename) for pattern in GENERIC_PATTERNS)


def sanitize_suggested_name(suggested: str, original_extension: str) -> str:
    name = suggested.strip()

    # Remove any extension the AI might have added
    stem = Path(name).stem
    ext = Path(name).suffix.lower()

    # Use original extension if AI didn't provide one or got it wrong
    if not ext:
        ext = original_extension

    # Clean the stem: lowercase, replace spaces/underscores with hyphens
    stem = stem.lower()
    stem = re.sub(r"[^a-z0-9\-]", "-", stem)
    stem = re.sub(r"-+", "-", stem)
    stem = stem.strip("-")

    # Limit length
    if len(stem) > 50:
        stem = stem[:50].rstrip("-")

    return f"{stem}{ext}"
