from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from pytesseract import image_to_string

try:
    from pdf2image import convert_from_path
except Exception:  # noqa: BLE001
    convert_from_path = None

ORIGINALITY_SCORE_RE = re.compile(r"(?:originality|similarity|score|ציון)[^\d]{0,12}(\d{1,3}(?:\.\d+)?)\s*%?", re.IGNORECASE)
PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def extract_text_from_pdf(path: str | Path) -> str:
    text_parts: list[str] = []
    reader = PdfReader(str(path))
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text:
            text_parts.append(page_text)
    text = "\n".join(text_parts)
    if text.strip():
        return text

    # OCR is used only when direct text extraction failed.
    if convert_from_path is None:
        return text
    try:
        images = convert_from_path(str(path), first_page=1, last_page=2)
        ocr_chunks = [image_to_string(img, lang="heb+eng") for img in images]
        return "\n".join([chunk for chunk in ocr_chunks if chunk.strip()])
    except Exception:  # noqa: BLE001
        return text


def extract_originality_score(text: str) -> float | None:
    match = ORIGINALITY_SCORE_RE.search(text)
    if match:
        value = float(match.group(1))
        if 0 <= value <= 100:
            return value

    for fallback in PERCENT_RE.findall(text):
        value = float(fallback)
        if 0 <= value <= 100:
            return value
    return None
