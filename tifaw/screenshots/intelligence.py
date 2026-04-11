from __future__ import annotations

import logging
from pathlib import Path

from tifaw.llm.client import OllamaClient

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT = """Analyze this screenshot and provide a JSON response with:
1. "type": one of "error", "receipt", "booking", "code", "website", "chat", "document", "other"
2. "summary": a brief one-sentence description of what the screenshot shows
3. "extracted_data": a dict of structured key-value data you can extract from the image (e.g., error messages, amounts, dates, URLs, code snippets, etc.)

Respond ONLY with valid JSON, no markdown."""


async def analyze_screenshot(file_path: str | Path, llm: OllamaClient) -> dict:
    """Send a screenshot to Gemma 4 for visual analysis and data extraction."""
    file_path = Path(file_path)

    if not file_path.exists():
        return {
            "type": "other",
            "summary": "File not found",
            "extracted_data": {},
        }

    try:
        image_b64 = llm.encode_image_file(file_path)
        result = await llm.generate_json(
            prompt=_ANALYSIS_PROMPT,
            images=[image_b64],
        )

        # Ensure expected keys exist
        return {
            "type": result.get("type", "other"),
            "summary": result.get("summary", ""),
            "extracted_data": result.get("extracted_data", {}),
        }
    except Exception as exc:
        logger.error("Screenshot analysis failed for %s: %s", file_path, exc)
        return {
            "type": "other",
            "summary": f"Analysis failed: {exc}",
            "extracted_data": {},
        }
