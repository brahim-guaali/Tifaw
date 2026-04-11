from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".go", ".rs", ".java", ".cpp", ".c", ".h", ".rb", ".sh",
    ".sql", ".xml", ".env", ".ini", ".cfg",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

PDF_EXTENSION = ".pdf"


@dataclass
class ExtractionResult:
    text_content: str | None = None
    image_bytes: bytes | None = None
    file_type: str = "unknown"


def extract_content(path: Path) -> ExtractionResult:
    ext = path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return _extract_image(path)
    elif ext == PDF_EXTENSION:
        return _extract_pdf(path)
    elif ext in TEXT_EXTENSIONS:
        return _extract_text(path)
    elif ext == ".docx":
        return _extract_docx(path)
    elif ext == ".xlsx":
        return _extract_xlsx(path)
    else:
        return ExtractionResult(file_type="binary")


def _extract_text(path: Path) -> ExtractionResult:
    try:
        text = path.read_text(errors="replace")[:2000]
        return ExtractionResult(text_content=text, file_type="text")
    except Exception as e:
        logger.warning("Failed to read text from %s: %s", path, e)
        return ExtractionResult(file_type="text")


def _extract_image(path: Path) -> ExtractionResult:
    try:
        return ExtractionResult(image_bytes=path.read_bytes(), file_type="image")
    except Exception as e:
        logger.warning("Failed to read image %s: %s", path, e)
        return ExtractionResult(file_type="image")


def _extract_pdf(path: Path) -> ExtractionResult:
    text = ""
    image_bytes = None

    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))

        # Extract text from all pages
        for page in doc:
            text += page.get_text() + "\n"
        text = text[:2000]

        # Render first page as image
        if len(doc) > 0:
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image_bytes = pix.tobytes("png")

        doc.close()
    except Exception as e:
        logger.warning("Failed to extract PDF %s: %s", path, e)

    return ExtractionResult(text_content=text or None, image_bytes=image_bytes, file_type="pdf")


def _extract_docx(path: Path) -> ExtractionResult:
    try:
        from docx import Document

        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs)[:2000]
        return ExtractionResult(text_content=text, file_type="docx")
    except ImportError:
        logger.info("python-docx not installed, skipping .docx extraction")
        return ExtractionResult(file_type="docx")
    except Exception as e:
        logger.warning("Failed to extract docx %s: %s", path, e)
        return ExtractionResult(file_type="docx")


def _extract_xlsx(path: Path) -> ExtractionResult:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(str(path), read_only=True, data_only=True)
        lines = []
        for sheet in wb.sheetnames[:3]:
            ws = wb[sheet]
            for row in ws.iter_rows(max_row=50, values_only=True):
                line = " | ".join(str(c) for c in row if c is not None)
                if line:
                    lines.append(line)
        wb.close()
        text = "\n".join(lines)[:2000]
        return ExtractionResult(text_content=text, file_type="xlsx")
    except ImportError:
        logger.info("openpyxl not installed, skipping .xlsx extraction")
        return ExtractionResult(file_type="xlsx")
    except Exception as e:
        logger.warning("Failed to extract xlsx %s: %s", path, e)
        return ExtractionResult(file_type="xlsx")
