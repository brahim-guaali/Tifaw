from __future__ import annotations

import logging
from pathlib import Path

from tifaw.indexer.extractors import ExtractionResult
from tifaw.llm.client import OllamaClient
from tifaw.models.schemas import AnalysisResult

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a file analysis assistant. Analyze the given file and respond ONLY with a JSON object (no markdown, no explanation).

The JSON must have these fields:
- "description": A clear 1-2 sentence description of what this file contains
- "tags": An array of 3-5 relevant tags (lowercase, single words or short phrases)
- "category": Exactly one of: Documents, Images, Screenshots, Code, Spreadsheets, Presentations, Invoices, Receipts, Legal, Medical, Personal, Work, Education, Media, Archives, Other
- "suggested_name": If the current filename is generic or auto-generated (like Screenshot, IMG_, image, document, Untitled, download, or a UUID/hash), suggest a better kebab-case filename (max 50 chars, include the original extension). Set to null if the current name is already descriptive."""

ANALYSIS_PROMPT_TEMPLATE = """Analyze this file:
Filename: {filename}
File type: {file_type}
Size: {size}

{content_section}

Respond with ONLY a JSON object."""


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


async def analyze_file(
    filename: str,
    file_type: str,
    size_bytes: int | None,
    extraction: ExtractionResult,
    llm: OllamaClient,
) -> AnalysisResult:
    content_section = ""
    images: list[str] | None = None

    if extraction.text_content:
        content_section = f"Content:\n{extraction.text_content}"

    if extraction.image_bytes:
        import base64

        images = [base64.b64encode(extraction.image_bytes).decode()]
        if not content_section:
            content_section = "See the attached image."

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        filename=filename,
        file_type=file_type,
        size=_format_size(size_bytes),
        content_section=content_section or "No content could be extracted.",
    )

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system=ANALYSIS_SYSTEM_PROMPT,
            images=images,
        )

        return AnalysisResult(
            description=result.get("description", "No description available"),
            tags=result.get("tags", []),
            category=result.get("category", "Other"),
            suggested_name=result.get("suggested_name"),
        )
    except Exception as e:
        logger.error("Analysis failed for %s: %s", filename, e)
        return AnalysisResult(
            description=f"File: {filename}",
            tags=[],
            category="Other",
            suggested_name=None,
        )
